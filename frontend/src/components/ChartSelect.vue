<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
const props = defineProps<{ modelValue:string; label:string; options:{value:string;label:string;description?:string}[]; disabled?:boolean }>();
const emit = defineEmits<{ 'update:modelValue':[value:string] }>();
const root=ref<HTMLElement>(), trigger=ref<HTMLButtonElement>();
const open=ref(false), index=ref(0);
function choose(value:string) { emit('update:modelValue',value); open.value=false; trigger.value?.focus(); }
function toggle() { index.value=Math.max(0,props.options.findIndex(x=>x.value===props.modelValue)); open.value=!open.value; }
function key(event:KeyboardEvent) {
  if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
    event.preventDefault();
    if (!open.value) { toggle(); return; }
    index.value=event.key==='Home' ? 0 : event.key==='End' ? props.options.length-1 : (index.value+(event.key==='ArrowDown'?1:-1)+props.options.length)%props.options.length;
  } else if (event.key==='Escape') { open.value=false; }
  else if (event.key==='Tab') open.value=false;
  else if (open.value && ['Enter',' '].includes(event.key)) { event.preventDefault(); choose(props.options[index.value]!.value); }
}
function outside(event:PointerEvent) { if (!root.value?.contains(event.target as Node)) open.value=false; }
onMounted(()=>document.addEventListener('pointerdown',outside));
onUnmounted(()=>document.removeEventListener('pointerdown',outside));
</script>
<template>
  <div ref="root" class="chart-select-menu" @keydown="key">
    <button ref="trigger" class="chart-select-trigger" :aria-label="label" aria-haspopup="listbox" :aria-expanded="open" :disabled="disabled" @click="toggle">
      {{ options.find(x=>x.value===modelValue)?.label }}<span aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" class="chart-select-options" role="listbox" :aria-label="label">
      <button v-for="(option,i) in options" :key="option.value" role="option" :aria-selected="modelValue===option.value" :class="{ highlighted:index===i }" @pointerenter="index=i" @click="choose(option.value)">
        <span class="option-check" aria-hidden="true">{{ modelValue===option.value ? '✓' : '' }}</span><span>{{ option.label }}<small v-if="option.description">{{ option.description }}</small></span>
      </button>
    </div>
  </div>
</template>
