import { describe, expect, it } from "vitest";
import {
  bindingPresentation,
  evidenceReason,
  modelRequestLabel,
  reviewManifest,
  reviewErrorLabel,
  safeResearchUrl,
} from "./reviewEvidence";
import type { Review, ResearchEvidenceManifest } from "./types";

const review = { mode: "UNAVAILABLE" } as Review;
const evidence = {
  id: "company-1",
  section: "company",
  included: false,
  exclusion_reason: "字段校验未通过",
} as ResearchEvidenceManifest;

describe("Agent 研究证据展示", () => {
  it("将复核错误码映射为安全的中文状态，不暴露原始异常", () => {
    expect(reviewErrorLabel("INVALID_CITATION")).toContain("证据校验");
    expect(reviewErrorLabel("VENDOR_SECRET_ERROR")).toContain("保持等待");
    expect(reviewErrorLabel(null)).toBeNull();
  });
  it("旧记录缺绑定状态需重新复核，明确空态", () => {
    expect(bindingPresentation(review)).toMatchObject({
      status: "unbound",
      requiresReview: true,
    });
    expect(reviewManifest(review)).toEqual([]);
    expect(
      bindingPresentation({ ...review, research_binding_status: "STALE" })
        .requiresReview,
    ).toBe(true);
    expect(
      bindingPresentation({ ...review, research_binding_status: "CURRENT" })
        .requiresReview,
    ).toBe(false);
  });
  it("请求尝试不是成功或模型消费，规则演示始终非 AI", () => {
    expect(
      modelRequestLabel({ ...review, model_request_attempted: true }),
    ).toContain("不代表模型调用成功");
    expect(
      modelRequestLabel({ ...review, model_request_attempted: false }),
    ).toContain("未发起模型请求");
    expect(
      modelRequestLabel({
        ...review,
        mode: "RULE_DEMO",
        model_request_attempted: true,
      }),
    ).toContain("非 AI");
    expect(modelRequestLabel(review)).toContain("旧记录未报告");
  });
  it("排除原因原样展示，不将全部排除说成未来资料", () => {
    expect(evidenceReason(evidence)).toBe("字段校验未通过");
    expect(
      evidenceReason({ ...evidence, exclusion_reason: "获知时间晚于信号" }),
    ).toBe("获知时间晚于信号");
    expect(evidenceReason({ ...evidence, exclusion_reason: null })).toBe(
      "后端未提供排除原因",
    );
  });
  it("优先使用后端清单，不从空清单猜测旧快照", () => {
    const context = {
      as_of: "2026-10-28T00:00:00Z",
      evidence: [evidence],
      company: null,
      financials: [],
      announcements: [],
    };
    expect(
      reviewManifest({ ...review, research_context_snapshot: context }),
    ).toEqual([evidence]);
    expect(
      reviewManifest({
        ...review,
        research_evidence_snapshot: [],
        research_context_snapshot: context,
      }),
    ).toEqual([]);
  });
  it("来源链接仅允许 HTTPS 东方财富及子域，无凭据或非标准端口", () => {
    expect(safeResearchUrl("https://data.eastmoney.com/a")).toBe(
      "https://data.eastmoney.com/a",
    );
    expect(safeResearchUrl("https://eastmoney.com/a")).toBe(
      "https://eastmoney.com/a",
    );
    for (const value of [
      "http://data.eastmoney.com/a",
      "javascript:alert(1)",
      "https://eastmoney.com.evil.test/a",
      "https://noteastmoney.com/a",
      "https://eastmoney.com@evil.test/a",
      "https://user:secret@data.eastmoney.com/a",
      "https://data.eastmoney.com:8080/a",
      null,
    ])
      expect(safeResearchUrl(value)).toBeNull();
  });
});
