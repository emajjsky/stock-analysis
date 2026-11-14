<script setup lang="ts">
import { ref, onMounted } from "vue";
import { FlaskConical, Play } from "lucide-vue-next";
import { api, post } from "../api";
import { action } from "../state";
import type { Evaluation } from "../types";
import EmptyState from "../components/EmptyState.vue";
const rows = ref<Evaluation[]>([]),
  busy = ref(false),
  err = ref("");
async function load() {
  try {
    rows.value = (await api<Evaluation[]>("/evaluations")).data;
  } catch (e) {
    err.value = String(e);
  }
}
onMounted(load);
async function run() {
  busy.value = true;
  const r = await action(() => post<Evaluation>("/evaluations/run"));
  if (r) await load();
  busy.value = false;
}
</script>
<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">VALIDATION / 09</div>
      <h1>验证每一种判断</h1>
      <p>看见结果，也保留未采用的机会和失败样本。</p>
    </div>
    <button class="button primary" @click="run" :disabled="busy">
      <Play :size="15" />{{ busy ? "评估中…" : "运行后验验证" }}
    </button>
  </section>
  <div class="validation-trio">
    <article>
      <span class="index">A</span>
      <h3>算法信号</h3>
      <p>相同确认时刻与持有期限，检验原始信号。</p>
    </article>
    <article>
      <span class="index">B</span>
      <h3>固定规则过滤</h3>
      <p>同源样本，比较固定过滤的覆盖和代价。</p>
    </article>
    <article>
      <span class="index">C</span>
      <h3>Agent 过滤</h3>
      <p>包括拒绝机会与复核延迟，未配置模型不伪造增益。</p>
    </article>
  </div>
  <div class="subtle bottom-gap">
    当前交付成熟信号的后验统计。资金策略回测、校准曲线、影子交易对照、训练和模型晋级尚未开放，不能用合成数据证明算法有效。
  </div>
  <p class="error-box" v-if="err">
    {{ err }} <button @click="load">重试</button>
  </p>
  <div v-for="e in rows" class="panel inset bottom-gap">
    <div class="flex spread">
      <h2>{{ e.name }}</h2>
      <span class="badge">{{ e.status }}</span>
    </div>
    <p class="tiny muted">样本 {{ e.sample_size }} · 类型 {{ e.type }}</p>
    <div class="metric-grid">
      <div v-for="m in e.metrics">
        <small>{{ m.label }}</small
        ><strong>{{ m.value }}</strong>
        <p>{{ m.description }}</p>
      </div>
    </div>
    <p v-for="l in e.limitations" class="tiny muted">{{ l }}</p>
  </div>
  <EmptyState
    v-if="!rows.length"
    title="还没有成熟的验证样本"
    description="需要信号确认之后的真实后续行情。样本不足时保留待验证，不虚构胜率或收益。"
  />
</template>
