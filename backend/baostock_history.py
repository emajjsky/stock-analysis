"""BaoStock 0.9.4 独立进程历史会话；不与腾讯日线拼接。"""
import hashlib
import json
import socket
import time
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


_ready=False


class DeadlineSocket:
    """SDK在EOF时可能循环接收空字节；使其返回明确网络错误。"""
    def __init__(self,sock):self.socket=sock;self.deadline=0;self.received=0
    def __getattr__(self,name):return getattr(self.socket,name)
    def send(self,data):
        self.deadline=time.monotonic()+45;self.received=0
        self.socket.settimeout(20)
        return self.socket.send(data)
    def recv(self,count):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('历史响应超过45秒')
        self.socket.settimeout(min(20,remaining))
        data=self.socket.recv(count)
        if not data:raise ConnectionError('历史连接提前关闭')
        self.received+=len(data)
        if self.received>8*1024*1024:raise ValueError('单页历史响应超过上限')
        return data


def initialize():
    socket.setdefaulttimeout(20)
    import baostock.util.socketutil as transport
    import baostock.common.context as context
    original=transport.SocketUtil.connect
    if not getattr(original,'_wangzha_safe',False):
        def connect(self,api_key):
            original(self,api_key)
            raw=getattr(context,'default_socket',None)
            if raw is not None:context.default_socket=DeadlineSocket(raw)
        connect._wangzha_safe=True
        transport.SocketUtil.connect=connect
    time.sleep((os.getpid()%7)*.2)


def ensure_session():
    global _ready
    import baostock as bs
    if _ready:return
    for attempt in range(3):
        status=bs.login()
        if status.error_code=='0':_ready=True;return
        time.sleep(1+attempt)
    raise ValueError('BaoStock登录失败：'+status.error_msg)


def download(args):
    global _ready
    import baostock as bs
    ensure_session()
    sid,target,start=args
    result=bs.query_history_k_data_plus(sid.removeprefix('LIVE.').lower(),
        'date,open,high,low,close,volume,amount,tradestatus',
        start_date=start,end_date=target,frequency='d',adjustflag='3')
    if result.error_code!='0':
        _ready=False
        raise ValueError('BaoStock历史请求失败：'+result.error_msg)
    # 0.9.4服务端对三种复权请求均可能不回显标识；固定请求3，并拒绝明确的其他口径。
    # 已用同证券同日期的3/2/1响应实测其价格分别不同，不把空回显误当接口失败。
    if result.adjustflag not in ('','3') or result.frequency!='d' or result.code.lower()!=sid.removeprefix('LIVE.').lower():
        raise ValueError('BaoStock返回的证券、周期或复权身份不符')
    rows=[];diagnostics=[];fetched=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    if result.adjustflag=='':diagnostics.append({'action':'SOURCE_ADJUSTMENT_ACK_OMITTED','requested_adjustflag':'3'})
    while result.error_code=='0' and result.next():
        raw=result.get_row_data()
        day,o,h,l,c,v,a,status=raw
        if status!='1':continue
        try:
            prices=list(map(Decimal,(o,h,l,c)));volume=Decimal(v);amount=Decimal(a)
            if any(not p.is_finite() or p<=0 for p in prices) or not volume.is_finite() or volume<0 or volume!=int(volume) or not amount.is_finite() or amount<0:raise ValueError()
            if prices[1]<max(prices[0],prices[3]) or prices[2]>min(prices[0],prices[3]) or prices[1]<prices[2]:raise ValueError()
        except (ValueError,InvalidOperation):
            diagnostics.append({'date':day,'action':'INVALID_SOURCE_ROW_SKIPPED'});continue
        rows.append(dict(time=day,open=o,high=h,low=l,close=c,volume=int(volume),amount=a,
                         source='BaoStock公开日线 / 未复权',source_time=day+'T07:00:00Z',fetched_at=fetched,
                         raw_hash=hashlib.sha256(json.dumps(raw).encode()).hexdigest(),adjustment='NONE'))
    if result.error_code!='0':raise ValueError('BaoStock历史分页中断，未提交该证券')
    # SDK next()在接收失败时可能仅返回False、不改error_code；满页残留表示下一页未确认。
    from baostock.common.contants import BAOSTOCK_PER_PAGE_COUNT
    if len(result.data)==BAOSTOCK_PER_PAGE_COUNT and result.cur_row_num>=len(result.data):
        _ready=False
        raise ValueError('BaoStock最后分页未确认，未提交不完整历史')
    if any(a['time']>=b['time'] for a,b in zip(rows,rows[1:])):raise ValueError('BaoStock日期重复或顺序异常')
    if not rows:raise ValueError('BaoStock没有返回有效完成日线')
    time.sleep(.25)
    return rows,diagnostics
