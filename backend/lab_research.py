"""可解释研究规则和个股诊断；条件命中不是盈利概率。"""
import math
from datetime import datetime, timedelta, timezone

CHINA=timezone(timedelta(hours=8))


def session_context(at=None):
    d=(at or datetime.now(timezone.utc)).astimezone(CHINA);minute=d.hour*60+d.minute
    phase='休市' if d.weekday()>4 else '盘前' if minute<570 else '上午盘' if minute<690 else '午间休市' if minute<780 else '下午盘' if minute<900 else '收盘后'
    return dict(batch_date=d.date().isoformat(),session=phase,calendar_note='时段按北京时间工作日划分；是否交易以来源实际交易日为准')


EXTRA=[
 dict(id='ma-cross',name='均线金叉',group='趋势',description='本根短均线向上穿越长均线，区别于已经处于多头趋势。',minimum=21,parameters={'fast':5,'slow':20},schema={'fast':[2,60],'slow':[3,250]},supports=['daily']),
 dict(id='drawdown',name='回撤上限',group='风险',description='当前价格距窗口最高收盘价的回撤不超过设定上限。',minimum=21,parameters={'window':20,'max_pct':10},schema={'window':[5,250],'max_pct':[1,60]},supports=['daily']),
 dict(id='range-position',name='区间位置',group='位置',description='价格位于窗口高低价区间的指定位置，筛查低位或高位区域。',minimum=20,parameters={'window':20,'lower':20,'upper':80},schema={'window':[5,250],'lower':[0,99],'upper':[1,100]},supports=['daily']),
 dict(id='volume-contraction',name='缩量整理',group='量价',description='当日成交量低于此前均量的一定比例；需结合趋势判断。',minimum=21,parameters={'window':20,'ratio':0.7},schema={'window':[5,120],'ratio':[0.1,1]},supports=['daily']),
 dict(id='donchian',name='价格新高突破',group='突破',description='收盘突破此前窗口最高价，不额外要求放量。',minimum=21,parameters={'window':20},schema={'window':[5,250]},supports=['daily']),
 dict(id='kdj',name='KDJ金叉',group='动能',description='以9周期高低价计算K、D，观察本根K向上穿越D。',minimum=12,parameters={},schema={},supports=['daily']),
 dict(id='volatility',name='收益波动过滤',group='风险',description='窗口内每日收益率标准差不超过阈值；与ATR价格振幅不同。',minimum=21,parameters={'window':20,'max_pct':3},schema={'window':[5,120],'max_pct':[0.1,20]},supports=['daily']),
 dict(id='quote-turnover',name='换手率区间',group='报价',description='使用来源报价的换手率，筛查当前活跃程度。',minimum=0,parameters={'lower':1,'upper':10},schema={'lower':[0,99],'upper':[0.1,100]},supports=['intraday']),
 dict(id='quote-range',name='日内位置',group='报价',description='最新价在今日最高最低区间的位置，需有效高低价。',minimum=0,parameters={'lower':70,'upper':100},schema={'lower':[0,99],'upper':[1,100]},supports=['intraday']),
 dict(id='intraday-vwap',name='分时均价线之上',group='分时',description='最新成交价高于来源提供的当日成交均价；没有真实均价则不计算。',minimum=1,parameters={},schema={},supports=['intraday']),
 dict(id='intraday-breakout',name='分时窗口突破',group='分时',description='当前采样价格超过此前N个分时点；不等于标准分钟OHLC突破。',minimum=21,parameters={'window':20},schema={'window':[5,120]},supports=['intraday']),
]
EXTRA_MAP={a['id']:a for a in EXTRA}
QUOTE_IDS={'price-change','quote-turnover','quote-range'}


def extra_compute(selection,bars,quote):
    aid=selection['id'];a=EXTRA_MAP[aid];p=selection['parameters'];q=quote or {}
    r=dict(id=aid,name=a['name'],version='1.0.0',status='READY',matched=False,stance='WAIT',value=None,reason='',markers=[])
    def missing(reason):return {**r,'status':'MISSING','reason':reason}
    if aid.startswith('quote-'):
        try:
            if aid=='quote-turnover':value=float(q['turnover_rate'])
            else:
                low,high,price=(float(q[k]) for k in ('low','high','price'))
                if high<=low:return missing('日内高低价无有效区间')
                value=(price-low)/(high-low)*100
        except (KeyError,TypeError,ValueError):return missing('来源报价缺少换手率或日内高低价')
        if not math.isfinite(value):return missing('来源数值无效')
        r.update(value=round(value,3),matched=p['lower']<=value<=p['upper'],reason=f'当前 {value:.2f}%，设定区间 {p["lower"]}～{p["upper"]}%')
        r['stance']='WATCH' if r['matched'] else 'WAIT';return r
    required=max(a['minimum'],int(p.get('window',0))+(0 if aid=='range-position' else 1),int(p.get('slow',0))+1)
    if len(bars)<required:return missing(f'需要至少 {required} 根/点，当前 {len(bars)}')
    c=[float(b['close']) for b in bars];current=c[-1]
    if not all(math.isfinite(x) and x>0 for x in c):return missing('价格序列无效')
    w=int(p.get('window',20));value=None;hit=False;reason=''
    if aid=='ma-cross':
        f,s=int(p['fast']),int(p['slow']);before=sum(c[-f-1:-1])/f-sum(c[-s-1:-1])/s;after=sum(c[-f:])/f-sum(c[-s:])/s
        hit=before<=0<after;value=after;reason=f'短长均线差：前值 {before:.4f}，现值 {after:.4f}；须本根上穿'
    elif aid=='drawdown':
        value=(1-current/max(c[-w:]))*100;hit=value<=p['max_pct'];reason=f'距{w}日最高收盘回撤 {value:.2f}%，上限 {p["max_pct"]}%'
    elif aid=='range-position':
        hi=max(float(b['high']) for b in bars[-w:]);lo=min(float(b['low']) for b in bars[-w:])
        if hi<=lo:return missing('窗口高低价区间为零')
        value=(current-lo)/(hi-lo)*100;hit=p['lower']<=value<=p['upper'];reason=f'{w}日区间位置 {value:.2f}%，目标 {p["lower"]}～{p["upper"]}%'
    elif aid=='volume-contraction':
        avg=sum(float(b['volume']) for b in bars[-w-1:-1])/w
        if avg<=0:return missing('此前均量无效')
        value=float(bars[-1]['volume'])/avg;hit=value<=p['ratio'];reason=f'当日量/此前{w}日均量 {value:.2f}倍，上限 {p["ratio"]}'
    elif aid in {'donchian','intraday-breakout'}:
        high=max(float(b['high'] if aid=='donchian' else b['close']) for b in bars[-w-1:-1]);value=high;hit=current>high;reason=f'当前 {current:.3f}，此前{w}{"日高价" if aid=="donchian" else "采样点最高价"} {high:.3f}'
    elif aid=='volatility':
        changes=[(b/a-1)*100 for a,b in zip(c[-w-1:-1],c[-w:])];mean=sum(changes)/w;value=math.sqrt(sum((x-mean)**2 for x in changes)/w);hit=value<=p['max_pct'];reason=f'{w}日收益标准差 {value:.2f}%，上限 {p["max_pct"]}%'
    elif aid=='kdj':
        k=d=50;previous=0
        for i in range(8,len(bars)):
            chunk=bars[i-8:i+1];hi=max(float(b['high']) for b in chunk);lo=min(float(b['low']) for b in chunk);rsv=(c[i]-lo)/(hi-lo)*100 if hi>lo else 50
            previous=k-d;k=2*k/3+rsv/3;d=2*d/3+k/3
        value=k-d;hit=previous<=0<value;reason=f'K {k:.2f} / D {d:.2f} / J {3*k-2*d:.2f}；须本根上穿'
    elif aid=='intraday-vwap':
        try:value=float(bars[-1]['average_price'])
        except (KeyError,TypeError,ValueError):return missing('来源没有可验证的成交均价，不能用简单平均价代替')
        if not math.isfinite(value) or value<=0:return missing('来源成交均价无效')
        hit=current>value;reason=f'当前 {current:.3f} / 来源成交均价 {value:.3f}'
    r.update(value=round(value,6),matched=hit,stance=('PASS' if aid in {'drawdown','volatility'} else 'WATCH') if hit else 'WAIT',reason=reason)
    if hit:r['markers']=[dict(time=bars[-1]['time'],text=a['name'],direction='WATCH')]
    return r


def diagnose(bars):
    if len(bars)<20:return dict(status='MISSING',summary='至少需要20根完成日线，补齐后才能分析趋势和关键价位。',metrics=[],conditions=[])
    c=[float(b['close']) for b in bars];p=c[-1];ma5=sum(c[-5:])/5;ma20=sum(c[-20:])/20
    support=min(float(b['low']) for b in bars[-20:]);resistance=max(float(b['high']) for b in bars[-20:])
    tr=[max(float(b['high'])-float(b['low']),abs(float(b['high'])-c[i-1]),abs(float(b['low'])-c[i-1])) for i,b in enumerate(bars) if i];atr=sum(tr[-14:])/14
    trend='短期偏强' if p>ma5>ma20 else '短期偏弱' if p<ma5<ma20 else '趋势分歧 / 整理'
    metrics=[dict(label='完成日线收盘',value=round(p,3)),dict(label='MA5 / MA20',value=f'{ma5:.3f} / {ma20:.3f}'),dict(label='20日区间低点',value=round(support,3)),dict(label='20日区间高点',value=round(resistance,3)),dict(label='近14日平均真实振幅',value=round(atr,3)),dict(label='20日价格变化',value=f'{(p/c[-21]-1)*100:.2f}%' if len(c)>20 else '数据不足')]
    weeks={}
    for b in bars:
        year,week,_=datetime.fromisoformat(b['time'][:10]).isocalendar();weeks[(year,week)]=float(b['close'])
    weekly=list(weeks.values())
    metrics.append(dict(label='周线位置（末周可能未完成）',value=('高于' if p>sum(weekly[-5:])/5 else '低于')+'近5周收盘均值' if len(weekly)>=5 else '不足5周'))
    return dict(status='READY',summary=trend,as_of=bars[-1]['time'],price=p,atr=atr,support=support,resistance=resistance,metrics=metrics,
                conditions=[f'向上观察：后续完成收盘突破 {resistance:.3f}，再核对量能；目前高点不是保证可突破的目标价。',f'向下观察：跌破区间低点 {support:.3f} 或持续低于MA20 {ma20:.3f} 时，重新评估风险。',f'当前振幅约 {atr/p*100:.2f}%；持仓决策还需成本、可卖数量与风险预算，A股当日新买不能当天卖。'],
                limitations=['价位是历史区间统计，未验证为有效支撑压力或自动买卖点；未复权数据需核对除权。'])


def event_assessment(article):
    title=article.get('title','');positive=['预增','扭亏','中标','回购','增持'];negative=['预亏','减持','立案','处罚','退市','违约','亏损']
    pos=[w for w in positive if w in title];neg=[w for w in negative if w in title]
    qualified=any(w in title for w in ('终止','取消','未','不','澄清','完成','届满'))
    direction='方向不确定' if qualified else '偏正面线索' if pos and not neg else '偏负面线索' if neg and not pos else '方向不确定'
    return {**{k:article.get(k) for k in ('id','title','url','published_at','source')},'direction':direction,'evidence_type':'TITLE_ONLY',
            'reason':('标题包含：'+'、'.join(pos+neg)) if pos or neg else '标题不足以判断对业绩、现金流和股价预期的影响',
            'verification':'仅标题初筛，未读正文；须核对金额、基数、实施进度、预期差及公告原文，方向可能相反。'}
