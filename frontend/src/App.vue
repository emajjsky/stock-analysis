<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from "vue";
import {
  Compass,
  ChartNoAxesCombined,
  CandlestickChart,
  Star,
  Radio,
  FlaskConical,
  ArrowLeftRight,
  Settings,
  Search,
  Bell,
  ArrowUpRight,
  ChevronDown,
  Database,
  RefreshCw,
  X,
  Menu,
  Settings2,
  Check,
  PanelLeftClose,
  PanelLeftOpen,
  CalendarDays,
  Globe,
} from "lucide-vue-next";
import { state, loading, error, toast, refresh, seed, action } from "./state";
import { api, patch } from "./api";
import type { Security, Notice } from "./types";
import { date, label, money, direction } from "./format";
import HomeView from "./views/HomeView.vue";
import DiscoverView from "./views/DiscoverView.vue";
import MarketView from "./views/MarketView.vue";
import StockView from "./views/StockView.vue";
import SignalsView from "./views/SignalsView.vue";
import ValidationView from "./views/ValidationView.vue";
import TradingView from "./views/TradingView.vue";
import SettingsView from "./views/SettingsView.vue";
import WatchlistView from "./views/WatchlistView.vue";
import RuleEditor from "./components/RuleEditor.vue";
import IpoView from './views/IpoView.vue';
import WebBrowserView from './views/WebBrowserView.vue';
import './webBrowser';
const nav = [
  { id: "home", name: "首页", icon: ChartNoAxesCombined },
  { id: "discover", name: "发现", icon: Compass },
  { id: "market", name: "市场", icon: CandlestickChart },
  { id: "watch", name: "自选", icon: Star },
  { id: "ipo", name: "新股", icon: CalendarDays },
  { id: "web", name: "网页行情", icon: Globe },
  { id: "signals", name: "信号", icon: Radio },
  { id: "validation", name: "验证", icon: FlaskConical },
  { id: "trading", name: "交易", icon: ArrowLeftRight },
];
const sidebarPreferenceKey = 'wangzha-sidebar-collapsed-v1';
const sidebarCollapsed = ref((()=>{
  try { return localStorage.getItem(sidebarPreferenceKey)==='true'; } catch { return false; }
})());
const navTooltip=ref<{label:string;top:number;left:number}>();
const nativeTooltips = window.wangzhaBrowser?.nativeTooltips === true;
function showNavTooltip(event: Event,label: string) {
  if (!sidebarCollapsed.value || !window.matchMedia('(min-width:761px)').matches) return;
  const rect=(event.currentTarget as HTMLElement).getBoundingClientRect();
  navTooltip.value={label,top:rect.top+rect.height/2,left:rect.right+12};
  if (nativeTooltips) void window.wangzhaBrowser!.command('tooltip', {
    visible:true,label,x:navTooltip.value.left-5,y:navTooltip.value.top-18,
  }).catch(()=>{});
}
function hideNavTooltip() {
  navTooltip.value=undefined;
  if (nativeTooltips) void window.wangzhaBrowser!.command('tooltip',{visible:false}).catch(()=>{});
}
watch(sidebarCollapsed,(value)=>{
  hideNavTooltip();
  try { localStorage.setItem(sidebarPreferenceKey,String(value)); } catch { /* 导航偏好保存失败不影响使用。 */ }
});
const page = ref("home"),
  stock = ref(""),
  rule = ref(false),
  ruleSecurity = ref<string>(),
  notifications = ref(false),
  q = ref(""),
  searchResults = ref<Security[]>([]),
  searching = ref(false),
  searchError = ref(""),
  searchIndex = ref(-1),
  searchOpen = ref(false),
  mobileMenu = ref(false);
const webUrl = ref<string>();
function showWeb(event: Event) {
  webUrl.value = (event as CustomEvent<{url?:string}>).detail?.url;
  navigate('web');
}
watch([notifications,rule,mobileMenu],([a,b,c])=>{
  if(a||b||c)void window.wangzhaBrowser?.command('viewport',{visible:false});
  else void nextTick(()=>window.dispatchEvent(new Event('wangzha-browser-layout')));
});
let searchTimer: ReturnType<typeof setTimeout>;
let searchController: AbortController | undefined;
let cacheTimer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
const cacheController = new AbortController();
const unread = computed(
  () => state.notifications.filter((n) => !n.read).length,
);
function navigate(id: string) {
  hideNavTooltip();
  page.value = id;
  stock.value = "";
  mobileMenu.value = false;
  searchOpen.value = false;
  const hash = id === "home" ? "" : `#/${id}`;
  history.replaceState(null, "", location.pathname + hash);
}
function openStock(id: string) {
  stock.value = id;
  searchOpen.value = false;
  q.value = "";
  history.replaceState(null, "", `#/stock/${encodeURIComponent(id)}`);
}
function rules(id?: string) {
  ruleSecurity.value = id;
  rule.value = true;
}
function search() {
  clearTimeout(searchTimer);
  searchController?.abort();
  searchOpen.value = !!q.value.trim();
  searchIndex.value = -1;
  searchResults.value = [];
  searchError.value = "";
  if (!q.value.trim()) {
    searching.value = false;
    return;
  }
  searching.value = true;
  searchTimer = setTimeout(() => runSearch(), 180);
}
async function runSearch(openOnUnique = false) {
  clearTimeout(searchTimer);
  searchController?.abort();
  const query = q.value.trim();
  if (!query) return;
  const controller = new AbortController();
  searchController = controller;
  searching.value = true;
  searchOpen.value = true;
  searchError.value = "";
  try {
    const r = await api<Security[]>(
      `/securities?q=${encodeURIComponent(query)}`,
      { signal: controller.signal },
    );
    if (controller !== searchController || disposed) return;
    searchResults.value = r.data;
    if (openOnUnique && r.data.length === 1) openStock(r.data[0].id);
  } catch (e) {
    if (!controller.signal.aborted) {
      searchResults.value = [];
      searchError.value = e instanceof Error ? e.message : "搜索失败";
    }
  } finally {
    if (controller === searchController) searching.value = false;
  }
}
function searchKey(e: KeyboardEvent) {
  if (e.isComposing) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    searchOpen.value = true;
    const count = searchResults.value.length;
    if (count) {
      searchIndex.value =
        searchIndex.value < 0
          ? e.key === "ArrowDown"
            ? 0
            : count - 1
          : (searchIndex.value + (e.key === "ArrowDown" ? 1 : -1) + count) %
            count;
      nextTick(() =>
        document
          .getElementById(`search-result-${searchIndex.value}`)
          ?.scrollIntoView({ block: "nearest" }),
      );
    }
  }
  if (e.key === "Enter") {
    e.preventDefault();
    if (
      !searching.value &&
      searchIndex.value >= 0 &&
      searchResults.value[searchIndex.value]
    )
      openStock(searchResults.value[searchIndex.value].id);
    else runSearch(true);
  }
}
async function pollCache() {
  try {
    const [r,n] = await Promise.all([api<Security[]>("/securities", { signal: cacheController.signal }),api<Notice[]>("/notifications",{signal:cacheController.signal})]);
    if (!disposed) {
      state.securities = r.data;
      state.notifications = n.data;
      state.meta = r.meta;
      state.watchlists = state.watchlists.map((w) => ({
        ...w,
        security: r.data.find((s) => s.id === w.security_id) ?? w.security,
      }));
    }
  } catch {}
  if (!disposed) cacheTimer = setTimeout(pollCache, 10000);
}
async function readNotice(id: string) {
  if (await action(() => patch(`/notifications/${id}`, { read: true })))
    await refresh();
}
function outsideSearch(e: PointerEvent) {
  if (e.target instanceof Element && !e.target.closest(".global-search"))
    searchOpen.value = false;
}
function key(e: KeyboardEvent) {
  if (e.key === "Escape") {
    mobileMenu.value = false;
    hideNavTooltip();
    rule.value = false;
    notifications.value = false;
    searchOpen.value = false;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    document.getElementById("global-search")?.focus();
  }
}
onMounted(async () => {
  await refresh();
  if (disposed) return;
  pollCache();
  const hash = decodeURIComponent(location.hash);
  if (hash.startsWith("#/stock/")) stock.value = hash.slice(8);
  else if (hash.startsWith("#/")) page.value = hash.slice(2);
  document.addEventListener("keydown", key);
  document.addEventListener("pointerdown", outsideSearch);
  window.addEventListener('resize',hideNavTooltip);
  window.addEventListener('wangzha-open-browser',showWeb);
});
onUnmounted(() => {
  document.removeEventListener("keydown", key);
  document.removeEventListener("pointerdown", outsideSearch);
  window.removeEventListener('resize',hideNavTooltip);
  window.removeEventListener('wangzha-open-browser',showWeb);
  disposed = true;
  clearTimeout(searchTimer);
  clearTimeout(cacheTimer);
  cacheController.abort();
  searchController?.abort();
});
</script>
<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed':sidebarCollapsed }">
    <aside
      id="workspace-navigation"
      class="app-sidebar"
      :class="{ expanded: mobileMenu }"
      aria-label="工作区导航"
    >
      <div class="sidebar-brand-row">
      <a href="#" class="brand" aria-label="王炸首页" @click.prevent="navigate('home')"
        ><span class="brand-symbol">股</span>
        <strong class="brand-name">王炸</strong></a
      >
      <button class="icon-button sidebar-toggle" :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'" :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'" :aria-expanded="!sidebarCollapsed" aria-controls="workspace-navigation" @click="sidebarCollapsed=!sidebarCollapsed"><component :is="sidebarCollapsed ? PanelLeftOpen : PanelLeftClose" :size="18" /></button>
      <button class="icon-button mobile-nav-close" aria-label="关闭导航" @click="mobileMenu=false"><X :size="19" /></button>
      </div>
      <nav aria-label="主要功能" @scroll="hideNavTooltip">
        <button
          v-for="n in nav"
          :key="n.id"
          :class="{ active: page === n.id && !stock }"
          :aria-label="n.name"
          :aria-current="page===n.id && !stock ? 'page' : undefined"
          :aria-describedby="navTooltip?.label===n.name ? 'sidebar-tooltip' : undefined"
          @mouseenter="showNavTooltip($event,n.name)"
          @mouseleave="hideNavTooltip"
          @focus="showNavTooltip($event,n.name)"
          @blur="hideNavTooltip"
          @click="navigate(n.id)"
        >
          <component :is="n.icon" :size="20" /><span class="nav-label"
            ><strong>{{ n.name }}</strong></span
          ><span
            v-if="n.id === 'signals' && state.signals.length"
            class="nav-count"
            >{{ state.signals.length }}</span
          ><ArrowUpRight v-if="page === n.id && !stock" :size="16" />
        </button>
      </nav>
      <div class="sidebar-footer">
        <button aria-label="算法与规则" :aria-describedby="navTooltip?.label==='算法与规则' ? 'sidebar-tooltip' : undefined" @mouseenter="showNavTooltip($event,'算法与规则')" @mouseleave="hideNavTooltip" @focus="showNavTooltip($event,'算法与规则')" @blur="hideNavTooltip" @click="hideNavTooltip(); rules()"><Settings2 :size="19" /><span class="nav-label">算法与规则</span></button
        ><button
          @click="navigate('settings')"
          :class="{ selected: page === 'settings' }"
          aria-label="数据与设置"
          :aria-describedby="navTooltip?.label==='数据与设置' ? 'sidebar-tooltip' : undefined"
          @mouseenter="showNavTooltip($event,'数据与设置')"
          @mouseleave="hideNavTooltip"
          @focus="showNavTooltip($event,'数据与设置')"
          @blur="hideNavTooltip"
        >
          <Settings :size="19" /><span class="nav-label">数据与设置</span></button>
      </div>
    </aside>
    <button v-if="mobileMenu" class="sidebar-backdrop" aria-label="关闭导航遮罩" @click="mobileMenu=false" />
    <div class="app-body" :class="{'browser-page':page==='web'&&!stock,'ipo-page':page==='ipo'&&!stock}">
      <header class="topbar">
        <button
          class="icon-button mobile-toggle"
          aria-label="展开导航"
          aria-controls="workspace-navigation"
          :aria-expanded="mobileMenu"
          @click="mobileMenu = !mobileMenu"
        >
          <Menu />
        </button>
        <div class="breadcrumb">
          工作台 <span>/</span>
          {{
            stock
              ? "个股分析"
              : page === "settings"
                ? "数据与设置"
                : (nav.find((n) => n.id === page)?.name ?? "发现")
          }}
        </div>
        <div class="global-search">
          <Search :size="16" /><input
            id="global-search"
            v-model="q"
            @input="search"
            @keydown="searchKey"
            role="combobox"
            :aria-expanded="searchOpen"
            aria-controls="global-search-results"
            :aria-activedescendant="
              searchIndex >= 0 ? `search-result-${searchIndex}` : undefined
            "
            @focus="searchOpen = !!q"
            placeholder="代码 / 名称 / 拼音 / 首字母"
            autocomplete="off"
            aria-label="全局搜索股票"
          /><kbd>Ctrl K</kbd>
          <div
            v-if="searchOpen"
            id="global-search-results"
            class="search-results"
            role="listbox"
          >
            <p v-if="searching">正在搜索…</p>
            <template v-else
              ><button
                v-for="(s, i) in searchResults"
                :key="s.id"
                :id="`search-result-${i}`"
                role="option"
                :aria-selected="searchIndex === i"
                :class="{ highlighted: searchIndex === i }"
                @click="openStock(s.id)"
              >
                <span
                  ><strong>{{ s.name }}</strong
                  ><small>{{ s.code }} · {{ s.exchange }}</small></span
                ><strong :class="direction(s.quote?.change_pct)">{{
                  money(s.quote?.price)
                }}</strong>
              </button>
              <p v-if="!searchResults.length">
                {{ searchError || "没有匹配证券" }}
              </p></template
            >
          </div>
        </div>
        <div class="topbar-actions">
          <button
            class="icon-button notification-trigger"
            aria-label="打开通知中心"
            @click="notifications = true"
          >
            <Bell :size="19" /><span v-if="unread" class="unread-dot" /></button
          ><span class="local-avatar">王</span>
        </div>
      </header>
      <div v-if="!['home', 'watch', 'market', 'ipo', 'web'].includes(page) && !stock" class="data-ribbon compact-ribbon">
        <div class="flex">
          <span
            class="status-dot"
            :class="{ demo: state.meta.mode === 'DEMO' }"
          /><strong>{{ label(state.meta.mode) }}</strong
          ><span class="tiny muted">{{ date(state.meta.as_of) }}</span>
        </div>
        <button class="text-button tiny" @click="navigate('settings')">
          <Database :size="13" />数据设置
        </button>
      </div>
      <main>
        <div v-if="error" class="error-box">
          <strong>本地服务连接失败</strong>
          <p>{{ error }}</p>
          <button class="button small" @click="refresh">
            <RefreshCw :size="13" />重试连接
          </button>
        </div>
        <div v-if="loading && !state.dashboard" class="loading-region">
          正在连接本地工作台…
        </div>
        <template v-else
          ><StockView
            v-if="stock"
            :key="stock"
            :id="stock"
            @back="
              stock = '';
              navigate(page);
            "
            @rules="rules" /><HomeView
            v-else-if="page === 'home'"
            @open="openStock"
            @market="navigate('market')" /><DiscoverView
            v-else-if="page === 'discover'"
            @open="openStock"
            @rules="rules" /><MarketView
            v-else-if="page === 'market'"
            :key="page"
            @open="openStock"
            @rules="rules" /><WatchlistView
            v-else-if="page === 'watch'"
            @open="openStock"
            @market="navigate('market')" /><IpoView
            v-else-if="page === 'ipo'"
            @open="openStock" /><WebBrowserView
            v-else-if="page === 'web'"
            :key="webUrl"
            :initial-url="webUrl" /><SignalsView
            v-else-if="page === 'signals'"
            @open="openStock"
            @rules="rules" /><ValidationView
            v-else-if="page === 'validation'" /><TradingView
            v-else-if="page === 'trading'" /><SettingsView
            v-else-if="page === 'settings'"
        /></template>
      </main>
      <footer v-if="!['market','ipo','web'].includes(page) || stock" class="app-footer">
        <span>王炸</span
        ><span
          >所有时间均为北京时间 · 数据截至 {{ date(state.meta.as_of) }}</span
        >
      </footer>
    </div>
    <Teleport to="body"><div v-if="navTooltip" id="sidebar-tooltip" class="sidebar-tooltip" :class="{'native-tooltip-text':nativeTooltips}" role="tooltip" :style="{top:navTooltip.top+'px',left:navTooltip.left+'px'}">{{ navTooltip.label }}</div></Teleport>
    <RuleEditor v-if="rule" :security-id="ruleSecurity" @close="rule = false" />
    <div
      v-if="notifications"
      class="modal-scrim"
      @click.self="notifications = false"
    >
      <section
        class="drawer notification-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="notification-title"
      >
        <header class="drawer-header">
          <div>
            <div class="eyebrow">INBOX / 13</div>
            <h2 id="notification-title">
              通知中心 <span>{{ unread }}</span>
            </h2>
          </div>
          <button
            class="icon-button"
            aria-label="关闭通知"
            @click="notifications = false"
          >
            <X />
          </button>
        </header>
        <div class="drawer-content">
          <div
            v-for="n in state.notifications"
            :key="n.id"
            class="notification-card"
            :class="{ read: n.read }"
          >
            <span class="tiny muted">{{ date(n.created_at) }}</span>
            <h3>{{ n.title }}</h3>
            <p>{{ n.message }}</p>
            <div class="flex spread">
              <button
                v-if="n.signal_id"
                class="text-button tiny"
                @click="
                  navigate('signals');
                  notifications = false;
                "
              >
                查看原始信号 <ArrowUpRight :size="13" /></button
              ><button
                class="button small"
                :disabled="n.read"
                @click="readNotice(n.id)"
              >
                <Check :size="12" />{{ n.read ? "已读" : "标为已读" }}
              </button>
            </div>
          </div>
          <div v-if="!state.notifications.length" class="empty-state">
            <Bell :size="28" />
            <h3>暂无通知</h3>
            <p>信号通知会保留原始记录。外部推送与操作系统通知尚未开放。</p>
          </div>
        </div>
      </section>
    </div>
    <div v-if="toast" class="toast" role="status">
      <span>{{ toast }}</span
      ><button class="icon-button" aria-label="关闭提示" @click="toast = ''">
        <X :size="16" />
      </button>
    </div>
  </div>
</template>
