<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import { ArrowLeft, ArrowRight, RefreshCw, Plus, X, ExternalLink, Globe, Copy } from 'lucide-vue-next';
import { browserPresets, type BrowserState } from '../webBrowser';
const props = defineProps<{ initialUrl?: string }>();
const bridge = window.wangzhaBrowser;
const state = ref<BrowserState>({ tabs: [] });
const active = computed(() => state.value.tabs.find(t => t.id === state.value.active));
const address = ref(props.initialUrl || browserPresets[0].url);
const addressFocused = ref(false);
const area = ref<HTMLElement>();
const error = ref('');
const preview = ref(false);
const copied = ref(false);
let remove: (() => void) | undefined, observer: ResizeObserver | undefined;
let disposed = false;
async function command(name: string, args?: Record<string, unknown>) {
  error.value = '';
  try {
    if (bridge) state.value = await bridge.command(name, args);
    address.value = active.value?.url || address.value;
  } catch (e) { error.value = e instanceof Error ? e.message : '网页操作失败'; }
}
async function open(url = browserPresets[0].url) {
  if (bridge) await command('open', { url });
  else { address.value = url; preview.value = true; }
}
function viewport() {
  const r = area.value?.getBoundingClientRect();
  if (bridge && r && !disposed) void bridge.command('viewport', { visible: !document.querySelector('.modal-scrim,.sidebar-backdrop'), x: r.x, y: r.y, width: r.width, height: r.height });
}
function navigate() {
  let url = address.value.trim();
  if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error();
    if (bridge) void command('navigate', { url });
    else { address.value = parsed.href; preview.value = true; }
  } catch { error.value = '请输入有效的网页地址'; }
}
async function copyLaunch() {
  try { await navigator.clipboard.writeText('cd desktop\nnpm start'); copied.value = true; }
  catch { error.value = '请在项目目录进入 desktop 文件夹后执行 npm start'; }
}
onMounted(async () => {
  if (bridge) {
    remove = bridge.onState(s => { state.value = s; if(!addressFocused.value)address.value = active.value?.url || address.value; });
    await command('state');
    const existing = props.initialUrl && state.value.tabs.find(t => t.url === props.initialUrl);
    if (existing) await command('active', { id: existing.id });
    else if (props.initialUrl || !state.value.tabs.length) await open(props.initialUrl);
    await nextTick();
    observer = new ResizeObserver(viewport);
    if (area.value) observer.observe(area.value);
    window.addEventListener('resize', viewport);
    window.addEventListener('scroll', viewport, true);
    window.addEventListener('wangzha-browser-layout', viewport);
    viewport();
  }
});
onUnmounted(() => {
  disposed = true; remove?.(); observer?.disconnect();
  window.removeEventListener('resize', viewport); window.removeEventListener('scroll', viewport, true);
  window.removeEventListener('wangzha-browser-layout', viewport);
  if (bridge) void bridge.command('viewport', { visible: false });
});
</script>
<template>
  <section class="web-workspace" aria-label="多标签网页行情">
    <div class="web-tabs" role="tablist" aria-label="网页标签">
      <div v-for="t in state.tabs" :key="t.id" class="web-tab" :class="{active:t.id===state.active}">
        <button role="tab" :aria-selected="t.id===state.active" :title="t.title + '\n' + t.url" @click="command('active',{id:t.id})"><Globe :size="14"/><span>{{ t.loading ? '加载中…' : t.title || '网页' }}</span></button>
        <button class="web-close" :aria-label="`关闭${t.title}标签`" @click="command('close',{id:t.id})"><X :size="14"/></button>
      </div>
      <button class="icon-button" aria-label="新建网页标签" title="新建同花顺标签" @click="open()"><Plus :size="18"/></button>
      <span v-if="!bridge" class="web-preview-label">浏览器模式</span>
    </div>
    <form class="web-address-row" @submit.prevent="navigate">
      <button type="button" class="icon-button" aria-label="网页后退" :disabled="!active?.back" @click="command('back')"><ArrowLeft :size="18"/></button>
      <button type="button" class="icon-button" aria-label="网页前进" :disabled="!active?.forward" @click="command('forward')"><ArrowRight :size="18"/></button>
      <button type="button" class="icon-button" aria-label="刷新网页" :disabled="!bridge && !preview" @click="bridge ? command('reload') : preview=false"><RefreshCw :size="17" :class="{spinning:active?.loading}"/></button>
      <label class="web-address"><Globe :size="15"/><input v-model="address" @focus="addressFocused=true" @blur="addressFocused=false" aria-label="网页地址" spellcheck="false"/><button class="text-button" type="submit">前往</button></label>
      <a :href="active?.url || address" target="_blank" rel="noopener noreferrer" class="icon-button" aria-label="打开原站" title="打开原站"><ExternalLink :size="17"/></a>
    </form>
    <nav class="web-bookmarks" aria-label="行情预设网址"><button v-for="p in browserPresets" :key="p.url" @click="open(p.url)">{{ p.label }}</button><span v-if="bridge">新开网页保留在内部标签页</span></nav>
    <div v-if="error || active?.error" class="error-box" role="alert">{{ error || active?.error }}</div>
    <div ref="area" class="web-viewport">
      <div v-if="!bridge && !preview" class="web-start">
        <Globe :size="40"/><h2>同花顺网页行情</h2><p>桌面版支持内部多标签、前进后退，并保留原站登录。</p>
        <div class="flex"><button class="button primary" @click="preview=true">预览网页</button><a class="button" :href="address" target="_blank" rel="noopener noreferrer">打开原站 <ExternalLink :size="15"/></a></div>
        <div class="web-launch"><strong>启动桌面版</strong><code>cd desktop<br/>npm start</code><button class="text-button" @click="copyLaunch"><Copy :size="14"/>{{copied ? '已复制' : '复制命令'}}</button></div>
        <small>网页预览受原站嵌入策略限制；预览中的新窗口由浏览器管理。</small>
      </div>
      <template v-else-if="!bridge"><div class="web-preview-note">预览中的新窗口由浏览器管理；完整多标签请使用桌面版。若空白可点击右上角打开原站。</div><iframe :src="address" title="同花顺网页预览" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox" referrerpolicy="strict-origin-when-cross-origin"/></template>
      <div v-else-if="!state.tabs.length" class="web-start"><h2>打开一个行情网页</h2><button class="button primary" @click="open()">打开同花顺</button></div>
    </div>
  </section>
</template>
<style>
.web-workspace .web-bookmarks{flex-direction:row}
.web-workspace .web-bookmarks>button{min-height:26px;box-shadow:none;padding:2px 4px}
.web-workspace{display:flex;flex-direction:column;height:calc(100dvh - 110px);min-height:540px;border:1px solid var(--line);background:var(--surface);overflow:hidden;border-radius:8px}
.web-tabs{display:flex;align-items:center;gap:5px;min-height:40px;padding:5px 8px 0;background:#eee9dc;overflow:auto}.web-tab{display:flex;align-items:center;border-radius:6px 6px 0 0;flex:0 1 220px;min-width:125px}.web-tab.active{background:var(--surface)}.web-tab button{display:flex;align-items:center;gap:7px;border:0;background:transparent;padding:8px;min-width:0}.web-tab button:first-child{flex:1}.web-tab span{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.web-close{flex:none}.web-address-row{display:flex;align-items:center;gap:5px;padding:7px 10px}.web-address{display:flex;align-items:center;gap:8px;background:var(--paper);border:1px solid var(--line);border-radius:5px;flex:1;padding:0 10px}.web-address input{flex:1;border:0;background:transparent;padding:6px 0}.web-bookmarks{display:flex;gap:7px;padding:0 12px 8px;border-bottom:1px solid var(--line);align-items:center}.web-bookmarks button{border:0;background:transparent;font-size:13px;color:var(--blue)}.web-bookmarks>span,.web-preview-label{font-size:12px;color:var(--muted);margin-left:auto}.web-viewport{flex:1;position:relative;min-height:0;overflow:hidden}.web-viewport iframe{border:0;width:100%;height:calc(100% - 30px)}.web-preview-note{font-size:12px;padding:3px 10px;background:#fff2c5;height:30px}.web-start{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:12px;text-align:center;padding:24px}.web-start>svg{color:var(--blue)}.web-start p{color:var(--muted)}.web-launch{display:flex;align-items:center;gap:22px;border-top:1px solid var(--line);padding:20px;margin-top:15px;text-align:left}.web-launch code{font-size:14px;line-height:1.8}.web-start>small{font-size:12px;color:var(--muted)}
</style>
