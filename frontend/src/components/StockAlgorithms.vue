<script setup lang="ts">
import {ref,onMounted,watch} from 'vue';
import {api,post} from '../api';
import {action,inform} from '../state';
import AlgorithmPicker from './AlgorithmPicker.vue';
import AlgorithmResults from './AlgorithmResults.vue';
import type {LabAlgorithm,LabSelection,LabRun} from '../algorithmLab';
const props=defineProps<{securityId:string}>();
const emit=defineEmits<{markers:[{time:string;text:string;direction:string}[]]}>();
const catalog=ref<LabAlgorithm[]>([]),selected=ref<LabSelection[]>([{id:'ma-trend',parameters:{fast:5,slow:20}},{id:'macd',parameters:{}}]),run=ref<LabRun>(),busy=ref(false),error=ref(''),expanded=ref(false);
let version=0;
async function calculate(){const v=++version;busy.value=true;error.value='';try{const result=await post<LabRun>('/lab/run',{scope:'custom',security_ids:[props.securityId],mode:'daily',combination:'all',selections:selected.value});if(v!==version)return;run.value=result.data;emit('markers',result.data.rows.flatMap(r=>r.results.flatMap(a=>a.markers)));}catch(e){if(v===version)error.value=String(e);}finally{if(v===version)busy.value=false;}}
async function monitor(){const r=await action(()=>post('/lab/tasks',{name:'个股日线观察',scope:'custom',security_ids:[props.securityId],mode:'daily',combination:'all',selections:selected.value,interval_seconds:60,enabled:true,auto_review:false}));if(r)inform('已加入后台监测；发现页可暂停或调整。');}
watch(()=>props.securityId,()=>{++version;busy.value=false;run.value=undefined;error.value='';emit('markers',[]);});
watch(selected,()=>{run.value=undefined;emit('markers',[]);},{deep:true});
onMounted(async()=>{try{catalog.value=(await api<LabAlgorithm[]>('/lab/catalog')).data;}catch(e){error.value=String(e);}});
</script>
<template><section class="panel stock-algorithms"><div class="lab-section-title"><div><h2>算法分析</h2><span class="tiny muted">选择算法计算当前个股，命中条件会标记在日 K 图上。</span></div><button class="button small" @click="expanded=!expanded">{{expanded?'收起算法':'选择算法'}}</button><button class="button primary small" :disabled="busy||!selected.length" @click="calculate">{{busy?'计算中…':'计算建议'}}</button></div><AlgorithmPicker v-if="expanded" :catalog="catalog" v-model="selected" mode="daily"/><p v-if="error" class="error-line">{{error}}</p><AlgorithmResults v-if="run" :run="run" compact @monitor="monitor" @open="()=>{}"/><p v-else class="tiny muted">{{selected.map(s=>catalog.find(a=>a.id===s.id)?.name??s.id).join(' / ')}} · 按需计算，不自动调用模型。</p></section></template>
