<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from "vue";
import {
  Upload,
  RefreshCw,
  Check,
  Download,
  CloudDownload,
} from "lucide-vue-next";
import { state, action, refresh, seed, inform } from "../state";
import { api, post } from "../api";
import type {
  Provider,
  ImportPreview,
  ProviderSyncResult,
  ProviderSyncRun,
} from "../types";
import { label, date } from "../format";
import {
  modeDescription,
  presentProvider,
  parseSecurityCodes,
} from "../dataSources";
import DataAutomationPanel from "../components/DataAutomationPanel.vue";
import AutomationPanel from "../components/AutomationPanel.vue";
import { supportsTencent } from "../research";
const tab = ref("数据管理"),
  providers = ref<Provider[]>([]),
  providersLoaded = ref(false),
  imports = ref<ImportPreview[]>([]),
  preview = ref<ImportPreview>(),
  partial = ref(false),
  busy = ref(false),
  file = ref<File>(),
  committed = ref(false);
const syncScope = ref<"codes" | "watchlist" | "selected">("codes"),
  codeInput = ref(""),
  selectedSecurityIds = ref<string[]>([]),
  syncDaily = ref(false),
  syncBusy = ref(false),
  syncError = ref(""),
  syncResult = ref<ProviderSyncResult>(),
  syncRuns = ref<ProviderSyncRun[]>([]);
const syncCandidates = computed(() =>
  state.securities.filter((s) => s.id.startsWith("LIVE.")),
);
const realWatchIds = computed(() =>
  state.watchlists
    .filter((w) => w.security_id.startsWith("LIVE."))
    .map((w) => w.security_id),
);
const parsedCodes = computed(() => parseSecurityCodes(codeInput.value));
const syncLimit = computed(() => (syncDaily.value ? 5 : 50));
const syncIds = computed(() => [
  ...new Set(
    syncScope.value === "codes"
      ? parsedCodes.value.ids
      : syncScope.value === "watchlist"
        ? realWatchIds.value
        : selectedSecurityIds.value,
  ),
]);
const syncBlockReason = computed(() => {
  if (!supportsTencent(providers.value))
    return "当前数据源尚不可用，请先点击“刷新诊断”检查。";
  if (syncBusy.value) return "正在同步，请等待本次请求完成。";
  if (syncScope.value === "codes" && parsedCodes.value.errors.length)
    return "股票代码有误，请按输入框下方的提示修正。";
  if (!syncIds.value.length) {
    if (syncScope.value === "watchlist")
      return "真实来源自选股为 0 只，请先改为输入股票代码。";
    if (syncScope.value === "selected")
      return syncCandidates.value.length
        ? "请至少勾选一只证券。"
        : "还没有已同步的真实证券，请先改为输入股票代码。";
    return "请先输入至少一个六位沪深 A 股代码。";
  }
  if (syncIds.value.length > syncLimit.value)
    return `当前每次最多同步 ${syncLimit.value} 只，请减少证券数量。`;
  return "";
});
async function enterStockCodes() {
  syncScope.value = "codes";
  await nextTick();
  document.getElementById("sync-security-codes")?.focus();
}
async function load() {
  const p = await action(() => api<Provider[]>("/data/providers"));
  if (p) {
    providers.value = p.data;
    providersLoaded.value = true;
  }
  const i = await action(() => api<ImportPreview[]>("/data/imports"));
  if (i) imports.value = i.data;
  if (p && supportsTencent(p.data)) {
    const runs = await action(() => api<ProviderSyncRun[]>("/data/sync-runs"));
    if (runs) syncRuns.value = runs.data;
  } else {
    syncRuns.value = [];
  }
}
onMounted(load);
function select(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0];
  preview.value = undefined;
  committed.value = false;
}
async function inspect() {
  if (!file.value) return;
  busy.value = true;
  partial.value = false;
  const body = new FormData();
  body.append("file", file.value);
  const r = await action(() =>
    api<ImportPreview>("/data/imports/preview", { method: "POST", body }),
  );
  if (r) preview.value = r.data;
  busy.value = false;
}
async function commit() {
  if (!preview.value) return;
  busy.value = true;
  const r = await action(() =>
    post<{ imported_rows: number; security_count: number }>(
      `/data/imports/${preview.value!.id}/commit`,
      { allow_partial: partial.value },
    ),
  );
  if (r) {
    inform(
      `已保存 ${r.data.imported_rows} 行行情，${r.data.security_count} 只证券`,
    );
    committed.value = true;
    await refresh();
    await load();
  }
  busy.value = false;
}
async function syncTencent() {
  if (syncBlockReason.value) {
    inform(syncBlockReason.value);
    return;
  }
  syncBusy.value = true;
  syncError.value = "";
  syncResult.value = undefined;
  try {
    const result = await post<ProviderSyncResult>(
      "/data/providers/tencent/sync",
      {
        security_ids: syncIds.value,
        sync_daily: syncDaily.value,
      },
    );
    syncResult.value = result.data;
    inform(
      `腾讯公开行情同步返回：${result.data.quotes_updated} 条快照，${result.data.daily_rows_saved} 条日线`,
    );
    await refresh();
    await load();
  } catch (error) {
    syncError.value =
      error instanceof Error ? error.message : "公开行情同步失败";
    inform(syncError.value);
  } finally {
    syncBusy.value = false;
  }
}
function template() {
  const text = "code,name,date,open,high,low,close,volume,amount\r\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(
    new Blob(["\ufeff" + text], { type: "text/csv;charset=utf-8" }),
  );
  a.download = "行情导入模板.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
</script>
<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">DATA / 12 · SYSTEM / 14</div>
      <h1>数据与工作台设置</h1>
    </div>
    <button class="button" @click="load">
      <RefreshCw :size="14" />刷新诊断
    </button>
  </section>
  <div class="tabs bottom-gap">
    <button
      v-for="t in ['数据管理', '模型与运行', '外观与关于']"
      :class="{ active: tab === t }"
      @click="tab = t"
    >
      {{ t }}
    </button>
  </div>
  <template v-if="tab === '数据管理'"
    ><DataAutomationPanel />
    <div class="settings-grid">
      <section class="panel inset">
        <div class="flex spread">
          <h2>历史行情导入</h2>
          <span class="badge blue">CSV · UTF-8 / GBK</span>
        </div>
        <p class="muted">先预览再提交，不直接覆盖原始决策快照。</p>
        <label class="file-drop"
          ><Upload :size="26" /><strong>{{
            file?.name ?? "选择 CSV 行情文件"
          }}</strong
          ><span>支持代码、名称、日期与 OHLCV 等基本中文别名</span
          ><input type="file" accept=".csv,text/csv" @change="select"
        /></label>
        <div class="flex spread top-gap">
          <button class="text-button tiny" @click="template">
            <Download :size="13" />下载字段模板</button
          ><button
            class="button primary"
            :disabled="!file || busy"
            @click="inspect"
          >
            {{ busy ? "处理中…" : "校验并预览" }}
          </button>
        </div>
        <p class="tiny muted">
          保留证券前导零。首批只接收标准
          CSV；同花顺原生文件、Excel、成交记录和公式导入尚未开放。
        </p>
        <div v-if="preview" class="preview-box">
          <h3>{{ preview.filename }}</h3>
          <div class="flex">
            <span class="badge blue">有效 {{ preview.valid_rows }} 行</span
            ><span class="badge">异常 {{ preview.invalid_rows }} 行</span>
          </div>
          <p class="tiny">证券 {{ preview.securities.join("、") }}</p>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th v-for="c in preview.columns">{{ c }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in preview.sample.slice(0, 4)" :key="i">
                  <td v-for="c in preview.columns">{{ row[c] ?? "—" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-for="e in preview.errors.slice(0, 20)" class="error-line">
            第 {{ e.row }} 行：{{ e.message }}
          </p>
          <label v-if="preview.invalid_rows" class="check-row"
            ><input
              type="checkbox"
              v-model="partial"
            />我确认仅导入有效行，保留异常报告</label
          ><button
            class="button primary top-gap"
            :disabled="
              busy ||
              committed ||
              (!preview.can_commit && !partial) ||
              !preview.valid_rows
            "
            @click="commit"
          >
            <Check :size="15" />{{
              committed ? "已提交保存" : "确认导入并保存"
            }}
          </button>
        </div>
      </section>
      <section class="panel inset">
        <div class="flex spread">
          <h2>数据源状态</h2>
          <span
            :class="[
              'badge',
              'source-badge',
              modeDescription(state.meta.mode).tone,
            ]"
          >
            {{ modeDescription(state.meta.mode).label }}
          </span>
        </div>
        <div class="source-overview">
          <div>
            <span>当前数据说明</span
            ><strong>{{ state.meta.source || "尚无数据来源信息" }}</strong>
          </div>
          <div>
            <span>最近行情时间</span
            ><strong>{{ date(state.meta.as_of) }}</strong>
          </div>
          <div>
            <span>数据状态</span
            ><strong>{{
              state.meta.stale
                ? "数据可能已过期"
                : state.meta.as_of
                  ? "服务端有时间戳"
                  : "没有可用行情"
            }}</strong>
          </div>
        </div>

        <div v-for="p in providers" :key="p.id" class="provider-row">
          <div class="flex spread">
            <strong>{{ p.name }}</strong
            ><span :class="['badge', 'source-badge', presentProvider(p).tone]">
              {{ presentProvider(p).connection }}
            </span>
          </div>
          <div class="provider-facts">
            <span
              >数据模式 <strong>{{ presentProvider(p).mode }}</strong></span
            >
            <span
              >最近更新
              <strong>{{ date(presentProvider(p).updatedAt) }}</strong></span
            >
          </div>
          <p class="tiny muted">{{ p.source }}</p>
          <details class="terminal-details">
            <summary>能力与来源详情</summary>
            <p class="tiny source-detail">{{ presentProvider(p).detail }}</p>
            <div class="flex wrap">
              <span class="mini-tag" v-for="c in p.capabilities">{{ c }}</span>
            </div>
            <p class="tiny muted" v-for="l in p.limitations">{{ l }}</p>
          </details>
        </div>
        <p v-if="providersLoaded && !providers.length" class="muted">
          服务端未返回可用数据源。
        </p>
        <p v-if="!providersLoaded" class="muted">
          数据源诊断尚未加载或本地服务不可用；连接状态未知。
        </p>
        <details
          class="divider top-gap sync-box"
          :class="{ 'sync-disabled': !supportsTencent(providers) }"
        >
          <summary>高级：手动补充行情</summary>
          <p v-if="!supportsTencent(providers)" class="error-line">
            当前后端未报告腾讯行情
            Provider，行情同步入口已禁用；请重启更新后的后端后刷新本页。
          </p>
          <div class="sync-options">
            <label
              ><input
                type="radio"
                value="codes"
                v-model="syncScope"
              />输入真实股票代码</label
            >
            <label
              ><input
                type="radio"
                value="watchlist"
                v-model="syncScope"
              />同步真实来源自选（{{ realWatchIds.length }}）</label
            >
            <label
              ><input
                type="radio"
                value="selected"
                v-model="syncScope"
              />手动选择证券</label
            >
            <label class="check-row"
              ><input
                type="checkbox"
                v-model="syncDaily"
              />同步未复权已完成日线</label
            >
          </div>
          <div v-if="syncScope === 'codes'" class="sync-code-input">
            <label for="sync-security-codes"
              >沪深 A 股代码（以逗号、空格或换行分隔）</label
            >
            <textarea
              id="sync-security-codes"
              v-model="codeInput"
              rows="3"
              placeholder="例如：600519, 000001&#10;不会自动替你填写或同步"
            />
            <p v-for="e in parsedCodes.errors" :key="e" class="error-line">
              {{ e }}
            </p>
          </div>
          <div v-if="syncScope === 'selected'" class="sync-security-list">
            <label v-for="s in syncCandidates" :key="s.id" class="check-row">
              <input
                type="checkbox"
                :value="s.id"
                v-model="selectedSecurityIds"
              />
              {{ s.name }}（{{ s.code }}）
            </label>
          </div>
          <div
            v-if="
              (syncScope === 'watchlist' && !realWatchIds.length) ||
              (syncScope === 'selected' && !syncCandidates.length)
            "
            class="sync-empty-state"
            role="status"
          >
            <strong>{{
              syncScope === "watchlist"
                ? "还没有真实来源自选股"
                : "还没有已同步的真实证券"
            }}</strong>
            <p class="tiny muted">
              先输入股票代码并同步行情，再到「市场」把真实证券加入自选，即可使用自选同步。演示证券不计入这里。
            </p>
            <button class="button small" @click="enterStockCodes">
              改为输入股票代码
            </button>
          </div>
          <p class="tiny muted">
            已选 {{ syncIds.length }} 只；{{
              syncDaily ? "包含日线时每次最多 5 只" : "仅快照每次最多 50 只"
            }}。同步保留独立真实来源证券，不覆盖 CSV
            或演示数据，不自动加入自选。
          </p>
          <button
            class="button primary top-gap"
            :disabled="!!syncBlockReason"
            aria-describedby="sync-block-reason"
            @click="syncTencent"
          >
            <CloudDownload :size="14" />{{
              syncBusy ? "同步中…" : "开始手动同步"
            }}
          </button>
          <p id="sync-block-reason" class="tiny muted" role="status">
            {{ syncBlockReason || "已就绪，点击按钮开始同步所选证券。" }}
          </p>
          <p v-if="syncError" class="error-line" role="alert">
            {{ syncError }}
          </p>
          <div v-if="syncResult" class="sync-result">
            <strong>{{
              syncResult.status === "SUCCEEDED" ? "同步完成" : "同步已返回结果"
            }}</strong>
            <span
              >处理 {{ syncResult.securities_processed }} 只 · 快照
              {{ syncResult.quotes_updated }} 条 · 日线
              {{ syncResult.daily_rows_saved }} 行</span
            >
            <p v-for="e in syncResult.errors" :key="e" class="error-line">
              {{ e }}
            </p>
            <p v-for="l in syncResult.limitations" :key="l" class="tiny muted">
              {{ l }}
            </p>
          </div>
        </details>
        <details class="divider top-gap">
          <summary>合成演示数据</summary>
          <p class="tiny muted">
            用户显式载入，不替代真实市场数据；重复载入不清空用户数据。
          </p>
          <button class="button" @click="seed">载入合成演示数据</button>
        </details>
      </section>
    </div>
    <details class="panel inset top-gap">
      <summary>行情同步记录（{{ syncRuns.length }}）</summary>
      <div v-for="run in syncRuns" :key="run.id" class="compact-row">
        <span
          >{{ date(run.started_at) }} ·
          {{
            run.status === "SUCCEEDED"
              ? "已完成"
              : run.status === "PARTIAL"
                ? "部分完成"
                : "失败"
          }}</span
        >
        <span
          >快照 {{ run.quotes_updated }} · 日线 {{ run.daily_rows_saved }}</span
        >
        <span class="error-line">{{
          run.errors.join("；") || "无错误记录"
        }}</span>
      </div>
      <p v-if="!syncRuns.length" class="muted">尚无公开行情同步记录。</p>
    </details>
    <section class="panel inset top-gap">
      <h2>导入记录</h2>
      <div v-for="i in imports" class="compact-row">
        <span>{{ i.filename }}</span
        ><span>有效 {{ i.valid_rows }} / 异常 {{ i.invalid_rows }}</span
        ><button
          class="text-button tiny"
          @click="
            preview = i;
            committed = false;
          "
        >
          查看校验报告
        </button>
      </div>
      <p v-if="!imports.length" class="muted">尚无导入记录。</p>
    </section></template
  >
  <section v-else-if="tab === '模型与运行'" class="settings-runtime-stack">
    <AutomationPanel />
    <section class="panel inset">
    <div class="section-label">
      <h2>Agent 模型状态</h2>
      <span class="badge blue">{{
        state.settings?.agent_configured ? "已配置" : "未配置"
      }}</span>
    </div>
    <p>当前模型：{{ state.settings?.agent_model ?? "未配置 LLM" }}</p>
    <p class="muted">
      密钥通过后端环境变量设置，不发送给前端。未配置时复核返回等待；规则演示始终标记“非
      AI”。
    </p>
    <div class="subtle">
      连接配置由本机服务管理；当前界面不保存模型密钥、券商凭据，也不提供任意工具执行。
    </div>
    <h3 class="top-gap">运行诊断</h3>
    <div class="facts-grid">
      <div>
        <span>工作台版本</span
        ><strong>{{ state.settings?.version ?? "0.2" }}</strong>
      </div>
      <div>
        <span>数据模式</span><strong>{{ label(state.meta.mode) }}</strong>
      </div>
      <div>
        <span>最后保存数据</span><strong>{{ date(state.meta.as_of) }}</strong>
      </div>
    </div>
    <ul>
      <li v-for="l in state.settings?.limitations">{{ l }}</li>
    </ul>
    <p class="tiny muted">行情自动更新与算法监测分别配置。停机期间不运行。</p>
    </section>
  </section>
  <section v-else class="panel inset">
    <h2>波普复古 · 专注研究</h2>
    <p>奶油纸、钴蓝、黄块与墨黑边框；图表使用干净中性色，保留红涨绿跌。</p>
    <p>
      数字使用等宽字体；系统减少动画偏好会自动生效。页面支持键盘焦点与屏幕阅读标签。
    </p>
    <h3 class="top-gap">组件与许可</h3>
    <p class="muted">
      TradingView Lightweight Charts™ · Copyright (с) 2025 TradingView, Inc.
      https://www.tradingview.com/。Vue / Vite（MIT）、Lucide
      图标（ISC）、TradingView Lightweight
      Charts（Apache-2.0，附归属链接）。本工作台未复制 go-stock 源码。
    </p>
    <p class="tiny muted">
      字体使用本机中文字体回退，不从外网加载字体。不提供未经验证的完整桌面打包、商业行情或实盘能力。
    </p>
  </section>
</template>
