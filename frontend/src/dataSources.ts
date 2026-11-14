import type { Provider } from "./types";

export type ProviderPresentation = {
  mode: string;
  connection: string;
  tone: "live" | "history" | "demo" | "offline" | "unknown";
  updatedAt: string | null;
  detail: string;
};

export function presentProvider(provider: Provider): ProviderPresentation {
  const mode = (provider.data_mode ?? "").toUpperCase();
  const status = provider.status.toUpperCase();
  const demo =
    mode === "DEMO" || mode === "SYNTHETIC" || provider.id === "synthetic-demo";
  const unconfigured =
    mode === "UNAVAILABLE" ||
    mode === "NOT_CONFIGURED" ||
    status === "NOT_CONFIGURED" ||
    status === "UNAVAILABLE";
  const live = mode === "LIVE" || status === "LIVE";
  const historical = mode === "HISTORICAL" || provider.id === "local-csv";
  const research = mode === "RESEARCH" || provider.id === "eastmoney-research";
  const updatedAt = provider.latest_data_at ?? provider.last_updated_at ?? null;

  if (demo) {
    return {
      mode: "合成演示",
      connection: status === "LOADED" ? "已载入演示数据" : "演示数据未载入",
      tone: "demo",
      updatedAt,
      detail: "合成样本，不是市场行情；不会标记为实时数据。",
    };
  }
  if (unconfigured) {
    return {
      mode: "未接入",
      connection:
        status === "NOT_CONFIGURED" || mode === "NOT_CONFIGURED"
          ? "未配置"
          : "不可用",
      tone: "offline",
      updatedAt,
      detail:
        provider.error ??
        provider.warning ??
        "数据连接尚未配置，不会发起外部数据请求。",
    };
  }
  if (live) {
    const connection =
      status === "ERROR"
        ? "同步失败（保留缓存）"
        : status === "SYNCED"
          ? "已同步缓存"
          : status === "PARTIAL"
            ? "部分同步"
            : status === "AVAILABLE" && provider.connected === false
              ? "尚未同步"
              : provider.connected === true
                ? "有缓存记录"
                : provider.connected === false
                  ? "未连接"
                  : "连接状态未报告";
    return {
      mode: "公开行情快照",
      connection,
      tone:
        status === "ERROR"
          ? "offline"
          : provider.connected === true
            ? "live"
            : "unknown",
      updatedAt,
      detail:
        provider.error ??
        provider.warning ??
        "真实行情仅在手动同步后更新，不代表持续实时订阅。",
    };
  }
  if (historical) {
    return {
      mode: "历史导入",
      connection: "本地文件导入",
      tone: "history",
      updatedAt,
      detail: "用户导入的历史行情，不代表实时行情。",
    };
  }
  if (research) {
    return {
      mode: "研究资料源",
      connection:
        status === "SYNCED"
          ? "已保存资料"
          : status === "PARTIAL"
            ? "部分资料"
            : status === "ERROR"
              ? "同步失败，保留旧资料"
              : "可手动同步",
      tone: status === "ERROR" ? "offline" : "history",
      updatedAt,
      detail:
        provider.error ??
        provider.warning ??
        "公司资料、财务摘要和公告标题；不代表 Agent 已消费。",
    };
  }
  return {
    mode: "服务端状态：" + provider.status,
    connection:
      provider.connected === true
        ? "已连接"
        : provider.connected === false
          ? "未连接"
          : "连接状态未报告",
    tone: "unknown",
    updatedAt,
    detail: provider.error ?? provider.warning ?? provider.source,
  };
}

export function modeDescription(mode: string) {
  switch (mode.toUpperCase()) {
    case "LIVE":
      return { label: "公开行情快照", tone: "live" as const };
    case "LIVE_HISTORY":
      return { label: "真实历史日线", tone: "history" as const };
    case "IMPORTED":
      return { label: "历史导入", tone: "history" as const };
    case "DEMO":
      return { label: "合成演示", tone: "demo" as const };
    case "MIXED":
      return { label: "混合来源", tone: "unknown" as const };
    case "SYNTHETIC":
      return { label: "合成演示", tone: "demo" as const };
    case "HISTORICAL":
      return { label: "历史导入", tone: "history" as const };
    case "UNAVAILABLE":
      return { label: "尚无行情", tone: "offline" as const };
    case "RESEARCH":
      return { label: "研究资料源", tone: "history" as const };
    default:
      return { label: "尚无行情", tone: "offline" as const };
  }
}

export function parseSecurityCodes(input: string) {
  const tokens = input
    .toUpperCase()
    .split(/[\s,，;；]+/)
    .filter(Boolean);
  const ids: string[] = [];
  const errors: string[] = [];
  for (const token of tokens) {
    const normalized = token.replace(/^LIVE\./, "");
    const match = /^(?:(SH|SZ)\.)?(\d{6})$/.exec(normalized);
    if (!match) {
      errors.push(`${token}：请输入六位沪深股票代码`);
      continue;
    }
    const [, exchange, code] = match;
    const market = /^(600|601|603|605|688)/.test(code)
      ? "SH"
      : /^(000|001|002|003|300|301|302)/.test(code)
        ? "SZ"
        : null;
    if (!market || (exchange && exchange !== market)) {
      errors.push(`${token}：不是支持的沪深 A 股代码或市场前缀不匹配`);
      continue;
    }
    ids.push(`${market}.${code}`);
  }
  return { ids: [...new Set(ids)], errors };
}
