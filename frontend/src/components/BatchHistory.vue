<script setup lang="ts">
import {computed,ref} from 'vue';
import {api,patch} from '../api';
import {date} from '../format';
import {labWorkspace as ws,workspaceNames,runWorkspace,refreshLabWorkspace} from '../labWorkspace';
import type {LabRun,LabRunSummary} from '../algorithmLab';
defineEmits<{open:[string]}>();
const day=ref(''),mode=ref(''),search=ref(''),limit=ref(30),selected=ref<string[]>([]),error=ref(''),busy=ref(false),compare=ref<{added:string[];removed:string[];kept:string[];same:boolean;older:string;newer:string}>();
const naming=ref(''),name=ref('');
const dayOf=(r:LabRunSummary)=>r.batch_date??new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(r.started_at));
const modeName=(m:string)=>({daily:'收盘日线',intraday:'盘中快照',news:'公告线索'}[m]??m);
const filtered=computed(()=>ws.runs.filter(r=>(!day.value||dayOf(r)===day.value)&&(!mode.value||r.mode===mode.value)&&(!search.value||(r.batch_name+' '+r.selections.map(s=>s.id).join(' ')).includes(search.value))));
const groups=computed(()=>{const result:Record<string,LabRunSummary[]>={};for(const r of filtered.value.slice(0,limit.value))(result[dayOf(r)]??=[]).push(r);return Object.entries(result);});
function choose(id:string){selected.value=selected.value.includes(id)?selected.value.filter(x=>x!==id):[...selected.value.slice(-1),id];compare.value=undefined;}
async function compareRuns(){busy.value=true;error.value='';try{
  const runs=await Promise.all(selected.value.map(id=>api<LabRun>('/lab/runs/'+id).then(r=>r.data)));runs.sort((a,b)=>a.started_at.localeCompare(b.started_at));
  const [a,b]=runs;if(!a||!b)return;const left=new Map(a.rows.filter(r=>r.matched).map(r=>[r.security.id,r.security.name+' '+r.security.code])),right=new Map(b.rows.filter(r=>r.matched).map(r=>[r.security.id,r.security.name+' '+r.security.code]));
  compare.value={added:[...right].filter(([id])=>!left.has(id)).map(([,n])=>n),removed:[...left].filter(([id])=>!right.has(id)).map(([,n])=>n),kept:[...right].filter(([id])=>left.has(id)).map(([,n])=>n),same:!!a.config_hash&&a.config_hash===b.config_hash,older:date(a.started_at),newer:date(b.started_at)};
}catch(e){error.value=String(e);}finally{busy.value=false;}}
async function rename(id:string){try{await patch('/lab/runs/'+id,{batch_name:name.value});await refreshLabWorkspace();naming.value='';}catch(e){error.value=String(e);}}
async function download(id:string){try{const run=(await api<LabRun>('/lab/runs/'+id)).data;const url=URL.createObjectURL(new Blob([JSON.stringify(run,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=(run.batch_name||'选股批次')+'-'+id+'.json';link.click();URL.revokeObjectURL(url);}catch(e){error.value=String(e);}}
</script>
<template><section class="lab-history">
  <div class="lab-section-title"><div><h2>筛选与诊断批次</h2><p class="tiny muted">按日期归档，共 {{ws.runs.length}} 批。保存当时条件、数据时点和结果，不再自动淘汰；旧版已删除的批次无法恢复。</p></div></div>
  <div class="batch-filters"><label>日期<input type="date" v-model="day"></label><label>任务类型<select v-model="mode"><option value="">全部</option><option value="daily">收盘日线</option><option value="intraday">盘中快照</option><option value="news">公告线索</option></select></label><label>搜索名称 / 算法<input v-model="search" placeholder="批次名称或算法ID"></label><button class="button small" :disabled="selected.length!==2||busy" @click="compareRuns">{{busy?'比较中…':'比较已选两批'}}</button></div>
  <p class="error-line" v-if="error">{{error}}</p>
  <section v-if="compare" class="panel batch-comparison"><strong>{{compare.older}} → {{compare.newer}} · 候选变化</strong><p v-if="!compare.same" class="error-line">算法、参数或股票范围不同，以下仅比较名单，不代表信号变强或变弱。</p><div class="batch-columns"><div v-for="(title,key) in {added:'新增入选',removed:'退出候选',kept:'连续入选'}" :key="key"><h3>{{title}} {{compare[key].length}}</h3><p>{{compare[key].slice(0,100).join('、')||'无'}}</p><small v-if="compare[key].length>100">前100只，完整名单请分别查看或导出批次。</small></div></div></section>
  <div v-if="!filtered.length" class="lab-empty">没有符合条件的批次。完成一次筛查后会自动归档。</div>
  <section v-for="[day,records] in groups" :key="day" class="batch-day"><h3>{{day}} <span class="tiny muted">{{records.length}} 批</span></h3><article v-for="r in records" :key="r.id" class="lab-task"><input type="checkbox" :aria-label="'比较批次 '+r.id" :checked="selected.includes(r.id)" @change="choose(r.id)"><div class="batch-record"><strong>{{r.batch_name||workspaceNames[runWorkspace(r)]+' · '+modeName(r.mode)}}</strong><p class="tiny">{{date(r.started_at)}} · {{r.session||'旧批次未记录阶段'}} · {{r.combination==='all'?'同时满足':'任一满足'}} {{r.selections.length}}项 · 候选 {{r.matched}} / {{r.total}}</p><p class="tiny muted">数据不足 {{r.skipped}} · 过期 {{r.stale??'未记录'}} · 来源范围 {{r.source_from??'旧版未记录'}} ～ {{r.source_to??'旧版未记录'}} · 批号 {{r.id.slice(0,8)}}</p><div v-if="naming===r.id" class="flex"><input aria-label="批次新名称" v-model="name" maxlength="60"><button class="button small" @click="rename(r.id)">保存名称</button><button class="text-button" @click="naming=''">取消</button></div></div><button class="button small" @click="$emit('open',r.id)">查看结果</button><button class="text-button" @click="naming=r.id;name=r.batch_name||''">命名</button><button class="text-button" @click="download(r.id)">导出</button></article></section>
  <button class="button small" v-if="filtered.length>limit" @click="limit+=30">更多批次（{{limit}} / {{filtered.length}}）</button>
  <h3>未完成任务</h3><p class="tiny muted">{{ws.jobs.filter(j=>j.status!=='SUCCEEDED').map(j=>date(j.started_at)+' · '+({RUNNING:'运行中',QUEUED:'等待',CANCELLING:'取消中',FAILED:'失败',CANCELLED:'已取消',INTERRUPTED:'已中断'}[j.status]??j.status)+(j.error?'：'+j.error:'')).join('；')||'无未完成任务'}}</p>
</section></template>
