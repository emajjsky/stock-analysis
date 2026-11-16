<script setup lang="ts">
import {ref,computed,onMounted,watch} from 'vue';
import {api,post} from '../api';
import {action,inform} from '../state';
import {stockStudy,activeLabJob} from '../labWorkspace';
import AlgorithmPicker from './AlgorithmPicker.vue';
import AlgorithmResults from './AlgorithmResults.vue';
import StockDiagnosis from './StockDiagnosis.vue';
import type {LabAlgorithm,LabRun} from '../algorithmLab';
const props=defineProps<{securityId:string}>();
const emit=defineEmits<{markers:[{time:string;text:string;direction:string}[]]}>();
const catalog=ref<LabAlgorithm[]>([]),study=computed(()=>stockStudy(props.securityId));
const dirty=computed(()=>study.value.run&&JSON.stringify(study.value.selected)!==JSON.stringify(study.value.run.selections));
const markers=computed(()=>!dirty.value?study.value.run?.rows.flatMap(r=>r.results.flatMap(a=>a.markers))??[]:[]);
watch(markers,value=>emit('markers',value),{immediate:true});
async function calculate(){
  const current=study.value,id=props.securityId;if(current.busy||activeLabJob.value)return;
  current.busy=true;current.error='';
  try{current.run=(await post<LabRun>('/lab/run',{scope:'custom',security_ids:[id],mode:'daily',combination:'all',selections:current.selected,workspace:'stock'})).data;}
  catch(e){current.error=String(e);}finally{current.busy=false;}
}
async function monitor(){
  const source=study.value.run;
  const result=await action(()=>post('/lab/tasks',{name:'个股日线观察',scope:'custom',security_ids:[props.securityId],mode:'daily',combination:source?.combination??'all',selections:source?.selections??study.value.selected,interval_seconds:60,enabled:true,auto_review:false}));
  if(result)inform('已加入后台监测；发现页可暂停或调整。');
}
onMounted(async()=>{try{catalog.value=(await api<LabAlgorithm[]>('/lab/catalog')).data;}catch(e){study.value.error=String(e);}});
</script>
<template><section class="panel stock-algorithms"><div class="lab-section-title"><div><h2>算法分析</h2><span class="tiny muted">从发现页进入时沿用本次日线计算条件，命中日期会标记在 K 线上。</span></div><button class="button small" @click="study.expanded=!study.expanded">{{study.expanded?'收起算法':'选择算法'}}</button><button class="button primary small" :disabled="study.busy||!!activeLabJob||!study.selected.length" @click="calculate">{{study.busy?'计算中…':'重新计算'}}</button></div><fieldset class="lab-fields" :disabled="study.busy"><AlgorithmPicker v-if="study.expanded" :catalog="catalog" v-model="study.selected" mode="daily"/></fieldset><p class="tiny muted">{{study.selected.map(s=>catalog.find(a=>a.id===s.id)?.name??s.id).join(' / ')}} · {{dirty?'算法已调整，下方保留上次结果，重新计算后更新。':study.busy?'计算中，离开页面后仍保留结果。':'按需计算，不自动调用模型。'}}</p><p v-if="activeLabJob" class="tiny muted">选股任务正在后台运行，请完成后再重算个股。</p><p v-if="study.error" class="error-line">{{study.error}}</p><StockDiagnosis v-if="study.run?.rows[0]?.diagnosis" :run="study.run" hide-open/><AlgorithmResults v-if="study.run" :run="study.run" compact @monitor="monitor" @open="()=>{}"/></section></template>
