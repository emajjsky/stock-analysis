<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Maximize2, Minimize2, Search } from 'lucide-vue-next';
import { boardTiles, wan, type Board, type BoardCache } from '../boards';
import { percent } from '../terminal';
import { direction } from '../format';

const props = defineProps<{ boards: Board[]; selected?: string; kind: string; cache?: Partial<BoardCache> }>();
defineEmits<{ select: [code: string] }>();
const panel = ref<HTMLElement>(), canvas = ref<HTMLElement>();
const width = ref(1200), height = ref(520), query = ref('');
const weight = ref<'amount' | 'equal'>('amount'), metric = ref<'change_pct' | 'net_ratio'>('change_pct');
const full = ref(false), hovered = ref<Board>();
let observer: ResizeObserver | undefined;
const filtered = computed(() => props.boards.filter(b => !query.value || (b.name + b.code).toLowerCase().includes(query.value.toLowerCase())));
const tiles = computed(() => boardTiles(filtered.value, width.value, height.value, weight.value));
const selectedBoard = computed(() => hovered.value ?? props.boards.find(b => b.code === props.selected));
function color(b: Board) {
  const raw = b[metric.value];
  if (raw == null || !Number.isFinite(Number(raw))) return '#97998b';
  const n = Number(raw), level = Math.min(1, Math.abs(n) / (metric.value === 'change_pct' ? 4 : 12));
  if (n === 0) return '#8c9084';
  return n > 0 ? `hsl(354 48% ${58 - level * 18}%)` : `hsl(152 42% ${48 - level * 17}%)`;
}
function labels(t: (typeof tiles.value)[number]) {
  const w = t.width * width.value / 100, h = t.height * height.value / 100;
  return { name: w > 47 && h > 19, value: w > 47 && h > 36, large: w > 110 && h > 70 };
}
function describe(b: Board) {
  return `${b.name} ${b.code} · 涨跌幅 ${percent(b.change_pct)} · 主力净额占比 ${percent(b.net_ratio)} · 成交额 ${wan(b.amount)}万元`;
}
async function toggleFull() {
  if (document.fullscreenElement) await document.exitFullscreen();
  else await panel.value?.requestFullscreen();
}
function fullscreenChanged() { full.value = document.fullscreenElement === panel.value; }
onMounted(() => {
  observer = new ResizeObserver(entries => {
    const r = entries[0]?.contentRect;
    if (r && r.width > 0 && r.height > 0) { width.value = r.width; height.value = r.height; }
  });
  if (canvas.value) observer.observe(canvas.value);
  document.addEventListener('fullscreenchange', fullscreenChanged);
});
onUnmounted(() => { observer?.disconnect(); document.removeEventListener('fullscreenchange', fullscreenChanged); });
</script>

<template>
  <section ref="panel" class="heatmap-panel" :class="{ fullscreen: full }" aria-label="全景板块热力图">
    <header class="heatmap-toolbar">
      <div class="heatmap-heading"><strong>板块全景</strong><span>{{ kind === 'industry' ? '行业 · 含细分' : '概念' }} <b>{{ tiles.length }}</b> / {{ boards.length }}</span></div>
      <div class="heatmap-controls">
        <label>面积<select v-model="weight" aria-label="热力图面积"><option value="amount">成交额</option><option value="equal">等面积</option></select></label>
        <label>颜色<select v-model="metric" aria-label="热力图颜色"><option value="change_pct">涨跌幅</option><option value="net_ratio">主力净额占比</option></select></label>
        <label class="heatmap-search"><Search :size="14" /><input v-model="query" aria-label="搜索热力图" placeholder="搜索板块 / 代码" /></label>
        <button class="heatmap-fullscreen" :aria-label="full ? '退出热力图全屏' : '热力图全屏'" :title="full ? '退出全屏' : '全屏查看'" @click="toggleFull"><Minimize2 v-if="full" :size="16" /><Maximize2 v-else :size="16" /></button>
      </div>
    </header>
    <div ref="canvas" class="board-heatmap" aria-label="板块成交额热力图" @mouseleave="hovered = undefined">
      <button v-for="t in tiles" :key="t.board.code" :style="{ left: t.x + '%', top: t.y + '%', width: t.width + '%', height: t.height + '%', background: color(t.board) }"
        :class="{ selected: selected === t.board.code, large: labels(t).large }" :title="describe(t.board)" :aria-label="describe(t.board)" :aria-pressed="selected === t.board.code"
        @mouseenter="hovered = t.board" @focus="hovered = t.board" @blur="hovered = undefined" @click="$emit('select', t.board.code)">
        <strong v-if="labels(t).name">{{ t.board.name }}</strong><span v-if="labels(t).value">{{ percent(t.board[metric]) }}</span>
      </button>
      <div v-if="!tiles.length" class="heatmap-empty">{{ query ? '没有匹配的板块' : cache?.error || (cache?.refreshing ? '正在获取板块数据…' : '当前暂无有效成交额，可切换等面积查看全部板块') }}</div>
    </div>
    <footer class="heatmap-footer">
      <div class="heatmap-inspect" aria-live="polite"><template v-if="selectedBoard"><strong>{{ selectedBoard.name }}</strong><span :class="direction(selectedBoard.change_pct)">{{ percent(selectedBoard.change_pct) }}</span><span>成交额 <b>{{ wan(selectedBoard.amount) }}</b> 万元</span></template><span v-else>悬停查看数据 · 点击联动下方走势和成分股</span></div>
      <div class="heatmap-legend"><span>跌</span><i v-for="(c, i) in ['#247c53','#489c70','#a2a394','#be7379','#b63845']" :key="c" :style="{background:c}" :title="['跌幅较大','下跌','零值附近','上涨','涨幅较大'][i]"></i><span>涨</span><small>灰色：缺失</small></div>
    </footer>
  </section>
</template>

<style scoped>
.heatmap-panel { display:flex; flex-direction:column; min-width:0; border:1px solid #d0c5aa; border-radius:4px; background:#fffef9; overflow:hidden; }
.heatmap-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:48px; padding:7px 12px; background:#f8f3e5; border-bottom:1px solid #ded4bd; flex-wrap:wrap; }
.heatmap-heading { display:flex; align-items:center; gap:15px; white-space:nowrap; }
.heatmap-heading strong { font-size:16px; }
.heatmap-heading span { color:#8b7b5d; font-size:12px; }
.heatmap-heading b { color:#594b30; font-weight:600; }
.heatmap-controls { display:flex; align-items:center; gap:13px; flex-wrap:wrap; }
.heatmap-controls label { display:flex; align-items:center; gap:6px; font-size:12px; color:#8a7857; }
.heatmap-controls select { font-size:12px; color:#6b5734; border:1px solid #ddcfad; background:#fffdf5; padding:4px 6px; border-radius:3px; }
.heatmap-search { border:1px solid #ddcfad; border-radius:3px; background:#fffdf5; padding:4px 7px; }
.heatmap-search input { border:0; outline:0; background:none; min-width:0; width:145px; font-size:12px; }
.heatmap-fullscreen { display:flex; padding:5px; border:0; background:none; color:#8a7857; }
.board-heatmap { position:relative; height:clamp(440px,61dvh,760px); min-width:0; margin:5px; overflow:hidden; }
.board-heatmap > button { position:absolute; display:flex; flex-direction:column; align-items:center; justify-content:center; border:1px solid #fff9ed; color:#fffef5; overflow:hidden; padding:0 2px; cursor:pointer; border-radius:0; gap:1px; }
.board-heatmap strong { max-width:100%; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; font-size:11px; font-weight:500; line-height:1.3; }
.board-heatmap span { font-size:11px; line-height:1.2; font-variant-numeric:tabular-nums; }
.board-heatmap .large strong { font-size:15px; font-weight:650; }
.board-heatmap .large span { font-size:15px; }
.board-heatmap > button.selected { outline:3px solid #f6ce45; outline-offset:-3px; z-index:1; }
.board-heatmap > button:hover, .board-heatmap > button:focus-visible { outline:2px solid #fffbd0; outline-offset:-2px; z-index:2; }
.heatmap-footer { min-height:35px; padding:6px 11px; display:flex; align-items:center; justify-content:space-between; gap:12px; border-top:1px solid #e5dcc7; font-size:12px; background:#fbf7e9; }
.heatmap-inspect { display:flex; align-items:center; gap:13px; min-width:0; color:#96815e; flex-wrap:wrap; }
.heatmap-inspect strong { color:#5f5034; }.heatmap-inspect b { font-weight:500; }.up {color:#b42332}.down {color:#087f5b}
.heatmap-legend {display:flex; align-items:center; gap:3px; color:#8b7b60; flex-shrink:0; font-size:10px;}.heatmap-legend i {width:20px;height:10px;}.heatmap-legend small {margin-left:7px;}
.heatmap-empty {height:100%;display:flex;align-items:center;justify-content:center;color:#9b8966;font-size:13px;}
.heatmap-panel:fullscreen { height:100dvh; width:100dvw; padding:10px; background:#fff8e7; }.fullscreen .board-heatmap {flex:1;height:auto;}
@media(max-width:800px){.heatmap-controls{gap:8px}.heatmap-toolbar{gap:8px}.heatmap-footer{flex-wrap:wrap}.board-heatmap{height:500px}.heatmap-search input{width:125px}}
</style>
