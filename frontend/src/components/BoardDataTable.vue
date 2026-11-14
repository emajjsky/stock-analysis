<script setup lang="ts">
import { computed, ref } from "vue";
import { money, direction } from "../format";
import { percent } from "../terminal";
import { wan } from "../boards";
export interface MarketColumn {
  key: string;
  label: string;
  format?: "price" | "percent" | "wan" | "signedWan" | "number" | "point" | "text";
  unit?: string;
  color?: boolean;
  width?: number;
  formatValue?: (row: Record<string, any>) => string;
  directionValue?: (row: Record<string, any>) => unknown;
}
const props = defineProps<{
  rows: Record<string, any>[];
  columns: MarketColumn[];
  selected?: string;
  initialSort?: string;
  empty?: string;
  stock?: boolean;
  catalog?: boolean;
  columnWidths?: Record<string, string>;
}>();
defineEmits<{ select: [id: string]; open: [id: string]; add: [id: string] }>();
const sort = ref(""),
  descending = ref(true);
const ordered = computed(() =>
  [...props.rows].sort((a, b) => {
    const key = sort.value || props.initialSort || "change_pct",
      x = a[key],
      y = b[key];
    if (x == null || x === "") return y == null ? 0 : 1;
    if (y == null || y === "") return -1;
    return (
      (Number.isFinite(Number(x)) && Number.isFinite(Number(y))
        ? Number(x) - Number(y)
        : String(x).localeCompare(String(y), "zh-CN")) *
      (descending.value ? -1 : 1)
    );
  }),
);
function toggle(key: string) {
  if (sort.value === key) descending.value = !descending.value;
  else {
    sort.value = key;
    descending.value = !["name", "code", "date"].includes(key);
  }
}
function format(v: any, c: MarketColumn, row?: Record<string, any>) {
  if (c.formatValue && row) return c.formatValue(row);
  if (c.format === "percent")
    return c.color ? percent(v) : v == null || v === "" ? "—" : money(v) + "%";
  if (c.format === "wan" || c.format === "signedWan")
    return wan(v, c.format === "signedWan");
  if (c.format === "price") return money(v);
  if (v == null || v === "") return "—";
  if (c.format === "point") {
    const n = Number(v);
    return Number.isFinite(n) ? (n > 0 ? "+" : "") + n.toFixed(2) : "—";
  }
  if (c.format === "number")
    return Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  return String(v);
}
</script>
<template>
  <div class="market-grid-scroll">
    <table
      class="market-grid"
      :class="{ 'member-table': stock, 'board-ranking': !stock, 'catalog-grid': catalog }"
      :style="catalog ? { '--catalog-min-width': `${columns.reduce((sum, c) => sum + (c.width ?? 100), 76)}px` } : undefined"
    >
      <colgroup v-if="catalog">
        <col style="width: 2.5%" />
        <col v-for="c in columns" :key="c.key" :style="{ width: columnWidths?.[c.key] }" />
        <col v-if="stock" style="width: 2.5%" />
      </colgroup>
      <thead>
        <tr>
          <th class="row-no">#</th>
          <th
            v-for="c in columns"
            :key="c.key"
            :class="{ 'name-cell': c.key === 'name', 'code-cell': c.key === 'code' }"
          >
            <button @click="toggle(c.key)">
              {{ c.label }}<small v-if="c.unit">{{ c.unit }}</small
              ><span v-if="(sort || initialSort || 'change_pct') === c.key">{{
                descending ? " ↓" : " ↑"
              }}</span>
            </button>
          </th>
          <th v-if="stock">自选</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, i) in ordered"
          :key="row.id"
          :class="{ selected: selected === row.id }"
          tabindex="0"
          :aria-selected="selected === row.id"
          :title="row.event || undefined"
          @click="$emit('select', row.id)"
          @keydown.enter="$emit('select', row.id)"
          @dblclick="stock && $emit('open', row.id)"
        >
          <td class="row-no">{{ i + 1 }}</td>
          <td
            v-for="c in columns"
            :key="c.key"
            :class="[
              c.color ? direction(c.directionValue ? c.directionValue(row) : row[c.key]) : '',
              { 'name-cell': c.key === 'name', 'code-cell': c.key === 'code' },
            ]"
            :title="format(row[c.key], c, row)"
          >
            <button
              v-if="stock && c.key === 'name'"
              class="stock-name-link"
              @click.stop="$emit('open', row.id)"
            >
              {{ row.name }}</button
            ><span v-else>{{ format(row[c.key], c, row) }}</span>
          </td>
          <td v-if="stock" class="watch-action">
            <button
              :disabled="row.watched"
              :aria-label="`加入自选 ${row.name}`"
              @click.stop="$emit('add', row.id)"
            >
              {{ row.watched ? "✓" : "+" }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="!rows.length" class="market-empty">
      {{ empty || "暂无数据" }}
    </div>
  </div>
</template>
<style scoped>
.market-grid-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  scrollbar-width: thin;
  overscroll-behavior: contain;
}
.market-grid {
  width: 100%;
  border-collapse: collapse;
  white-space: nowrap;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.catalog-grid {
  width: 100%;
  min-width: var(--catalog-min-width, 900px);
  table-layout: fixed;
}
.catalog-grid th,
.catalog-grid td {
  padding-inline: clamp(5px, 0.45vw, 11px);
}
.market-grid th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8f5ea;
  color: #797361;
  font-size: 12px;
  font-weight: 500;
  height: 36px;
  text-align: right;
  padding: 4px 7px;
  border-bottom: 1px solid #ded7c3;
}
.market-grid th button {
  font: inherit;
  background: none;
  border: 0;
  color: inherit;
  padding: 0;
}
.market-grid small {
  display: block;
  font-size: 10px;
  color: #98907d;
  line-height: 12px;
}
.market-grid td {
  height: 31px;
  padding: 5px 7px;
  border-bottom: 1px solid #eeeadd;
  text-align: right;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.market-grid tbody tr {
  cursor: pointer;
}
.market-grid tbody tr:hover {
  background: #f5f0df;
}
.market-grid tbody tr.selected {
  background: #ffedaf;
}
.market-grid tbody tr.selected td:first-child {
  box-shadow: inset 3px 0 #bb8b24;
}
.market-grid .row-no {
  width: 26px;
  text-align: center;
  color: #a0967c;
  font-size: 11px;
}
.market-grid .name-cell {
  text-align: left;
  min-width: 92px;
  font-weight: 600;
}
.code-cell {
  font:
    12px Consolas,
    monospace;
  color: #777261;
}
.stock-name-link {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  color: inherit;
}
.stock-name-link:hover {
  color: #2458a6;
  text-decoration: underline;
}
.watch-action button {
  border: 1px solid #d8ccaa;
  background: none;
  width: 23px;
  height: 23px;
  border-radius: 3px;
}
.watch-action button:disabled {
  border-color: transparent;
}
.market-empty {
  padding: 35px 15px;
  text-align: center;
  color: #958973;
  font-size: 13px;
}
.up {
  color: #b42332;
}
.down {
  color: #087f5b;
}
@media (min-width: 1800px) {
  .market-grid {
    font-size: 14px;
  }
  .market-grid td {
    height: 33px;
    padding-inline: 9px;
  }
}
@media (max-width: 700px) {
  .market-grid {
    min-width: 620px;
  }
}
</style>
