<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { Search, RefreshCw, ChevronLeft, ChevronRight, ExternalLink, Star, PanelRightClose, PanelRightOpen, FileText } from 'lucide-vue-next';
import { api, post } from '../api';
import { addWatch, state } from '../state';
import { date, direction, money } from '../format';
import type { Bar, Security } from '../types';
import type { Intraday } from '../terminal';
import { percent } from '../terminal';
import { ipoTabs, ipoBoards, listedColumns, pendingColumns, applyColumns, disclosureColumns, reviewColumns, returnColumns, bondColumns, inWan, type IpoPage, type IpoRow } from '../ipo';
import BoardDataTable from '../components/BoardDataTable.vue';
import BoardMiniChart from '../components/BoardMiniChart.vue';
import WebBrowserView from './WebBrowserView.vue';
import { openWeb } from '../webBrowser';
const emit = defineEmits<{ open: [id:string] }>();
const tab = ref('home'), board = ref('all'), page = ref(1), query = ref(''), statusFilter = ref('all');
const data = ref<IpoPage>(), pending = ref<IpoPage>(), news = ref<IpoPage>();
const error = ref(''), loading = ref(false), selected = ref<IpoRow>();
const details = ref(true), mode = ref<'intraday'|'daily'>('intraday');
const intraday = ref<Intraday>(), bars = ref<Bar[]>([]), security = ref<Security>();
const chartError = ref(''), chartLoading = ref(false), addError = ref('');
let disposed = false, request = 0, chartRequest = 0;
let controller: AbortController | undefined, chartController: AbortController | undefined, timer: ReturnType<typeof setTimeout> | undefined;
const external = computed(() => ipoTabs.find(t=>t.id===tab.value)?.url);
const overview = computed(()=>tab.value==='home'||tab.value==='star');
const section = computed(()=>overview.value||tab.value==='returns'?'listed':tab.value);
const activeBoard = computed(()=>tab.value==='star'?'star':board.value);
const columns = computed(()=>overview.value?listedColumns:tab.value==='apply'?applyColumns:tab.value==='review'?reviewColumns:tab.value==='disclosure'?disclosureColumns:tab.value==='returns'?returnColumns:bondColumns);
const rows = computed(()=>(data.value?.rows||[]).filter(r=>
  (!query.value || `${r.name} ${r.code} ${r.apply_code||''}`.toLowerCase().includes(query.value.toLowerCase())) &&
  (tab.value!=='review'||statusFilter.value==='all'||(statusFilter.value==='passed'?r.status==='上会通过':statusFilter.value==='failed'?String(r.status).includes('未通过'):r.status==='未上会'))));
const watched = computed(()=>!!selected.value?.security_id && state.watchlists.some(w=>w.security_id===selected.value!.security_id));
const currentPrice = computed(()=>security.value?.quote?.price ?? selected.value?.price);
const currentChange = computed(()=>security.value?.quote?.change_pct ?? selected.value?.change_pct);
const empty = computed(()=>loading.value||data.value?.refreshing&&!data.value.rows.length?'正在加载发行资料…':error.value||data.value?.error||(!data.value?.enabled&&!data.value?.rows.length?'自动更新已关闭，可点击刷新获取资料':'暂无符合条件的记录'));

async function load() {
  if (external.value) return;
  const seq = ++request, key = section.value, b = activeBoard.value, n = page.value;
  controller?.abort(); const c = new AbortController(); controller = c;
  loading.value = true;
  try {
    const result = await api<IpoPage>(`/market/ipo?section=${key}&board=${b}&page=${n}`, {signal:c.signal});
    if (seq!==request||disposed) return;
    data.value = result.data; error.value='';
    if (selected.value && pending.value?.rows.some(r=>r.id===selected.value?.id)) { /* 保留待上市表当前选择。 */ }
    else if (!selected.value || !result.data.rows.some(r=>r.id===selected.value?.id))
      selected.value=result.data.rows.find(r=>!!r.security_id)||result.data.rows[0];
    else selected.value=result.data.rows.find(r=>r.id===selected.value?.id);
    if (overview.value) {
      const results = await Promise.allSettled([
        api<IpoPage>(`/market/ipo?section=pending&board=${b}`, {signal:c.signal}),
        api<IpoPage>('/market/ipo?section=news', {signal:c.signal}),
      ]);
      if(seq!==request||disposed) return;
      if(results[0].status==='fulfilled')pending.value=results[0].value.data;
      if(results[1].status==='fulfilled')news.value=results[1].value.data;
    }
  } catch(e) { if(!c.signal.aborted) error.value=e instanceof Error?e.message:'资料加载失败'; }
  finally { if(seq===request)loading.value=false; }
}
async function refreshData() {
  if(external.value)return;
  try {
    await post(`/market/ipo/refresh?section=${section.value}&board=${activeBoard.value}&page=${page.value}`);
    if(overview.value) await Promise.allSettled([post(`/market/ipo/refresh?section=pending&board=${activeBoard.value}`),post('/market/ipo/refresh?section=news')]);
    await load();
  } catch(e){error.value=e instanceof Error?e.message:'刷新失败';}
}
async function loadChart(activate=false) {
  const row=selected.value, id=row?.security_id, seq=++chartRequest;
  chartController?.abort(); const c=new AbortController(); chartController=c;
  if(!id||!overview.value||!details.value){chartLoading.value=false;return;}
  chartLoading.value=true;
  try {
    if(activate)await post(`/securities/${encodeURIComponent(id)}/activate`);
    if(seq!==chartRequest||disposed)return;
    const results=await Promise.all([
      api<Security>(`/securities/${encodeURIComponent(id)}`,{signal:c.signal}),
      mode.value==='intraday'?api<Intraday>(`/market/intraday?security_id=${encodeURIComponent(id)}`,{signal:c.signal}):
        api<{bars:Bar[]}>(`/market/bars?security_id=${encodeURIComponent(id)}&adjustment=none&timeframe=1d`,{signal:c.signal}),
    ]);
    if(seq!==chartRequest||disposed)return;
    security.value=results[0].data;
    if(mode.value==='intraday'){intraday.value=results[1].data as Intraday;chartError.value=intraday.value.error||'';}
    else{bars.value=(results[1].data as {bars:Bar[]}).bars;chartError.value='';}
  }catch(e){if(!c.signal.aborted)chartError.value=e instanceof Error?e.message:'走势加载失败';}
  finally{if(seq===chartRequest)chartLoading.value=false;}
}
function select(id:string, source=data.value){selected.value=source?.rows.find(r=>r.id===id);}
async function add() {
  if(!selected.value?.security_id||watched.value)return;
  addError.value='';
  try{await addWatch(selected.value.security_id);}catch(e){addError.value=e instanceof Error?e.message:'加入自选失败';}
}
function openSelected() {if(selected.value?.security_id)emit('open',selected.value.security_id);}
function newsTime(r:IpoRow) {return r.published_at?date(r.published_at):'—';}
async function poll(){await load();if(overview.value)await loadChart();if(!disposed)timer=setTimeout(poll,5000);}
watch([tab,board],()=>{
  request++;controller?.abort(); page.value=1;query.value='';statusFilter.value='all';data.value=undefined;pending.value=undefined;selected.value=undefined;error.value='';
  void load();
});
watch(page,()=>{selected.value=undefined;data.value=undefined;void load();});
watch(()=>selected.value?.id,()=>{intraday.value=undefined;bars.value=[];security.value=undefined;chartError.value='';addError.value='';void loadChart(true);});
watch([mode,details],()=>{intraday.value=undefined;bars.value=[];void loadChart();});
onMounted(()=>void poll());
onUnmounted(()=>{disposed=true;request++;chartRequest++;clearTimeout(timer);controller?.abort();chartController?.abort();});
</script>
<template>
  <section class="ipo-workspace">
    <header class="ipo-navigation"><nav aria-label="新股栏目"><button v-for="t in ipoTabs" :key="t.id" :class="{active:tab===t.id}" :aria-current="tab===t.id?'page':undefined" @click="tab=t.id">{{t.label}}<ExternalLink v-if="t.url" :size="11"/></button></nav></header>
    <WebBrowserView v-if="external" :key="tab" :initial-url="external"/>
    <template v-else>
      <div class="ipo-tools">
        <nav v-if="tab!=='bonds'&&tab!=='star'" class="ipo-board-tabs" aria-label="新股市场"><button v-for="b in ipoBoards" :key="b.id" :class="{active:board===b.id}" @click="board=b.id">{{b.label}}</button></nav>
        <strong v-else>{{tab==='star'?'科创板新股':'可转债发行与申购'}}</strong>
        <label class="ipo-search"><Search :size="15"/><input v-model="query" placeholder="筛选本页名称 / 代码" aria-label="筛选本页新股"/></label>
        <button class="icon-button" aria-label="刷新新股资料" title="刷新新股资料" :disabled="loading||data?.refreshing" @click="refreshData"><RefreshCw :size="17" :class="{spinning:data?.refreshing}"/></button>
        <button v-if="overview" class="icon-button" :aria-label="details?'收起新股详情':'展开新股详情'" @click="details=!details"><component :is="details?PanelRightClose:PanelRightOpen" :size="18"/></button>
      </div>
      <div v-if="tab==='review'" class="ipo-review-tabs" aria-label="审核状态"><button v-for="s in [{id:'all',label:'全部申报'},{id:'upcoming',label:'待上会'},{id:'passed',label:'上会通过'},{id:'failed',label:'上会未通过'}]" :key="s.id" :class="{active:statusFilter===s.id}" @click="statusFilter=s.id">{{s.label}}</button></div>
      <div v-if="error||data?.error" class="ipo-error" role="alert">{{error||data?.error}}<button class="text-button" @click="refreshData">重试</button></div>
      <div class="ipo-body" :class="{'ipo-overview':overview,'ipo-details-hidden':!details}">
        <div class="ipo-tables">
          <section class="ipo-panel ipo-primary-table">
            <header class="ipo-panel-heading"><h3>{{overview?'已上市新股':ipoTabs.find(t=>t.id===tab)?.label}}</h3><span>{{rows.length}} 条<span v-if="overview"> · 按上市日期排序</span></span><button v-if="tab==='disclosure'" class="text-button" @click="openWeb('https://data.10jqka.com.cn/ipo/xgpt/')">预披露原站 <ExternalLink :size="13"/></button></header>
            <div v-if="tab==='disclosure'" class="ipo-data-note">当前为申报企业及招股说明书目录，更新日期不等于首次预披露日期；原站预披露记录可从右上角打开。</div>
            <BoardDataTable :key="tab+activeBoard+page" :rows="rows" :columns="columns" :selected="selected?.id" :initial-sort="overview||tab==='returns'?'listing_date':tab==='review'?'review_date':tab==='disclosure'?'update_date':'apply_date'" :empty="empty" @select="select($event)"/>
            <footer class="ipo-table-footer"><span>共 {{data?.total||0}} 条<span v-if="query||statusFilter!=='all'"> · 当前页筛选 {{rows.length}} 条</span></span><div class="ipo-pager"><button class="icon-button" aria-label="上一页新股" :disabled="page<=1||loading" @click="page--"><ChevronLeft :size="16"/></button><span>{{page}} / {{data?.pages||1}}</span><button class="icon-button" aria-label="下一页新股" :disabled="page>=(data?.pages||1)||loading" @click="page++"><ChevronRight :size="16"/></button></div><details><summary>数据来源</summary><div><p>{{data?.source||'东方财富公开发行/审核资料'}} · 缓存更新 {{date(data?.fetched_at)}}</p><p>发行资料及其附带行情约5分钟检查更新，不是实时推送。北交所按资金申购、按配售结果计算；沪深按来源的每签股数与收益字段展示。收益为税费前历史数据。</p></div></details></footer>
          </section>
          <section v-if="overview" class="ipo-panel ipo-pending-table"><header class="ipo-panel-heading"><h3>待上市新股</h3><span>{{pending?.total||0}} 条</span></header><BoardDataTable :rows="pending?.rows||[]" :columns="pendingColumns" initial-sort="apply_date" :selected="selected?.id" :empty="pending?.refreshing?'正在加载待上市资料…':pending?.error||'近期暂无待上市新股'" @select="select($event,pending)"/></section>
        </div>
        <aside v-if="overview&&details" class="ipo-aside">
          <section class="ipo-panel ipo-chart-panel"><header class="ipo-panel-heading"><button class="text-button ipo-stock-name" @click="openSelected" :disabled="!selected?.security_id">{{selected?.name||'选择新股'}}</button><span>{{selected?.code}}</span><strong :class="direction(currentChange)">{{money(currentPrice)}}</strong><strong :class="direction(currentChange)">{{percent(currentChange)}}</strong></header>
            <div class="ipo-chart-tools"><div class="segmented"><button :class="{active:mode==='intraday'}" @click="mode='intraday'">分时</button><button :class="{active:mode==='daily'}" @click="mode='daily'">日K</button></div><span v-if="intraday?.trade_date">{{intraday.trade_date}}</span><button class="icon-button" :aria-label="watched?'已在自选':'将新股加入自选'" :disabled="!selected?.security_id||watched" @click="add"><Star :size="16" :fill="watched?'currentColor':'none'"/></button></div>
            <div v-if="chartError||addError" class="ipo-error">{{chartError||addError}}</div>
            <div class="ipo-chart"><BoardMiniChart v-if="selected?.security_id && (mode==='intraday'?intraday?.points.length:bars.length)" :key="selected.id" :mode="mode" :points="intraday?.points" :bars="bars" :previous-close="security?.quote?.previous_close"/>
              <div v-else class="ipo-chart-empty">{{chartLoading?'正在读取走势…':!selected?'点击列表选择新股':!selected.security_id?(selected.status==='已上市'?'该市场走势尚未接入，可查看原站':'尚未上市，暂无交易走势'):'暂无走势数据'}}<button v-if="selected&&!selected.security_id" class="text-button" @click="openWeb('https://stockpage.10jqka.com.cn/'+selected.code+'/')">查看原站 <ExternalLink :size="13"/></button></div>
            </div>
            <div class="ipo-issuer-metrics"><div><span>发行价</span><strong>{{money(selected?.issue_price)}}</strong></div><div><span>上市日期</span><strong>{{selected?.listing_date||'待公布'}}</strong></div><div><span>首日涨幅</span><strong :class="direction(selected?.first_change)">{{percent(selected?.first_change)}}</strong></div><div><span>上市至今</span><strong :class="direction(selected?.total_return)">{{percent(selected?.total_return)}}</strong></div></div>
          </section>
          <section class="ipo-panel ipo-news"><header class="ipo-panel-heading"><h3>新股要闻</h3><button class="text-button" @click="openWeb('https://stock.10jqka.com.cn/newstock/')">更多 <ExternalLink :size="13"/></button></header><div class="ipo-news-list"><button v-for="item in news?.rows" :key="item.id" :title="item.summary" @click="item.url?openWeb(item.url):openWeb('https://finance.sina.com.cn/')"><span>{{item.title}}</span><time>{{newsTime(item)}}</time></button><div v-if="!news?.rows.length" class="ipo-chart-empty">{{news?.refreshing?'正在获取新股快讯…':news?.error||'最新快讯中暂无新股相关内容'}}</div></div></section>
        </aside>
      </div>
      <section v-if="!overview && selected" class="ipo-selection-strip"><div><strong>{{selected.name}}</strong><span>{{selected.code}}</span><span>{{selected.board||selected.stock_name}}</span><span v-if="selected.status">{{selected.status}}</span></div><span v-if="tab==='apply'">{{activeBoard==='bj'?'按资金申购':'发行数量'}} {{inWan(activeBoard==='bj'?selected.required_cash:selected.issue_shares)}} {{activeBoard==='bj'?'万元':'万股'}}</span><button v-if="selected.document_url" class="text-button" @click="openWeb(selected!.document_url!)"><FileText :size="15"/>招股书 / 公告</button><button v-if="selected.security_id" class="text-button" @click="openSelected">个股详情 <ExternalLink :size="14"/></button></section>
    </template>
  </section>
</template>
<style>
.ipo-workspace .ipo-navigation nav,.ipo-workspace .ipo-board-tabs{flex-direction:row}
.ipo-workspace nav>button{min-height:34px;box-shadow:none}
.ipo-workspace{display:flex;flex-direction:column;gap:12px;height:calc(100dvh - 100px);min-height:600px}.ipo-navigation{border-bottom:2px solid var(--ink);flex-shrink:0}.ipo-navigation nav{display:flex;overflow:auto;gap:3px}.ipo-navigation button{border:0;background:transparent;padding:10px 13px;white-space:nowrap;font-size:15px;font-weight:600;display:flex;align-items:center;gap:4px}.ipo-navigation button.active{background:var(--ink);color:var(--yellow);border-radius:5px 5px 0 0}.ipo-tools{display:flex;align-items:center;gap:9px;min-height:36px;flex-wrap:wrap}.ipo-board-tabs,.ipo-review-tabs{display:flex;gap:3px}.ipo-board-tabs button,.ipo-review-tabs button{background:transparent;border:0;border-radius:4px;padding:5px 10px;white-space:nowrap}.ipo-board-tabs button.active,.ipo-review-tabs button.active{background:#e7eced;color:var(--blue);font-weight:700}.ipo-search{display:flex;align-items:center;gap:6px;margin-left:auto;border:1px solid var(--line);border-radius:5px;background:var(--surface);padding:0 8px}.ipo-search input{width:195px;padding:5px 0;border:0;background:transparent}.ipo-body{flex:1;min-height:0;display:flex;gap:12px}.ipo-tables{min-width:0;display:flex;flex-direction:column;gap:12px;flex:1}.ipo-panel{border:1px solid #d9d2bf;background:var(--surface);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0}.ipo-panel-heading{display:flex;align-items:center;gap:12px;min-height:39px;padding:6px 12px;background:#f5f0df;border-bottom:1px solid var(--line);flex-shrink:0}.ipo-panel-heading h3{font-size:15px;font-weight:700}.ipo-panel-heading>span{font-size:13px;color:var(--muted)}.ipo-panel-heading>.text-button:last-child{margin-left:auto}.ipo-primary-table{flex:1}.ipo-pending-table{flex:0 0 30%;min-height:140px}.ipo-table-footer{display:flex;gap:14px;align-items:center;padding:4px 12px;border-top:1px solid var(--line);min-height:37px;font-size:12px;flex-shrink:0}.ipo-pager{display:flex;align-items:center;gap:5px;margin-left:auto}.ipo-table-footer details{position:relative}.ipo-table-footer summary{cursor:pointer;color:var(--muted)}.ipo-table-footer details>div{position:absolute;bottom:32px;right:0;background:var(--surface);border:1px solid var(--line);box-shadow:0 3px 20px #0002;width:360px;z-index:15;padding:14px;font-size:12px}.ipo-aside{width:37%;display:flex;flex-direction:column;gap:12px;min-width:330px}.ipo-chart-panel{flex:1.3;min-height:280px}.ipo-news{flex:1;min-height:140px}.ipo-chart-tools{display:flex;align-items:center;gap:10px;padding:7px 10px}.ipo-chart-tools>span{font-size:12px;color:var(--muted);margin-left:auto}.ipo-chart{flex:1;min-height:170px;display:flex;flex-direction:column}.ipo-chart>div{flex:1;min-height:0}.ipo-chart-empty{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:10px;height:100%;min-height:100px;padding:20px;color:var(--muted);font-size:13px}.ipo-issuer-metrics{display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;padding:9px 12px;border-top:1px solid var(--line);font-size:13px}.ipo-issuer-metrics>div{display:flex;justify-content:space-between;gap:10px}.ipo-issuer-metrics span{color:var(--muted)}.ipo-news-list{overflow:auto;min-height:0;flex:1;padding:0 10px}.ipo-news-list>button{display:flex;align-items:center;gap:12px;border:0;border-bottom:1px solid #eee8da;background:transparent;width:100%;padding:10px 0;text-align:left;font-size:14px}.ipo-news-list>button span{flex:1;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.ipo-news-list time{font-size:12px;color:var(--muted);white-space:nowrap}.ipo-selection-strip{display:flex;align-items:center;gap:18px;min-height:43px;font-size:13px}.ipo-selection-strip>div{display:flex;gap:15px;align-items:center;flex:1}.ipo-selection-strip>div>strong{font-size:15px}.ipo-selection-strip span{color:var(--muted)}.ipo-error{padding:6px 10px;color:var(--up);font-size:13px;display:flex;gap:10px;align-items:center}.ipo-data-note{padding:7px 12px;background:#fff2c5;font-size:12px;color:#746128}.ipo-workspace .market-grid{font-size:14px}.ipo-workspace .market-grid th{font-size:13px}.ipo-workspace .market-grid td{height:34px}.ipo-workspace .market-grid small{font-size:11px}.ipo-workspace .market-grid .name-cell{min-width:105px;max-width:320px}.ipo-workspace .web-workspace{flex:1;height:auto;min-height:0}
@media(max-width:1250px){.ipo-aside{width:36%;min-width:300px}.ipo-navigation button{padding:9px;font-size:14px}.ipo-overview .market-grid{font-size:13px}.ipo-board-tabs button{padding-inline:7px}.ipo-stock-name{max-width:120px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}}
@media(max-width:900px){.ipo-workspace{height:auto;min-height:calc(100dvh - 160px)}.ipo-body{min-height:650px}.ipo-overview{display:block}.ipo-aside{width:100%;min-height:650px;margin-top:12px}.ipo-overview .ipo-tables{height:650px}.ipo-tools{gap:5px}.ipo-selection-strip{flex-wrap:wrap}.ipo-selection-strip>div{min-width:100%}.ipo-search{margin-left:0}.ipo-table-footer details>div{width:290px}}
</style>
