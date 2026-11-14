<script setup lang="ts">
import { computed, ref } from "vue";
import { Play, ArrowUpRight, RefreshCw } from "lucide-vue-next";
import { state, action, refresh } from "../state";
import { post } from "../api";
import { date, label, money } from "../format";
import type { Review, Signal } from "../types";
import ReviewCard from "../components/ReviewCard.vue";
import EmptyState from "../components/EmptyState.vue";
defineEmits<{ open: [id: string]; rules: [] }>();
const filter = ref("全部"),
  selectedId = ref(""),
  busy = ref(false);
const list = computed(() =>
  state.signals.filter(
    (s) => filter.value === "全部" || s.kind === filter.value,
  ),
);
const selected = computed(
  () => state.signals.find((s) => s.id === selectedId.value) ?? list.value[0],
);
async function run() {
  busy.value = true;
  const r = await action(() =>
    post<{ generated: number; signals: Signal[] }>("/signals/run"),
  );
  if (r) {
    await refresh();
    selectedId.value = r.data.signals[0]?.id ?? "";
  }
  busy.value = false;
}
async function review(demo = false) {
  if (!selected.value) return;
  const r = await action(() =>
    post<Review>("/reviews", { signal_id: selected.value.id, demo }),
  );
  if (r) await refresh();
}
</script>
<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">SIGNALS / 06 · AGENT / 08</div>
      <h1>信号中心</h1>
      <p>保留确认、复核和失效记录，理解每一次提示。</p>
    </div>
    <div class="flex">
      <button class="button" @click="$emit('rules')">配置规则</button
      ><button
        class="button primary"
        @click="run"
        :disabled="busy || !state.securities.length"
      >
        <Play :size="15" />{{ busy ? "计算中…" : "运行信号计算" }}
      </button>
    </div>
  </section>
  <div class="tabs bottom-gap">
    <button
      v-for="v in ['全部', 'BUY', 'SELL', 'WATCH', 'T_BUY', 'T_SELL']"
      :class="{ active: filter === v }"
      @click="filter = v"
    >
      {{ label(v) }}
    </button>
  </div>
  <div class="signal-center">
    <section class="panel">
      <div class="section-label inset">
        <h2>
          已保存信号 <span>{{ list.length }}</span>
        </h2>
        <span class="tiny muted">收盘确认 · 非实时盘中</span>
      </div>
      <button
        v-for="s in list"
        :key="s.id"
        class="signal-row"
        :class="{ selected: s.id === selected?.id }"
        @click="selectedId = s.id"
      >
        <div class="flex spread">
          <strong
            >{{ s.security.name }} <small>{{ s.security.code }}</small></strong
          ><span class="badge blue">{{ label(s.kind) }}</span>
        </div>
        <p>{{ s.reasons[0] }}</p>
        <div class="flex spread tiny muted">
          <span>{{ date(s.confirmed_at) }}</span
          ><span
            >{{ label(s.status) }} ·
            {{ s.review ? label(s.review.verdict) : "尚未复核" }}</span
          >
        </div></button
      ><EmptyState
        v-if="!list.length"
        title="没有符合条件的信号"
        description="保存监测规则后运行计算。未满足条件时不会强行生成买卖建议。"
      />
    </section>
    <section v-if="selected" class="panel inset">
      <div class="flex spread">
        <div>
          <div class="eyebrow">信号详情</div>
          <h2>{{ selected.security.name }} · {{ label(selected.kind) }}</h2>
        </div>
        <button
          class="icon-button"
          title="查看个股图表"
          @click="$emit('open', selected.security.id)"
        >
          <ArrowUpRight />
        </button>
      </div>
      <div class="signal-times">
        <div>
          <small>确认时刻</small
          ><strong>{{ date(selected.confirmed_at) }}</strong>
        </div>
        <div>
          <small>失效时刻</small
          ><strong>{{ date(selected.valid_until) }}</strong>
        </div>
        <div>
          <small>参考保存价</small><strong>{{ money(selected.price) }}</strong>
        </div>
      </div>
      <h3>触发条件</h3>
      <div v-for="c in selected.conditions" class="condition">
        <span
          >{{ c.passed === null ? "未知" : c.passed ? "✓ 满足" : "× 未满足" }} ·
          {{ c.label }}</span
        ><strong>{{ c.value }} {{ c.operator }} {{ c.threshold }}</strong>
      </div>
      <p class="tiny muted">
        算法 {{ selected.algorithm_id }} · {{ selected.id }}
      </p>
      <div class="divider top-gap">
        <div class="flex spread">
          <h3>Agent 决策复核</h3>
          <button class="button small" @click="review()">
            <RefreshCw :size="13" />请求复核
          </button>
        </div>
        <ReviewCard :review="selected.review" /><button
          class="text-button tiny top-gap"
          @click="review(true)"
        >
          显式体验规则复核演示（非 AI）
        </button>
      </div>
      <div class="subtle top-gap">
        这是算法观察记录。未绑定账户，不含持仓适配和下单许可；过期信号不能按旧价执行。
      </div>
      <section
        v-if="selected.decision"
        class="subtle top-gap"
        aria-label="复核过滤决策门"
      >
        <div class="flex spread wrap">
          <h3>复核过滤决策门</h3>
          <span class="badge blue">{{
            label(selected.decision.agent_mode)
          }}</span>
        </div>
        <p>
          <strong>{{ selected.decision.label }}</strong>
        </p>
        <p class="tiny">
          过滤结果：{{
            selected.decision.gate_passed === null
              ? "未参与过滤"
              : selected.decision.gate_passed
                ? "通过过滤"
                : "未通过过滤"
          }}
        </p>
        <ul class="tiny">
          <li v-for="reason in selected.decision.reasons" :key="reason">
            {{ reason }}
          </li>
        </ul>
        <div
          v-for="check in selected.decision.checks"
          :key="check.id"
          class="condition"
        >
          <span
            >{{
              check.passed === null
                ? "？ 未知"
                : check.passed
                  ? "✓ 通过"
                  : "× 未通过"
            }}
            · {{ check.label }}</span
          >
          <span>{{ check.detail }}</span>
        </div>
        <p class="tiny">
          <strong>{{ selected.decision.execution_label }}</strong>
        </p>
        <p class="tiny muted">
          过滤结果与算法得分、Agent 立场分开记录，不产生账户执行许可。评估
          {{ date(selected.decision.evaluated_at) }}
        </p>
      </section>
    </section>
  </div>
</template>
