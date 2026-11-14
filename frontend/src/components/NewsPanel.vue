<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { RefreshCw, ArrowUpRight, ChevronDown, X } from 'lucide-vue-next';
import { api, post } from '../api';
import { articleUrl, unseenCount, type NewsFeed, type NewsItem } from '../news';
const props = defineProps<{ selected?: { id: string; name: string } }>();
const emit = defineEmits<{ open: [id: string]; clear: [] }>();
const tab = ref(props.selected ? 'announcements' : 'market');
const feed = ref<NewsFeed>();
const items = ref<NewsItem[]>([]);
const pending = ref<NewsFeed>();
const busy = ref(false);
const error = ref('');
const expanded = ref(new Set<string>());
const scroller = ref<HTMLElement>();
const newCount = computed(() => unseenCount(items.value, pending.value?.items ?? []));
let controller: AbortController | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
let initialized = false;
function query() {
  return `tab=${tab.value}${props.selected && tab.value !== 'watch' ? `&security_id=${encodeURIComponent(props.selected.id)}` : ''}`;
}
async function load(reset = false) {
  controller?.abort();
  const ctrl = new AbortController();
  controller = ctrl;
  if (reset) {
    busy.value = true;
    items.value = [];
    pending.value = undefined;
    expanded.value = new Set();
    initialized = false;
    feed.value = undefined;
    error.value = '';
    if (scroller.value) scroller.value.scrollTop = 0;
  }
  try {
    const response = await api<NewsFeed>(`/market/news?${query()}`, { signal: ctrl.signal });
    if (ctrl !== controller || disposed) return;
    const next = response.data;
    feed.value = next;
    error.value = '';
    if (!initialized || !items.value.length) {
      items.value = next.items;
      initialized = !!next.items.length;
    } else if (unseenCount(items.value, next.items)) {
      pending.value = next;
    }
  } catch (e) {
    if (!ctrl.signal.aborted) error.value = e instanceof Error ? e.message : '资讯读取失败';
  } finally {
    if (ctrl === controller) busy.value = false;
  }
}
async function poll() {
  await load();
  if (!disposed) timer = setTimeout(poll, 10000);
}
async function retry() {
  busy.value = true;
  try {
    await post(`/market/news/refresh${props.selected && tab.value !== 'watch' ? `?security_id=${encodeURIComponent(props.selected.id)}` : ''}`);
    await load();
  } catch (e) { error.value = e instanceof Error ? e.message : '更新失败'; }
  finally { busy.value = false; }
}
function showNew() {
  if (!pending.value) return;
  items.value = pending.value.items;
  pending.value = undefined;
  if (scroller.value) scroller.value.scrollTop = 0;
}
function toggle(id: string) {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expanded.value = next;
}
function dateLabel(value: string, precision: string) {
  const day = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).format(new Date(value));
  const time = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false, hour: '2-digit', minute: '2-digit' }).format(new Date(value));
  return precision === 'DATE' ? day : `${day} ${time}`;
}
const emptyText = computed(() => {
  if (props.selected && tab.value !== 'watch') return '最近来源内容中暂无该股相关信息';
  if (tab.value === 'watch') return feed.value?.watch_count ? '最近快讯和公告中暂无自选相关信息' : '加入自选后，在这里查看相关快讯和公告';
  return tab.value === 'announcements' ? '暂无公司公告' : '暂无市场快讯';
});
watch(tab, () => load(true));
watch(() => props.selected?.id, () => {
  const nextTab = props.selected ? 'announcements' : 'market';
  if (tab.value !== nextTab) tab.value = nextTab;
  else load(true);
});
onMounted(() => { load(true); timer = setTimeout(poll, 10000); });
onUnmounted(() => { disposed = true; clearTimeout(timer); controller?.abort(); });
</script>

<template>
  <section class="panel news-panel" aria-label="市场资讯">
    <header class="market-panel-heading">
      <div class="market-panel-title">
        <h2>资讯</h2>
        <button v-if="newCount" class="news-pending" @click="showNew">{{ newCount }} 条新消息 ↑</button>
        <button class="icon-button" aria-label="更新资讯" :disabled="busy || feed?.refreshing" @click="retry">
          <RefreshCw :size="17" />
        </button>
      </div>
      <div class="tabs news-tabs" aria-label="资讯分类">
        <button v-for="[value, label] in (selected ? [['announcements', '公司公告'], ['market', '市场快讯'], ['watch', '自选相关']] : [['market', '市场快讯'], ['watch', '自选相关'], ['announcements', '公司公告']])"
          :key="value" :class="{ active: tab === value }" :aria-pressed="tab === value" @click="tab = value">{{ label }}</button>
      </div>
    </header>
    <div ref="scroller" class="news-scroll" role="region" aria-label="资讯列表" tabindex="0" :aria-busy="busy">
      <div v-if="selected && tab !== 'watch'" class="news-context">
        <span>{{ selected.name }} · 相关资讯</span>
        <button class="text-button" aria-label="返回全部资讯" @click="emit('clear')"><X :size="15" />全部</button>
      </div>
      <p v-if="error || feed?.error" class="news-status error-line" role="status">{{ error || feed?.error }}<span v-if="items.length"> · 已保留上次内容</span></p>
      <div v-if="!items.length" class="news-empty" role="status">
        <strong>{{ busy || feed?.refreshing || feed?.status === 'LOADING' ? '正在读取资讯…' : error || feed?.error ? '资讯暂不可用' : emptyText }}</strong>
        <button v-if="!busy && !feed?.refreshing" class="text-button" @click="retry">重新获取</button>
      </div>
      <article v-for="item in items" :key="item.id" class="news-item">
        <div class="news-meta"><time :datetime="item.published_at">{{ dateLabel(item.published_at, item.publication_precision) }}</time>
          <span>{{ item.source }}</span><span v-if="item.kind === 'announcement'" class="news-kind">公告</span></div>
        <button class="news-title" :aria-expanded="expanded.has(item.id)" @click="toggle(item.id)">
          <span>{{ item.title }}</span><ChevronDown :size="16" :class="{ expanded: expanded.has(item.id) }" />
        </button>
        <div v-if="expanded.has(item.id)" class="news-detail">
          <p>{{ item.summary }}</p>
          <a v-if="articleUrl(item.url)" :href="articleUrl(item.url)" target="_blank" rel="noopener noreferrer">查看{{ item.kind === 'announcement' ? '公告' : '消息' }}原文 <ArrowUpRight :size="14" /></a>
        </div>
        <div v-if="item.securities.length" class="news-securities">
          <button v-for="stock in item.securities" :key="stock.id" @click="emit('open', stock.id)">{{ stock.name }} <span>{{ stock.code }}</span></button>
        </div>
      </article>
    </div>
    <footer class="news-footer">
      <span>{{ !feed?.enabled && feed ? '自动更新已暂停' : feed?.refreshing ? '更新中' : feed?.stale ? '缓存内容' : '按来源更新' }}<template v-if="feed?.updated_at"> · 获取 {{ dateLabel(feed.updated_at, 'TIME') }}</template></span>
      <span v-if="tab === 'watch'">最多 {{ feed?.watch_limit ?? 20 }} 只自选 · 不代表完整历史</span>
      <span v-else>发布时间见条目 · 公告仅提供目录</span>
    </footer>
  </section>
</template>
