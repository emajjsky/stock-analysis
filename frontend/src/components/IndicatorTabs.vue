<script setup lang="ts">
defineProps<{ modelValue:string; label:string; options:{value:string;label:string;description?:string}[] }>();
defineEmits<{ 'update:modelValue':[value:string] }>();
</script>
<template>
  <div class="indicator-tabs" role="group" :aria-label="label">
    <button v-for="option in options" :key="option.value" type="button" :aria-pressed="modelValue===option.value" :class="{active:modelValue===option.value}" :title="option.description" @click="$emit('update:modelValue',option.value)">{{ option.label }}</button>
  </div>
</template>
