<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  Activity,
  Clock3,
  History,
  Play,
  RefreshCw,
  Save,
  ShieldAlert,
} from "lucide-vue-next";
import { api, patch, post } from "../api";
import { action, inform } from "../state";
import type { Automation, AutomationRun } from "../types";
import { date, label } from "../format";

const emit = defineEmits<{ completed: [] }>();
const automation = ref<Automation>();
const runs = ref<AutomationRun[]>([]);
const enabled = ref(false);
const autoReview = ref(false);
const interval = ref(60);
const loading = ref(false);
const running = ref(false);
const error = ref("");
const dirty = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;
let controller: AbortController | undefined;
let completedRun: string | undefined;

const workerLabel = computed(() =>
  automation.value?.worker_running ? "服务端工作器在线" : "服务端工作器未运行",
);
const statusLabel: Record<string, string> = {
  IDLE: "空闲",
  RUNNING: "运行中",
  SUCCEEDED: "已完成",
  PARTIAL: "部分完成",
  FAILED: "失败",
  CANCELLED: "已取消",
  INTERRUPTED: "已中断",
  MANUAL: "手动",
  SCHEDULED: "定时",
};
function runLabel(value: string) {
  return statusLabel[value] ?? label(value);
}
function clearPolling() {
  if (timer) clearInterval(timer);
  timer = undefined;
}
function schedulePolling() {
  clearPolling();
  if (!automation.value?.enabled && !running.value && automation.value?.last_status !== "RUNNING") return;
  timer = setInterval(() => void load(false), 5000);
}
async function load(showError = true) {
  controller?.abort();
  controller = new AbortController();
  const current = controller;
  if (showError) loading.value = true;
  try {
    const [config, history] = await Promise.all([
      api<Automation>("/automation", { signal: current.signal }),
      api<AutomationRun[]>("/automation/runs", { signal: current.signal }),
    ]);
    if (current !== controller) return;
    automation.value = config.data;
    runs.value = history.data;
    error.value = "";
    const finished = history.data.find((item) => item.status !== "RUNNING");
    if (finished && finished.id !== completedRun) {
      if (completedRun !== undefined || !showError) emit("completed");
      completedRun = finished.id;
    }
    // 轮询期间只同步服务端状态；用户正在编辑的表单留在本地，避免误覆盖。
    if (!dirty.value) {
      enabled.value = config.data.enabled;
      autoReview.value = config.data.auto_review;
      interval.value = config.data.interval_seconds;
    }
    schedulePolling();
  } catch (e) {
    if (current.signal.aborted) return;
    error.value = e instanceof Error ? e.message : "自动监测状态读取失败";
  } finally {
    if (current === controller) loading.value = false;
  }
}
async function save() {
  if (!Number.isInteger(interval.value) || interval.value < 30 || interval.value > 3600) {
    inform("监测间隔必须在 30 到 3600 秒之间");
    return;
  }
  loading.value = true;
  const result = await action(
    () =>
      patch<Automation>("/automation", {
        enabled: enabled.value,
        interval_seconds: interval.value,
        auto_review: autoReview.value,
      }),
    enabled.value ? "自动监测已启用" : "自动监测已关闭",
  );
  if (result) {
    dirty.value = false;
    automation.value = result.data;
    enabled.value = result.data.enabled;
    interval.value = result.data.interval_seconds;
    autoReview.value = result.data.auto_review;
    schedulePolling();
  }
  loading.value = false;
}
async function runOnce() {
  if (running.value) return;
  running.value = true;
  error.value = "";
  try {
    const result = await post<AutomationRun>("/automation/run", {});
    inform(`单次监测：${runLabel(result.data.status)}，请查看运行记录和信号`);
    runs.value = [
      result.data,
      ...runs.value.filter((item) => item.id !== result.data.id),
    ].slice(0, 30);
    await load(false);
    emit("completed");
  } catch (e) {
    const message = e instanceof Error ? e.message : "单次自动监测失败";
    await load(false);
    error.value = message;
    inform(message);
  }
  running.value = false;
  schedulePolling();
}
onMounted(() => void load());
onUnmounted(() => {
  clearPolling();
  controller?.abort();
});
</script>

<template>
  <section class="automation-panel panel" aria-labelledby="automation-title">
    <header class="automation-header">
      <div>
        <div class="eyebrow">AUTOMATION / MONITOR</div>
        <h2 id="automation-title">自动监测</h2>
        <p>只计算已保存的日线，不自动拉取实时行情，也不连接交易。</p>
      </div>
      <span class="badge" :class="{ blue: automation?.worker_running }">
        <Activity :size="12" />{{ workerLabel }}
      </span>
    </header>
    <div v-if="error" class="automation-error">
      <ShieldAlert :size="16" /><span>{{ error }}</span
      ><button class="text-button tiny" @click="load()">重试</button>
    </div>
    <div class="automation-controls">
      <label class="automation-toggle">
        <input
          v-model="enabled"
          type="checkbox"
          :disabled="loading || !automation"
          @change="dirty = true"
        />
        <span
          ><strong>{{ dirty ? (enabled ? "将启用自动监测 · 待保存" : "将关闭自动监测 · 待保存") : (enabled ? "自动监测已启用" : "自动监测已关闭") }}</strong
          ><small>默认关闭 · 后端服务运行期间有效</small></span
        >
      </label>
      <label class="field automation-interval"
        >检查间隔（秒）<input
          v-model.number="interval"
          type="number"
          min="30"
          max="3600"
          step="1"
          :disabled="loading"
          @input="dirty = true"
      /></label>
      <label class="automation-toggle compact">
        <input
          v-model="autoReview"
          type="checkbox"
          :disabled="loading"
          @change="dirty = true"
        />
        <span
          ><strong>自动请求 Agent 复核</strong
          ><small>仅模型已配置时调用，可能产生模型费用</small></span
        >
      </label>
      <div class="automation-actions">
        <button class="button" :disabled="loading || !automation" @click="save">
          <Save :size="14" />保存设置
        </button>
        <button
          class="button primary"
          :disabled="running || loading"
          @click="runOnce"
        >
          <Play :size="14" />{{ running ? "运行中…" : "立即运行一次" }}
        </button>
      </div>
    </div>
    <div class="automation-status-grid">
      <div>
        <small>活动监测规则</small
        ><strong>{{ automation?.active_monitor_count ?? "—" }}</strong>
      </div>
      <div>
        <small>下一次检查</small
        ><strong>{{ date(automation?.next_run_at) }}</strong>
      </div>
      <div>
        <small>上次状态</small
        ><strong>{{ runLabel(automation?.last_status ?? "IDLE") }}</strong>
      </div>
      <div>
        <small>上次运行</small
        ><strong>{{ date(automation?.last_run_at) }}</strong>
      </div>
    </div>
    <p v-if="automation?.last_error" class="automation-last-error">
      <ShieldAlert :size="14" />{{ automation.last_error }}
    </p>
    <div
      v-if="automation?.limitations?.length"
      class="subtle automation-limitations"
    >
      <strong>当前边界</strong>
      <ul>
        <li v-for="item in automation.limitations" :key="item">{{ item }}</li>
      </ul>
    </div>
    <details class="automation-history">
      <summary>
        <History :size="14" />最近运行记录（最多 30 条）<RefreshCw
          :size="13"
          class="history-refresh"
          @click.prevent="load()"
        />
      </summary>
      <div v-if="!runs.length" class="automation-empty">
        <Clock3 :size="18" />尚无自动监测运行记录
      </div>
      <div v-for="item in runs" :key="item.id" class="automation-run">
        <div class="flex spread">
          <strong>{{ runLabel(item.status) }}</strong
          ><span class="badge">{{ runLabel(item.trigger) }}</span>
        </div>
        <div class="tiny muted">
          {{ date(item.started_at)
          }}<span v-if="item.finished_at"> → {{ date(item.finished_at) }}</span>
        </div>
        <div class="automation-run-counts">
          <span>生成 {{ item.generated }}</span
          ><span>复核 {{ item.reviewed }}</span
          ><span>跳过 {{ item.skipped }}</span>
        </div>
        <p v-if="item.error" class="tiny up">{{ item.error }}</p>
        <ul v-if="item.details.length" class="tiny muted">
          <li v-for="detail in item.details" :key="detail">{{ detail }}</li>
        </ul>
      </div>
    </details>
  </section>
</template>
