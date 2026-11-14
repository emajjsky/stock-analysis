import { describe, expect, it } from "vitest";
import {
  modeDescription,
  presentProvider,
  parseSecurityCodes,
} from "./dataSources";
import type { Provider } from "./types";

const provider = (overrides: Partial<Provider>): Provider => ({
  id: "xtdata",
  name: "行情源",
  status: "NOT_CONFIGURED",
  capabilities: [],
  source: "未接入",
  limitations: [],
  ...overrides,
});

describe("数据源状态文案", () => {
  it("研究资料源独立展示，不标成行情或 Agent 已消费", () => {
    expect(
      presentProvider(
        provider({
          id: "eastmoney-research",
          status: "SYNCED",
          data_mode: "RESEARCH",
        }),
      ),
    ).toMatchObject({
      mode: "研究资料源",
      connection: "已保存资料",
      tone: "history",
    });
    expect(
      presentProvider(
        provider({
          id: "eastmoney-research",
          status: "ERROR",
          data_mode: "RESEARCH",
          error: "资料源超时",
        }),
      ),
    ).toMatchObject({
      connection: "同步失败，保留旧资料",
      tone: "offline",
      detail: "资料源超时",
    });
  });
  it("未配置状态不会被显示成已连接或实时", () => {
    expect(presentProvider(provider({}))).toMatchObject({
      mode: "未接入",
      connection: "未配置",
      tone: "offline",
    });
  });

  it("区分已载入和未载入的合成演示数据", () => {
    expect(
      presentProvider(provider({ id: "synthetic-demo", status: "LOADED" })),
    ).toMatchObject({
      mode: "合成演示",
      connection: "已载入演示数据",
      tone: "demo",
    });
    expect(
      presentProvider(provider({ id: "synthetic-demo", status: "AVAILABLE" })),
    ).toMatchObject({ connection: "演示数据未载入", tone: "demo" });
  });

  it("区分本地 CSV 历史和有连接证据的实时源", () => {
    expect(
      presentProvider(provider({ id: "local-csv", status: "AVAILABLE" })),
    ).toMatchObject({
      mode: "历史导入",
      connection: "本地文件导入",
      tone: "history",
    });
    expect(
      presentProvider(
        provider({ status: "LIVE", data_mode: "LIVE", connected: true }),
      ),
    ).toMatchObject({
      mode: "公开行情快照",
      connection: "有缓存记录",
      tone: "live",
    });
  });

  it("旧版 LIVE 响应缺连接字段时明确显示未报告", () => {
    expect(
      presentProvider(provider({ status: "LIVE", data_mode: "LIVE" })),
    ).toMatchObject({ connection: "连接状态未报告", tone: "unknown" });
  });

  it("总览只把服务端 LIVE 模式标记为实时", () => {
    expect(modeDescription("IMPORTED").label).toBe("历史导入");
    expect(modeDescription("DEMO").label).toBe("合成演示");
    expect(modeDescription("MIXED").label).toBe("混合来源");
    expect(modeDescription("EMPTY").label).toBe("尚无行情");
    expect(modeDescription("LIVE").label).toBe("公开行情快照");
    expect(modeDescription("SYNTHETIC").label).toBe("合成演示");
    expect(modeDescription("HISTORICAL").label).toBe("历史导入");
    expect(modeDescription("LIVE_HISTORY").label).toBe("真实历史日线");
  });

  it("外部数据失败保留失败原因，不以演示数据兜底", () => {
    expect(
      presentProvider(
        provider({
          id: "tencent",
          status: "UNAVAILABLE",
          data_mode: "UNAVAILABLE",
          connected: false,
          error: "上游超时",
        }),
      ),
    ).toMatchObject({
      mode: "未接入",
      connection: "不可用",
      tone: "offline",
      detail: "上游超时",
    });
  });

  it("真实快照保留源时间和供应商限制", () => {
    expect(
      presentProvider(
        provider({
          id: "tencent",
          status: "AVAILABLE",
          data_mode: "LIVE",
          connected: true,
          latest_data_at: "2026-10-27T07:00:00Z",
          warning: "仅手动同步，非持续订阅",
        }),
      ),
    ).toMatchObject({
      mode: "公开行情快照",
      updatedAt: "2026-10-27T07:00:00Z",
      detail: "仅手动同步，非持续订阅",
    });
  });

  it("手动快照不会显示成持续连接，失败时保留缓存语义", () => {
    expect(
      presentProvider(
        provider({
          id: "tencent",
          status: "SYNCED",
          data_mode: "LIVE",
          connected: true,
        }),
      ),
    ).toMatchObject({ connection: "已同步缓存", tone: "live" });
    expect(
      presentProvider(
        provider({
          id: "tencent",
          status: "ERROR",
          data_mode: "LIVE",
          connected: true,
          error: "上游超时",
        }),
      ),
    ).toMatchObject({
      connection: "同步失败（保留缓存）",
      tone: "offline",
      detail: "上游超时",
    });
  });
});

describe("真实行情代码输入", () => {
  it("保留前导零，接受六位代码和真实来源标识并去重", () => {
    expect(
      parseSecurityCodes("000001, SH.600519；LIVE.SZ.000001\n300750"),
    ).toEqual({
      ids: ["SZ.000001", "SH.600519", "SZ.300750"],
      errors: [],
    });
  });
  it("拒绝错误市场前缀、非沪深股票和不完整输入", () => {
    const result = parseSecurityCodes("SH.000001 510300 123 bad");
    expect(result.ids).toEqual([]);
    expect(result.errors).toHaveLength(4);
  });
  it("支持 302 创业板代码且仍核验市场前缀", () => {
    expect(parseSecurityCodes("302132 LIVE.SZ.302132")).toEqual({
      ids: ["SZ.302132"],
      errors: [],
    });
    expect(parseSecurityCodes("SH.302132").errors).toHaveLength(1);
  });
  it("空输入不生成默认代码或同步对象", () => {
    expect(parseSecurityCodes("  ")).toEqual({ ids: [], errors: [] });
  });
});
