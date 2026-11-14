<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { Search, Maximize2, X } from "lucide-vue-next";
import {
  etfEmptyMessage,
  matchEtfs,
  wan,
  type Etfs,
  type EtfHoldings,
} from "../boards";
import { direction, money } from "../format";
import { percent } from "../terminal";
const props = defineProps<{
  name: string;
  memberCodes: string[];
  quotes?: Etfs;
  portfolios?: EtfHoldings;
  portfoliosError?: string;
}>();
const dialog = ref<HTMLDialogElement>(),
  opened = ref(false);
const query = ref(""),
  scope = ref("related"),
  page = ref(1),
  pageSize = ref(50);
const sort = ref("amount"),
  descending = ref(true);
const matched = computed(() =>
  matchEtfs(
    props.name,
    props.quotes?.rows ?? [],
    props.memberCodes,
    props.portfolios?.rows ?? [],
  ),
);
const all = computed(() =>
  (props.quotes?.rows ?? [])
    .filter((e) => /ETF/i.test(e.name))
    .map((e) => ({ ...e, matchReason: "", matchDetail: "" })),
);
const rows = computed(() => {
  const q = query.value.trim().toLowerCase();
  return [...(scope.value === "related" ? matched.value : all.value)]
    .filter((e) => !q || (e.name + e.code).toLowerCase().includes(q))
    .sort((a, b) => {
      const x = a[sort.value as keyof typeof a],
        y = b[sort.value as keyof typeof b];
      if (x == null) return y == null ? 0 : 1;
      if (y == null) return -1;
      const value = ["name", "code"].includes(sort.value)
        ? String(x).localeCompare(String(y), "zh-CN")
        : Number(x) - Number(y);
      return descending.value ? -value : value;
    });
});
const pages = computed(() =>
  Math.max(1, Math.ceil(rows.value.length / pageSize.value)),
);
const visible = computed(() =>
  rows.value.slice(
    (page.value - 1) * pageSize.value,
    page.value * pageSize.value,
  ),
);
const empty = computed(() =>
  etfEmptyMessage(props.quotes, props.portfolios, props.portfoliosError),
);
watch([query, scope, pageSize], () => (page.value = 1));
watch(pages, (n) => (page.value = Math.min(page.value, n)));
watch(opened, async (value) => {
  await nextTick();
  if (value) dialog.value?.showModal();
  else dialog.value?.close();
});
function browse() {
  scope.value = matched.value.length ? "related" : "all";
  query.value = "";
  opened.value = true;
}
function order(key: string) {
  descending.value =
    sort.value === key ? !descending.value : !["name", "code"].includes(key);
  sort.value = key;
  page.value = 1;
}
function trapFocus(event: KeyboardEvent) {
  if (event.key !== "Tab") return;
  const items = dialog.value?.querySelectorAll<HTMLElement>(
    "button:not([disabled]), input, select, a[href]",
  );
  if (!items?.length) return;
  const first = items[0]!,
    last = items[items.length - 1]!;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
const columns = [
  { key: "name", label: "基金名称" },
  { key: "code", label: "代码" },
  { key: "price", label: "现价" },
  { key: "change_pct", label: "涨跌幅" },
  { key: "amount", label: "成交额 / 万元" },
];
</script>
<template>
  <section class="market-panel etf-panel" aria-label="相关ETF候选">
    <header class="panel-head">
      <strong title="按名称、产业主题或季度披露前十大持仓匹配；持仓交集至少3只且披露净值权重合计不少于20%"
        >相关ETF候选</strong
      ><button
        class="expand-etfs"
        aria-label="展开ETF列表"
        title="展开浏览ETF"
        @click="browse"
      >
        <Maximize2 :size="15" />
      </button>
    </header>
    <div class="etf-rows">
      <div
        v-for="e in matched"
        :key="e.code"
        class="etf-row"
        :title="
          e.matchReason +
          '；' +
          e.matchDetail +
          '；成交额 ' +
          wan(e.amount) +
          '万元'
        "
      >
        <strong>{{ e.name }}</strong
        ><small>{{ e.code }}</small
        ><b>{{ money(e.price, 3) }}</b
        ><span :class="direction(e.change_pct)">{{
          percent(e.change_pct)
        }}</span>
      </div>
      <div v-if="!matched.length" class="etf-empty">
        {{ empty }}<button @click="browse">浏览ETF</button>
      </div>
    </div>
  </section>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="etf-dialog"
      aria-label="ETF行情浏览"
      @keydown="trapFocus"
      @close="opened = false"
      @click="$event.target === dialog && (opened = false)"
    >
      <div class="etf-dialog-content">
        <header>
          <div>
            <h2>ETF行情</h2>
            <span>{{ name || "当前板块" }}</span>
          </div>
          <button aria-label="关闭ETF列表" @click="opened = false">
            <X :size="20" />
          </button>
        </header>
        <div class="etf-browser-tools">
          <select v-model="scope" aria-label="ETF浏览范围">
            <option value="related">相关候选（{{ matched.length }}）</option>
            <option value="all">全部ETF（{{ all.length }}）</option></select
          ><label
            ><Search :size="16" /><input
              v-model="query"
              aria-label="搜索ETF"
              placeholder="名称 / 代码" /></label
          ><span>{{ rows.length }}只</span>
        </div>
        <div class="etf-browser-scroll">
          <table>
            <thead>
              <tr>
                <th v-for="c in columns" :key="c.key">
                  <button @click="order(c.key)">
                    {{ c.label
                    }}{{ sort === c.key ? (descending ? " ↓" : " ↑") : "" }}
                  </button>
                </th>
                <th v-if="scope === 'related'">匹配依据</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in visible" :key="e.code" :title="e.matchDetail">
                <td>{{ e.name }}</td>
                <td>{{ e.code }}</td>
                <td>{{ money(e.price, 3) }}</td>
                <td :class="direction(e.change_pct)">
                  {{ percent(e.change_pct) }}
                </td>
                <td>{{ wan(e.amount) }}</td>
                <td v-if="scope === 'related'">{{ e.matchReason }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!visible.length" class="etf-empty">
            {{ query ? "没有匹配的ETF" : empty }}
          </div>
        </div>
        <footer>
          <label
            >每页
            <select v-model="pageSize" aria-label="ETF每页数量">
              <option :value="25">25</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select></label
          >
          <div>
            <button :disabled="page <= 1" @click="page--">上一页</button
            ><span>{{ page }} / {{ pages }}</span
            ><button :disabled="page >= pages" @click="page++">下一页</button>
          </div>
        </footer>
      </div>
    </dialog>
  </Teleport>
</template>
<style scoped>
.etf-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: #f8f3e5;
  border-bottom: 1px solid #e4dcc9;
  padding: 7px 10px;
  min-height: 35px;
  flex-shrink: 0;
}
.panel-head strong {
  font-size: 14px;
  font-weight: 650;
}
.expand-etfs {
  display: flex;
  padding: 2px;
  border: 0;
  background: none;
  color: #8a7856;
  cursor: pointer;
}
.expand-etfs:hover {
  color: #2458a6;
}
.etf-rows {
  overflow: auto;
  flex: 1;
  min-height: 0;
  padding: 0 8px;
  scrollbar-width: thin;
}
.etf-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 43px 42px 55px;
  align-items: center;
  gap: 5px;
  min-height: 27px;
  border-bottom: 1px solid #eee6d3;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.etf-row strong {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.etf-row small {
  font-size: 10px;
  color: #948263;
}
.etf-row b {
  font-weight: 500;
  text-align: right;
}
.etf-row > span {
  text-align: right;
}
.etf-empty {
  color: #9c8d6d;
  font-size: 12px;
  line-height: 1.6;
  padding: 15px 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.etf-empty button {
  border: 0;
  background: none;
  color: #2458a6;
  cursor: pointer;
}
.up {
  color: #b42332;
}
.down {
  color: #087f5b;
}
.etf-dialog {
  padding: 0;
  border: 1px solid #bfb18e;
  border-radius: 6px;
  background: #fffef9;
  color: #3e392e;
  width: min(1020px, calc(100vw - 32px));
  max-width: calc(100vw - 32px);
  height: min(740px, 86dvh);
  max-height: 86dvh;
  box-shadow: 0 14px 60px #29251a55;
}
.etf-dialog::backdrop {
  background: #29251a66;
}
.etf-dialog-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.etf-dialog header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #ded5bf;
  background: #f8f3e5;
}
.etf-dialog header > div {
  display: flex;
  gap: 18px;
  align-items: center;
}
.etf-dialog h2 {
  font-size: 19px;
  margin: 0;
}
.etf-dialog header span {
  font-size: 13px;
  color: #8d7956;
}
.etf-dialog header > button {
  display: flex;
  border: 0;
  background: none;
  color: #756441;
  cursor: pointer;
}
.etf-browser-tools {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 20px;
  font-size: 13px;
}
.etf-browser-tools label {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  border: 1px solid #d7ccb0;
  border-radius: 3px;
  padding: 5px 8px;
}
.etf-browser-tools input {
  border: 0;
  outline: 0;
  background: none;
  min-width: 0;
  width: 100%;
  font: inherit;
}
.etf-dialog select,
.etf-dialog footer button {
  background: #fffcf3;
  border: 1px solid #d7ccb0;
  border-radius: 3px;
  font-size: 13px;
  padding: 5px 8px;
  color: #756441;
}
.etf-browser-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.etf-dialog table {
  width: 100%;
  border-collapse: collapse;
  white-space: nowrap;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.etf-dialog th,
.etf-dialog td {
  padding: 10px 15px;
  text-align: right;
  border-bottom: 1px solid #ece5d5;
}
.etf-dialog th {
  position: sticky;
  top: 0;
  background: #f8f3e5;
  color: #8d7956;
  font-size: 12px;
  font-weight: 500;
}
.etf-dialog th button {
  background: none;
  border: 0;
  font: inherit;
  color: inherit;
  cursor: pointer;
}
.etf-dialog th:first-child,
.etf-dialog td:first-child {
  text-align: left;
}
.etf-dialog tbody tr:hover {
  background: #fcf5df;
}
.etf-dialog footer {
  padding: 10px 20px;
  border-top: 1px solid #ded5bf;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.etf-dialog footer > div {
  display: flex;
  align-items: center;
  gap: 16px;
}
.etf-dialog button:disabled {
  opacity: 0.4;
  cursor: default;
}
@media (max-width: 600px) {
  .etf-browser-tools {
    gap: 6px;
    padding: 10px;
  }
  .etf-browser-tools > span {
    display: none;
  }
  .etf-dialog th,
  .etf-dialog td {
    padding: 9px 10px;
  }
  .etf-dialog header {
    padding: 12px;
  }
  .etf-dialog footer {
    padding: 8px;
    gap: 6px;
  }
  .etf-dialog footer > div {
    gap: 8px;
  }
}
</style>
