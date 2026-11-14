import type { Profile, Provider } from "./types";

export const researchSections = ["company", "financials", "announcements"];
export const sectionName = (value: string) =>
  ({ company: "公司概况", financials: "财务摘要", announcements: "公告标题" })[
    value
  ] ?? value;
export function researchAccess(
  profile: Profile | undefined,
  securityId: string,
) {
  if (securityId.startsWith("DEMO."))
    return { enabled: false, reason: "演示证券不支持真实研究资料同步。" };
  if (!profile || profile.security_id !== securityId)
    return { enabled: false, reason: "等待当前证券的资料状态。" };
  if (!profile.research)
    return {
      enabled: false,
      reason: "当前后端版本尚未提供研究接口，请重启更新后的后端。",
    };
  if (!profile.research.supported)
    return { enabled: false, reason: "该证券暂不支持此研究数据源。" };
  return {
    enabled: true,
    reason: "按访问时效自动补齐公司概况、财务摘要及公告标题，也可手动重试。",
  };
}
export function researchStatus(value?: string) {
  return (
    {
      AVAILABLE: "可手动同步",
      SYNCED: "已保存资料",
      PARTIAL: "部分同步",
      ERROR: "同步失败，保留旧资料",
      SUCCEEDED: "同步完成",
      FAILED: "同步失败",
    }[value ?? ""] ?? "状态待加载"
  );
}
export function researchTime(value?: string | null) {
  if (!value) return "未提供";
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return "时间格式未知";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(parsed);
}
export function publication(
  value: string | null | undefined,
  precision?: string,
) {
  if (!value || precision === "UNKNOWN") return "披露时间未提供";
  if (precision === "DATE") {
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value + "（仅日期）";
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return "披露日期格式未知";
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(parsed);
    const part = (type: string) =>
      parts.find((item) => item.type === type)?.value;
    return (
      part("year") + "-" + part("month") + "-" + part("day") + "（仅日期）"
    );
  }
  if (precision === "TIME") return researchTime(value) + "（精确到时间）";
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? value + "（精度未报告）"
    : researchTime(value) + "（精度未报告）";
}
export function supportsTencent(providers: Provider[]) {
  return providers.some((provider) => provider.id === "tencent");
}
