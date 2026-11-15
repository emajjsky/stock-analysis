<script setup lang="ts">
import {ref,computed,watch} from 'vue';
import type {LabRun,LabRow,LabReview} from '../algorithmLab';
import {post} from '../api';
import {money,date} from '../format';
type ResultState={filter:'matched'|'all'|'missing';expanded:string;limit:number};
const props=defineProps<{run:LabRun;compact?:boolean;workspaceState?:ResultState}>();
defineEmits<{open:[string];monitor:[string];adjust:[]}>();
const local=ref<ResultState>({filter:props.compact?'all':'matched',expanded:'',limit:50});
const ui=computed(()=>props.workspaceState??local.value);
const review=ref<LabReview>(),reviewing=ref(false),reviewKind=ref('Agent'),error=ref('');
const missing=computed(()=>props.run.rows.filter(r=>r.missing>0).length);
const rows=computed(()=>ui.value.filter==='matched'?props.run.rows.filter(r=>r.matched):ui.value.filter==='missing'?props.run.rows.filter(r=>r.missing>0):props.run.rows);
watch(()=>props.run.id,()=>{ui.value.expanded='';review.value=undefined;error.value='';ui.value.limit=50;});
function filter(value:ResultState['filter']){ui.value.filter=value;ui.value.limit=50;}
function expand(id:string){ui.value.expanded=ui.value.expanded===id?'':id;review.value=undefined;error.value='';}
async function analyze(row:LabRow,decision=false){reviewing.value=true;reviewKind.value=decision?'Jev':'Agent';error.value='';review.value=undefined;try{review.value=(await post<LabReview>(decision?'/lab/decision':'/lab/review',{run_id:props.run.id,security_id:row.security.id})).data;}catch(e){error.value=String(e);}finally{reviewing.value=false;}}
</script>
<template>
  <div class="lab-result-summary" :data-run-id="run.id"><strong>计算 {{run.total}} 只 · 满足 {{run.matched}} 只 · 数据不足 {{run.skipped}} 只</strong><span class="tiny muted">完成于 {{date(run.finished_at)}}</span></div>
  <div v-if="!compact" class="lab-result-filters" role="group" aria-label="筛选计算结果"><button :class="{active:ui.filter==='matched'}" :aria-pressed="ui.filter==='matched'" @click="filter('matched')">符合条件 {{run.matched}}</button><button :class="{active:ui.filter==='all'}" :aria-pressed="ui.filter==='all'" @click="filter('all')">全部 {{run.total}}</button><button :class="{active:ui.filter==='missing'}" :aria-pressed="ui.filter==='missing'" @click="filter('missing')">数据不足 {{missing}}</button><span class="tiny muted">点击股票打开 K 线，展开依据核对各项条件。</span></div>
  <div class="lab-results" v-if="rows.length">
    <article v-for="row in rows.slice(0,ui.limit)" :key="row.security.id" class="lab-result" :class="{expanded:ui.expanded===row.security.id||compact}">
      <div class="lab-result-line"><button class="stock-link" :aria-label="'打开 '+row.security.name+' K线'" @click="$emit('open',row.security.id)"><strong>{{row.security.name}}</strong><span class="tiny muted">{{row.security.code}}</span></button><strong>{{money(row.price)}}</strong><span class="badge" :class="row.action==='风险观察'?'lab-risk':row.matched?'blue':''">{{row.action}}</span><span class="lab-hit">满足 {{row.hit_count}} / {{row.total}}</span><span class="tiny muted">数据 {{row.data_as_of??'缺失'}}</span><button v-if="!compact" class="text-button" :aria-expanded="ui.expanded===row.security.id" @click="expand(row.security.id)">{{ui.expanded===row.security.id?'收起依据':'查看依据'}}</button></div>
      <div v-if="ui.expanded===row.security.id||compact" class="lab-evidence"><p class="tiny" :class="row.data_status==='STALE'?'error-line':'muted'">{{row.data_note}} · 计算口径：未复权原价</p><div v-for="r in row.results" :key="r.id" class="lab-evidence-row"><span :class="r.status==='MISSING'?'muted':r.stance==='RISK'?'error-line':r.matched?'lab-positive':''">{{r.status==='MISSING'?'数据不足':r.matched?'条件满足':'条件未满足'}}</span><strong>{{r.name}}</strong><span>{{r.reason}}</span></div><div class="lab-evidence-actions"><button v-if="!compact" class="button small" @click="$emit('open',row.security.id)">查看 K 线</button><button class="button small" @click="$emit('monitor',row.security.id)">加入算法监测</button><button class="button small" @click="analyze(row,true)" :disabled="reviewing">Jev 决策分流</button><button class="button small" @click="analyze(row)" :disabled="reviewing">Agent 复核</button><span class="tiny muted">模型需配置 · 显式点击可能产生费用</span></div><p v-if="reviewing" class="tiny muted">{{reviewKind}} 分析中…</p><p class="error-line" v-if="error">{{error}}</p><div v-if="review" class="lab-review"><strong>{{reviewKind}} · {{review.status==='SUCCEEDED'?'已完成':review.status==='UNAVAILABLE'?'待配置':'分析未完成'}}</strong><p>{{review.summary}}</p></div></div>
    </article><p v-if="rows.length>ui.limit" class="muted tiny"><button class="button small" @click="ui.limit+=100">继续展示（已展示 {{ui.limit}} / {{rows.length}}）</button></p>
  </div>
  <div v-else class="lab-empty lab-no-candidates"><h3>{{ui.filter==='matched'?'这次没有股票满足当前组合条件。':ui.filter==='missing'?'本次计算没有数据不足的股票。':'本次股票池为空。'}}</h3><p v-if="ui.filter==='matched'">已完成 {{run.total}} 只股票的计算。{{run.combination==='all'?'“同时满足”要求每项算法通过；可减少算法、调整阈值，或改为“任一满足”。':'可以查看全部结果，核对未满足的条件。'}}</p><div class="flex"><button v-if="ui.filter!=='all'" class="button small" @click="filter('all')">查看全部结果与依据</button><button v-if="ui.filter==='matched'" class="text-button" @click="$emit('adjust')">调整筛选条件</button></div></div>
</template>
