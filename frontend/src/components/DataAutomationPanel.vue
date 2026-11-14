<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { RefreshCw, Database } from "lucide-vue-next";
import { api, post, patch } from "../api";
import { date } from "../format";
import type { CatalogStatus, RefreshStatus } from "../terminal";
const catalog = ref<CatalogStatus>(),
  status = ref<RefreshStatus>(),
  enabled = ref(true),
  interval = ref(60),
  dirty = ref(false),
  busy = ref(false),
  error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined,
  stopped = false;
const ctrl = new AbortController();
async function load() {
  const [c, s] = await Promise.allSettled([
    api<CatalogStatus>("/data/catalog", { signal: ctrl.signal }),
    api<RefreshStatus>("/data/refresh", { signal: ctrl.signal }),
  ]);
  if (stopped) return;
  if (c.status === "fulfilled") catalog.value = c.value.data;
  if (s.status === "fulfilled") {
    status.value = s.value.data;
    if (!dirty.value) {
      enabled.value = s.value.data.enabled;
      interval.value = s.value.data.interval_seconds;
    }
  }
  if (c.status === "rejected" || s.status === "rejected")
    error.value = "自动更新状态读取失败";
  else error.value = "";
}
async function poll() {
  await load();
  if (!stopped) timer = setTimeout(poll, 5000);
}
async function sync() {
  if (busy.value) return;
  busy.value = true;
  try {
    const r = await post<CatalogStatus>("/data/catalog/sync");
    catalog.value = r.data;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "更新失败";
  } finally {
    busy.value = false;
  }
}
async function save() {
  if (
    busy.value ||
    !Number.isInteger(interval.value) ||
    interval.value < 30 ||
    interval.value > 3600
  )
    return;
  busy.value = true;
  try {
    const r = await patch<RefreshStatus>("/data/refresh", {
      enabled: enabled.value,
      interval_seconds: interval.value,
    });
    status.value = r.data;
    dirty.value = false;
    error.value = "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "保存失败";
  } finally {
    busy.value = false;
  }
}
onMounted(poll);
onUnmounted(() => {
  stopped = true;
  clearTimeout(timer);
  ctrl.abort();
});
</script>
<template>
  <section class="panel inset bottom-gap data-automation">
    <div class="flex spread wrap">
      <div class="flex">
        <Database :size="18" />
        <h2>基础库与自动更新</h2>
      </div>
      <span
        class="badge"
        :class="{ blue: status?.enabled }"
        :title="status?.phase"
        >{{
          !status
            ? "读取中"
            : status.running
              ? "更新中"
              : status?.error
                ? "更新异常"
                : status?.enabled
                  ? "自动更新已开启"
                  : "自动更新已暂停"
        }}</span
      >
    </div>
    <div class="data-settings-grid">
      <div>
        <span class="tiny muted">沪深 A 股证券目录</span>
        <div class="flex wrap">
          <strong class="catalog-count"
            >{{ catalog?.count.toLocaleString() ?? "—"
            }}<small> 只</small></strong
          ><span v-if="catalog?.status === 'RUNNING'" class="badge"
            >下载中</span
          >
        </div>
        <span class="tiny muted"
          >{{ catalog?.source ?? "来源待加载" }} ·
          {{ date(catalog?.updated_at) }}</span
        >
      </div>
      <div class="refresh-controls">
        <label class="check-row"
          ><input
            type="checkbox"
            v-model="enabled"
            @change="dirty = true"
          />自动更新行情</label
        ><label class="tiny"
          >盘中间隔
          <input
            v-model.number="interval"
            type="number"
            min="30"
            max="3600"
            step="1"
            aria-label="行情自动更新间隔秒数"
            @input="dirty = true"
          />
          秒</label
        ><button
          class="button small primary"
          :disabled="
            busy ||
            !dirty ||
            !Number.isInteger(interval) ||
            interval < 30 ||
            interval > 3600
          "
          @click="save"
        >
          保存
        </button>
      </div>
      <button
        class="button small"
        :disabled="busy || catalog?.status === 'RUNNING'"
        @click="sync"
      >
        <RefreshCw :size="13" />{{
          catalog?.status === "RUNNING" ? "更新中…" : "更新基础库"
        }}
      </button>
    </div>
    <p
      v-if="error || catalog?.error || status?.error"
      class="error-line"
      role="alert"
    >
      {{ error || catalog?.error || status?.error }}
    </p>
    <details class="terminal-details">
      <summary>运行详情</summary>
      <p class="tiny muted">
        最近成功 {{ date(status?.last_success_at) }} ·
        服务运行期间刷新，断网保留缓存。非交易时段降低频率。
      </p>
    </details>
  </section>
</template>
