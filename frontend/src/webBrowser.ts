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
  { label: '东方财富行情', url: 'https://quote.eastmoney.com/center/' },
  { label: '新浪财经', url: 'https://finance.sina.com.cn/stock/' },
  { label: '巨潮资讯', url: 'https://www.cninfo.com.cn/' },
];
export function openWeb(url: string) {
  window.dispatchEvent(new CustomEvent('wangzha-open-browser', { detail: { url } }));
}
