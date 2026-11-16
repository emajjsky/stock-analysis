import {reactive,shallowReactive,computed,watch} from 'vue';
import {api,post} from './api';
import type {LabConfig,LabJob,LabRun,LabRunSummary,LabSelection,LabWorkspace} from './algorithmLab';

export const workspaceNames:Record<LabWorkspace,string>={screen:'选股工作台',stock:'个股分析',monitor:'持续监测'};
export type ResearchStock={id:string;name:string;code:string};
export interface LabDraft {
  mode:string;scope:string;combination:string;chosen:ResearchStock[];
  selectionsByMode:Record<string,LabSelection[]>;paramsOpen:boolean;resultId?:string;pendingId?:string;
  filter:'matched'|'all'|'missing';expanded:string;limit:number;
  taskName:string;interval:number;autoReview:boolean;useJev:boolean;editingId?:string;
  batchName:string;refreshInputs:boolean;
}
const storageKey='wangzha-lab-workspaces-v1';
export const clone=<T>(value:T):T=>JSON.parse(JSON.stringify(value));
function defaults(key:LabWorkspace):LabDraft {
  return {mode:'daily',scope:key==='screen'?'all':'custom',combination:'all',chosen:[],
    selectionsByMode:{daily:[{id:'ma-trend',parameters:{fast:5,slow:20}},{id:'atr-risk',parameters:{period:14,max_pct:5}}],intraday:[{id:'price-change',parameters:{threshold:3}}],news:[{id:'announcement',parameters:{}}]},
    paramsOpen:true,filter:key==='screen'?'matched':'all',expanded:'',limit:50,taskName:'我的算法监测',interval:60,autoReview:false,useJev:false,batchName:'',refreshInputs:true};
}
function restore(){
  const drafts={screen:defaults('screen'),stock:defaults('stock'),monitor:defaults('monitor')};
  let tab:LabWorkspace|'history'='screen';
  try {
    const saved=JSON.parse(localStorage.getItem(storageKey)||'null');
    for(const key of Object.keys(drafts) as LabWorkspace[]){
      const d=saved?.drafts?.[key];
      if(d&&['daily','intraday','news'].includes(d.mode)&&['all','any'].includes(d.combination)&&Array.isArray(d.chosen)&&d.selectionsByMode){
        drafts[key]={...drafts[key],...d,selectionsByMode:{...drafts[key].selectionsByMode,...d.selectionsByMode}};
      }
    }
    if(['screen','stock','monitor','history'].includes(saved?.tab))tab=saved.tab;
  }catch{/* 缓存不可用时仍可从服务端任务和运行记录恢复。 */}
  return {drafts,tab};
}
const initial=restore();
export const labWorkspace=reactive({...initial,jobs:[] as LabJob[],runs:[] as LabRunSummary[],submitting:undefined as LabWorkspace|undefined,loading:true,connectionError:'',errors:{screen:'',stock:'',monitor:''},revision:0});
export const labResults=shallowReactive<Record<LabWorkspace,LabRun|undefined>>({screen:undefined,stock:undefined,monitor:undefined});
// K线页按证券保留研究上下文，离开再返回也不会换成另一套默认算法。
interface StockStudy {selected:LabSelection[];run?:LabRun;busy:boolean;error:string;expanded:boolean}
const stockStudies=new Map<string,StockStudy>();
export function stockStudy(id:string):StockStudy {
  if(!stockStudies.has(id))stockStudies.set(id,reactive<StockStudy>({selected:[{id:'ma-trend',parameters:{fast:5,slow:20}},{id:'macd',parameters:{}}],busy:false,error:'',expanded:false}));
  return stockStudies.get(id)!;
}
export function carryStockStudy(run:LabRun,id:string){
  if(run.mode!=='daily')return;
  const row=run.rows.find(r=>r.security.id===id);if(!row)return;
  const study=stockStudy(id);study.selected=clone(run.selections);study.run={...run,rows:[row],total:1,matched:Number(row.matched),skipped:Number(row.missing>0)};study.error='';
}
export const activeLabJob=computed(()=>labWorkspace.jobs.find(j=>['QUEUED','RUNNING','CANCELLING'].includes(j.status)));
export function runWorkspace(run:LabRunSummary):LabWorkspace {return run.workspace??(run.scope==='custom'&&run.total===1?'stock':'screen');}
export function draftConfig(key:LabWorkspace):LabConfig {
  const d=labWorkspace.drafts[key];
  return {workspace:key,mode:d.mode,scope:key==='stock'?'custom':d.scope,security_ids:d.chosen.map(s=>s.id),selections:clone(d.selectionsByMode[d.mode]??[]),combination:d.combination,batch_name:d.batchName,refresh_inputs:d.refreshInputs};
}
export function sameConfig(run:LabRun,key:LabWorkspace){
  const config=draftConfig(key);
  return run.mode===config.mode&&run.scope===config.scope&&run.combination===config.combination&&
    JSON.stringify(run.selections)===JSON.stringify(config.selections)&&
    (config.scope!=='custom'||JSON.stringify([...(run.security_ids??run.rows.map(r=>r.security.id))].sort())===JSON.stringify([...config.security_ids].sort()));
}
watch(()=>({tab:labWorkspace.tab,drafts:labWorkspace.drafts}),value=>{
  try{localStorage.setItem(storageKey,JSON.stringify(value));}catch{/* 结果存于服务端，不把大结果写入localStorage。 */}
},{deep:true});

let timer:ReturnType<typeof setTimeout>|undefined,started=false,polling=false,generation=0;
const fetching=new Map<string,Promise<LabRun>>();
async function detail(id:string){
  if(!fetching.has(id))fetching.set(id,api<LabRun>('/lab/runs/'+encodeURIComponent(id)).then(r=>r.data).finally(()=>fetching.delete(id)));
  return fetching.get(id)!;
}
export async function restoreResult(key:LabWorkspace,id:string){
  const value=await detail(id);
  labResults[key]=value;labWorkspace.drafts[key].resultId=id;
  return value;
}
export async function refreshLabWorkspace(){
  if(polling)return;
  polling=true;
  try{
    const previous=new Map(labWorkspace.jobs.map(j=>[j.id,j.status]));
    const [jobs,runs]=await Promise.all([api<LabJob[]>('/lab/jobs'),api<LabRunSummary[]>('/lab/runs')]);
    labWorkspace.jobs=jobs.data;labWorkspace.runs=runs.data;labWorkspace.connectionError='';
    for(const key of ['screen','stock','monitor'] as LabWorkspace[]){
      const d=labWorkspace.drafts[key];
      const completed=jobs.data.find(j=>j.workspace===key&&j.status==='SUCCEEDED'&&
        (d.pendingId===j.id||(previous.has(j.id)&&previous.get(j.id)!=='SUCCEEDED')));
      const active=jobs.data.find(j=>j.workspace===key&&['QUEUED','RUNNING','CANCELLING'].includes(j.status));
      if(active)d.pendingId=active.id;
      const currentId=labWorkspace.drafts[key].resultId;
      const id=completed?.run_id??(runs.data.some(r=>r.id===currentId)?currentId:undefined)??runs.data.find(r=>runWorkspace(r)===key)?.id;
      if(id&&labResults[key]?.id!==id){await restoreResult(key,id);labWorkspace.revision++;}
      if(completed&&labResults[key]?.id===completed.run_id)d.pendingId=undefined;
    }
  }catch(e){labWorkspace.connectionError=String(e);}
  finally{labWorkspace.loading=false;polling=false;}
}
export function startLabWorkspace(){
  if(started)return;started=true;const currentGeneration=++generation;
  const poll=async()=>{await refreshLabWorkspace();if(started&&generation===currentGeneration)timer=setTimeout(poll,activeLabJob.value?800:5000);};
  void poll();
}
export function stopLabWorkspace(){started=false;++generation;clearTimeout(timer);}
export async function startCalculation(key:LabWorkspace){
  if(activeLabJob.value||labWorkspace.submitting)return;
  labWorkspace.submitting=key;labWorkspace.errors[key]='';
  try{
    const requestId=crypto.randomUUID();labWorkspace.drafts[key].pendingId=requestId;
    const response=await post<LabJob>('/lab/jobs',{...draftConfig(key),request_id:requestId});
    labWorkspace.jobs=[response.data,...labWorkspace.jobs.filter(j=>j.id!==response.data.id)];
    labWorkspace.drafts[key].paramsOpen=false;
    clearTimeout(timer);
    if(started){timer=setTimeout(async()=>{stopLabWorkspace();startLabWorkspace();},0);}
  }catch(e){labWorkspace.errors[key]=String(e);void refreshLabWorkspace();}
  finally{labWorkspace.submitting=undefined;}
}
export async function cancelCalculation(id:string){
  const response=await post<LabJob>('/lab/jobs/'+encodeURIComponent(id)+'/cancel');
  labWorkspace.jobs=labWorkspace.jobs.map(j=>j.id===id?response.data:j);
}
export async function openRun(id:string){
  const run=await detail(id);const key=runWorkspace(run),d=labWorkspace.drafts[key];
  // 历史结果恢复独立的场景，不经模式/标签watcher清空算法。
  d.mode=run.mode;d.scope=run.scope;d.combination=run.combination;d.selectionsByMode[run.mode]=clone(run.selections);
  d.chosen=run.scope==='custom'?run.rows.map(r=>({...r.security})):[];
  d.resultId=id;d.paramsOpen=false;d.filter=key==='screen'?'matched':'all';d.expanded='';d.limit=50;
  labResults[key]=run;labWorkspace.tab=key;labWorkspace.revision++;
  return run;
}
