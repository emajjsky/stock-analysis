export function money(value: unknown, digits = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "—";
}
export function date(value?: string | null) {
  if (!value) return "尚无数据";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(d);
}
export function direction(value: unknown) {
  return Number(value) > 0 ? "up" : Number(value) < 0 ? "down" : "";
}
export const kindName: Record<string, string> = {
  DEMO_SYNTHETIC: "合成演示证券",
  IMPORTED_UNVERIFIED: "导入证券 · 状态未核验",
  LIVE_UNVERIFIED: "行情证券 · 状态未核验",
  NORMAL: "正常",
  BUY: "买入观察",
  SELL: "退出观察",
  T_BUY: "做T买入",
  T_SELL: "做T卖出",
  WATCH: "关注",
  CONFIRMED: "已确认",
  EXPIRED: "已过期",
  INVALIDATED: "已失效",
  SUPPORT: "支持",
  CONDITIONAL: "附条件支持",
  WAIT: "等待",
  REJECT: "反对",
  OFF: "关闭",
  EXPLAIN: "仅解释",
  FILTER: "参与过滤",
  COMPARABLE: "可比较",
  MISSING_DATA: "缺少数据",
  DIVERGED_CONSTRAINTS: "约束差异，不可比",
  FILLED: "已成交",
  REJECTED: "已拒绝",
  NOT_CONFIGURED: "未配置",
  ACTIVE: "可用",
  READY: "可用",
  RESEARCH: "研究中",
  CATALOG: "证券资料",
  EMPTY: "空库",
  DEMO: "合成演示",
  IMPORTED: "历史导入",
  LIVE: "公开行情快照",
  LIVE_HISTORY: "真实历史日线",
  MIXED: "混合来源",
};
export const label = (s: string) => kindName[s] ?? s;
export function safeUrl(value: string | null) {
  if (!value) return null;
  try {
    const u = new URL(value);
    return ["https:", "http:"].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
