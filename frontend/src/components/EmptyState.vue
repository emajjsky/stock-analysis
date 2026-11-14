<script setup lang="ts">
import { Telescope } from "lucide-vue-next";
defineProps<{ title: string; description: string }>();
</script>
<template>
  <div class="empty-state">
    <div class="empty-icon"><Telescope :size="28" /></div>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <slot />
  </div>
</template>
