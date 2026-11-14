export interface BrowserTab { id: string; url: string; title: string; loading: boolean; error: string | null; back: boolean; forward: boolean }
export interface BrowserState { active?: string; tabs: BrowserTab[] }
export interface DesktopBrowser {
  nativeTooltips?: boolean;
  command(command: string, args?: Record<string, unknown>): Promise<BrowserState>;
  onState(callback: (state: BrowserState) => void): () => void;
}
declare global { interface Window { wangzhaBrowser?: DesktopBrowser } }
export const browserPresets = [
  { label: '同花顺行情', url: 'https://q.10jqka.com.cn/' },
  { label: '同花顺新股', url: 'https://data.10jqka.com.cn/ipo/xgsgyzq/' },
  { label: '东方财富新股', url: 'https://data.eastmoney.com/xg/' },
];
export function openWeb(url: string) {
  window.dispatchEvent(new CustomEvent('wangzha-open-browser', { detail: { url } }));
}
