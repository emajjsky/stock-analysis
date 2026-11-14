export interface NewsItem {
  id: string;
  kind: 'news' | 'announcement';
  title: string;
  summary: string;
  published_at: string;
  publication_precision: 'TIME' | 'DATE';
  source: string;
  url: string | null;
  securities: { id: string; code: string; name: string }[];
}
export interface NewsFeed {
  items: NewsItem[];
  updated_at: string | null;
  refreshing: boolean;
  enabled: boolean;
  error: string | null;
  stale: boolean;
  status: string;
  watch_count: number;
  watch_limit: number;
}
export function unseenCount(current: Pick<NewsItem, 'id'>[], incoming: Pick<NewsItem, 'id'>[]) {
  const seen = new Set(current.map(item => item.id));
  return incoming.filter(item => !seen.has(item.id)).length;
}
export function articleUrl(url: string | null): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'https:' && !parsed.username && !parsed.password &&
        ['finance.sina.com.cn', 'data.eastmoney.com'].includes(parsed.hostname) && !parsed.port)
      return url;
  } catch { /* 无效来源链接不渲染 */ }
  return undefined;
}
