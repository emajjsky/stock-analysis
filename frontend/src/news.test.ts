import { describe, expect, it } from 'vitest';
import { articleUrl, unseenCount, type NewsItem } from './news';
describe('资讯阅读状态和原文链接', () => {
  it('只计算未读新ID，不把重新排序和重复轮询当新消息', () => {
    const a = [{ id: '1' }, { id: '2' }] as NewsItem[];
    expect(unseenCount(a, [{ id: '2' }, { id: '1' }] as NewsItem[])).toBe(0);
    expect(unseenCount(a, [{ id: '3' }, ...a])).toBe(1);
    expect(unseenCount(a, a)).toBe(0);
  });
  it('只允许固定资讯源的HTTPS原文，拒绝脚本和伪装域名', () => {
    expect(articleUrl('https://finance.sina.com.cn/7x24/test.shtml')).toContain('sina.com.cn');
    expect(articleUrl('https://data.eastmoney.com/notices/detail/600519/AN123.html')).toContain('eastmoney.com');
    for (const url of [null, 'javascript:alert(1)', 'https://evil.com/a', 'https://finance.sina.com.cn.evil.com/a', 'https://a:b@finance.sina.com.cn/a'])
      expect(articleUrl(url)).toBeUndefined();
  });
});
