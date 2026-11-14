import { beforeEach, describe, expect, it, vi } from "vitest";

describe("多算法选股请求", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("把选中的第二套算法 ID 原样提交，不落回服务端默认算法", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        requests.push({ url, init });
        return {
          ok: true,
          json: async () => ({ data: [], meta: { request_id: "selection-2" } }),
        };
      }),
    );
    const { runSelection } = await import("./recommendations");
    await runSelection("second-selection-v1");
    const request = requests.find((r) =>
      r.url.endsWith("/recommendations/run"),
    );
    expect(request?.init?.method).toBe("POST");
    expect(JSON.parse(String(request?.init?.body))).toEqual({
      algorithm_id: "second-selection-v1",
    });
  });

  it("未选择算法时不发送请求", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const { runSelection } = await import("./recommendations");
    expect(() => runSelection("")).toThrow("请先选择选股算法");
    expect(fetch).not.toHaveBeenCalled();
  });
});
