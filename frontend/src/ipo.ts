import type { MarketColumn } from './components/BoardDataTable.vue';
export interface IpoRow {
  id: string; code?: string; name?: string; security_id?: string | null; document_url?: string | null;
  title?: string; summary?: string; published_at?: string; url?: string | null;
  [key: string]: any;
}
export interface IpoPage {
  rows: IpoRow[]; total: number; pages: number; page: number; page_size: number;
  section: string; board: string; fetched_at: string | null; source?: string; source_url?: string;
  refreshing: boolean; status: string; error?: string | null; enabled: boolean; stale: boolean;
}
export const ipoTabs = [
  { id: 'home', label: '新股首页' }, { id: 'apply', label: '新股申购' },
  { id: 'disclosure', label: '新股预披露' }, { id: 'review', label: '新股上会' },
  { id: 'returns', label: '打新收益' }, { id: 'bonds', label: '转债申购' },
  { id: 'us', label: '美股新股', url: 'https://www.nasdaq.com/market-activity/ipos' },
  { id: 'star', label: '科创板新股' },
  { id: 'hk', label: '港股IPO', url: 'https://www.aastocks.com/tc/stocks/market/ipo/mainpage.aspx' },
  { id: 'hkperformance', label: '港股新股表现', url: 'https://www.aastocks.com/tc/stocks/market/ipo/listedipo.aspx' },
];
export const ipoBoards = [{ id: 'all', label: '全部A股' }, { id: 'sh', label: '沪市主板' }, { id: 'sz', label: '深市主板' },
  { id: 'gem', label: '创业板' }, { id: 'star', label: '科创板' }, { id: 'bj', label: '北交所' }];
const text = (key: string, label: string): MarketColumn => ({ key, label, format: 'text' });
const price = (key: string, label: string): MarketColumn => ({ key, label, format: 'price' });
const pct = (key: string, label: string, color = false): MarketColumn => ({ key, label, format: 'percent', color });
export const inWan = (value: unknown) => value == null ? '—' : (Number(value)/10000).toLocaleString('zh-CN', {maximumFractionDigits: 2});
const wan = (key: string, label: string, unit: string): MarketColumn => ({ key, label, unit, formatValue: r => inWan(r[key]) });
const base = [text('name','名称'), text('code','代码')];
export const listedColumns: MarketColumn[] = [...base, pct('change_pct','涨跌幅',true),price('price','现价'),text('listing_date','上市日期'),
  {key:'volume_lots',label:'成交量',unit:'手',formatValue:r=>r.volume_lots==null?'—':Number(r.volume_lots)>=10000?(Number(r.volume_lots)/10000).toFixed(2)+'万':Number(r.volume_lots).toLocaleString('zh-CN')},
  pct('turnover_rate','换手率'),wan('amount','成交额','万元'),price('pe_dynamic','动态PE'),
  {key:'market_cap',label:'总市值',unit:'亿元',formatValue:r=>r.market_cap==null?'—':(Number(r.market_cap)/1e8).toFixed(2)},
  text('industry','所属行业'),price('issue_price','发行价'),pct('total_return','上市价差',true)];
export const pendingColumns: MarketColumn[] = [...base,text('apply_date','申购日期'),text('apply_code','申购代码'),text('listing_date','上市日期'),
  price('issue_price','发行价'),wan('issue_shares','发行总数','万股'),wan('apply_limit','申购上限','万股'),price('issue_pe','发行PE')];
export const applyColumns: MarketColumn[] = [...base,text('apply_code','申购代码'),text('apply_date','申购日期'),price('issue_price','发行价'),
  wan('issue_shares','发行总数','万股'),wan('online_shares','网上发行','万股'),wan('apply_limit','申购上限','万股'),
  wan('required_cap','顶格所需市值','万元'),wan('required_cash','顶格所需资金','万元'),price('issue_pe','发行PE'),price('industry_pe','行业PE'),
  pct('win_rate','中签/配售率'),text('ballot_date','中签公布'),text('pay_date','缴款日期'),text('listing_date','上市日期')];
export const reviewColumns: MarketColumn[] = [text('name','公司名称'),text('board','上市板块'),text('review_date','上会日期'),text('status','审核状态'),
  wan('issue_shares','拟发行数量','万股'),wan('planned_funds','拟募集资金','万元'),text('notice_date','公告日期'),text('listing_date','上市日期'),text('sponsor','保荐/主承销商')];
export const disclosureColumns: MarketColumn[] = [text('name','公司名称'),text('update_date','更新日期'),text('accept_date','受理日期'),
  text('board','拟上市板块'),text('status','当前进度'),text('industry','所属行业'),text('region','注册地'),text('sponsor','保荐机构')];
export const returnColumns: MarketColumn[] = [...base,text('listing_date','上市日期'),price('issue_price','发行价'),price('price','最新价'),
  price('first_open','首日开盘'),price('first_close','首日收盘'),price('first_high','首日最高'),pct('first_change','首日涨幅',true),
  { ...price('first_profit','每签首日收益'), color:true },{ ...price('profit_per_100','每百股首日收益'), color:true },
  {key:'broken',label:'首日破发',formatValue:r=>r.first_close==null||r.issue_price==null?'—':Number(r.first_close)<Number(r.issue_price)?'是':'否'}];
export const bondColumns: MarketColumn[] = [...base,text('apply_code','申购代码'),text('apply_date','申购日期'),text('listing_date','上市日期'),
  price('issue_price','发行价'),wan('issue_amount','发行规模','万元'),pct('win_rate','中签率'),text('rating','评级'),text('stock_name','正股名称'),text('stock_code','正股代码')];
