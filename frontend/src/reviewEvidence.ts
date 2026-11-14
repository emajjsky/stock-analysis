import type { Review, ResearchEvidenceManifest } from "./types";

export function reviewManifest(review: Review): ResearchEvidenceManifest[] {
  return (
    review.research_evidence_snapshot ??
    review.research_context_snapshot?.evidence ??
    []
  );
}

export function bindingPresentation(review: Review) {
  const status = review.research_binding_status;
  return {
    status:
      status === "CURRENT"
        ? "current"
        : status === "STALE"
          ? "stale"
          : "unbound",
    label:
      review.research_binding_label ||
      (status === "CURRENT"
        ? "研究资料时点一致"
        : status === "STALE"
          ? "研究资料绑定已变化"
          : "研究资料未绑定"),
    requiresReview: status !== "CURRENT",
  };
}

export function modelRequestLabel(review: Review) {
  if (review.mode === "RULE_DEMO")
    return "规则演示，非 AI；绑定快照不代表模型消费。";
  if (review.model_request_attempted === true)
    return "已发起模型请求；不代表模型调用成功或已采用这些资料。";
  if (review.model_request_attempted === false)
    return "未发起模型请求；仅保存研究资料绑定快照。";
  return "旧记录未报告模型请求状态，不能确认模型是否接收研究资料。";
}

export function reviewErrorLabel(code: string | null | undefined) {
  const labels: Record<string, string> = {
    INPUT_TOO_LARGE: "复核上下文超过模型输入上限",
    OUTPUT_TOO_LARGE: "模型输出超过协议上限",
    INVALID_INPUT: "复核上下文无法序列化",
    INVALID_RESPONSE: "模型输出未通过结构校验",
    INVALID_CITATION: "模型引用未通过证据校验",
    REQUEST_FAILED: "模型请求失败或超时",
    RESEARCH_CHANGED: "复核期间研究资料发生变化",
    REVIEW_DISABLED: "复核完成前监测或 Agent 已关闭",
  };
  return code ? labels[code] || "复核未完成，结果保持等待" : null;
}

export function evidenceReason(item: ResearchEvidenceManifest) {
  return item.included
    ? "纳入本次绑定上下文"
    : item.exclusion_reason || "后端未提供排除原因";
}

export function safeResearchUrl(value: string | null | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      (url.port && url.port !== "443")
    )
      return null;
    return host === "eastmoney.com" || host.endsWith(".eastmoney.com")
      ? url.href
      : null;
  } catch {
    return null;
  }
}
