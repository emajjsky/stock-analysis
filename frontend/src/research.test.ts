import { describe, expect, it } from "vitest";
import {
  publication,
  researchAccess,
  researchTime,
  supportsTencent,
} from "./research";
import type { Profile, Provider } from "./types";

const profile: Profile = {
  security_id: "LIVE.SH.600519",
  business: null,
  facts: [],
  events: [],
  limitations: [],
};
describe("研究资料边界", () => {
  it("旧后端与演示证券禁同步，切换证券时旧状态不能放行", () => {
    expect(researchAccess(profile, profile.security_id)).toMatchObject({
      enabled: false,
    });
    expect(researchAccess(profile, "DEMO.000001").enabled).toBe(false);
    const supported = {
      ...profile,
      research: {
        supported: true,
        provider_id: "eastmoney-research",
        status: "AVAILABLE",
        last_synced_at: null,
        error: null,
        sections: [],
        limitations: [],
      },
    };
    expect(researchAccess(supported, profile.security_id).enabled).toBe(true);
    expect(researchAccess(supported, "LIVE.SZ.000001").enabled).toBe(false);
  });
  it("只有日期时不捏造午夜披露时点，未知精度不伪装已知", () => {
    expect(publication("2026-10-27T00:00:00Z", "DATE")).toBe(
      "2026-10-27（仅日期）",
    );
    expect(publication("2026-08-14T16:00:00Z", "DATE")).toBe(
      "2026-08-15（仅日期）",
    );
    expect(publication("2026-08-15", "DATE")).toBe("2026-08-15（仅日期）");
    expect(publication(null, "UNKNOWN")).toBe("披露时间未提供");
    expect(publication("2026-10-27", undefined)).toContain("精度未报告");
    expect(publication("2026-10-27T01:00:00Z", "TIME")).toContain("09:00:00");
  });
  it("实际抓取时间包含年份并显示北京时间，缺失不补时间", () => {
    expect(researchTime("2026-10-27T01:00:00Z")).toContain("2026");
    expect(researchTime("2026-10-27T01:00:00Z")).toContain("09:00:00");
    expect(researchTime(null)).toBe("未提供");
  });
  it("后端未报告腾讯 Provider 时不开放新行情接口", () => {
    expect(supportsTencent([])).toBe(false);
    expect(supportsTencent([{ id: "local-csv" } as Provider])).toBe(false);
    expect(supportsTencent([{ id: "tencent" } as Provider])).toBe(true);
  });
});
