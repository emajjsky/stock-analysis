import { beforeEach, describe, expect, it, vi } from "vitest";
describe("本机会话 API", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });
  it("并发调用先建立一次会话，写入使用同源凭据和 JSON", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        return {
          ok: true,
          json: async () => ({ data: { ok: true }, meta: { request_id: "r" } }),
        };
      }),
    );
    const { api, post } = await import("./api");
    await Promise.all([
      api("/securities"),
      post("/watchlists", { security_id: "SZ.000001" }),
    ]);
    expect(calls.filter((c) => c.url.endsWith("/session"))).toHaveLength(1);
    expect(calls[0].url).toBe("/api/v1/session");
    const write = calls.find((c) => c.url.endsWith("/watchlists"))!;
    expect(write.init?.credentials).toBe("same-origin");
    expect(write.init?.body).toContain("SZ.000001");
    expect(write.init?.headers).toMatchObject({
      "Content-Type": "application/json",
    });
  });
  it("保留服务端中文拒绝原因和请求标识，不返回假成功", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/session")
          ? { ok: true, json: async () => ({ data: { authenticated: true } }) }
          : {
              ok: false,
              json: async () => ({
                error: { code: "T_PLUS_ONE", message_zh: "当日买入不可卖" },
                meta: { request_id: "test-1" },
              }),
            },
      ),
    );
    const { post } = await import("./api");
    await expect(post("/sim/accounts/a/orders", {})).rejects.toMatchObject({
      message: "当日买入不可卖",
      code: "T_PLUS_ONE",
      requestId: "test-1",
    });
  });
  it('服务重启后并发401共享一次续会话，仅重放执行前被拒绝的请求', async()=>{
    let sessions=0, successfulWrites=0;
    const attempts=new Map<string,number>();
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
      if(url.endsWith('/session')) { sessions++; return {ok:true,json:async()=>({data:{authenticated:true}})}; }
      const count=(attempts.get(url) ?? 0)+1; attempts.set(url,count);
      if(count===1) return {ok:false,status:401,json:async()=>({error:{code:'SESSION_REQUIRED',message_zh:'会话已失效'}})};
      successfulWrites++;
      return {ok:true,json:async()=>({data:{ok:true}})};
    }));
    const {post}=await import('./api');
    await Promise.all([post('/securities/a/activate'),post('/securities/b/activate')]);
    expect(sessions).toBe(2);
    expect(successfulWrites).toBe(2);
    expect([...attempts.values()]).toEqual([2,2]);
  });
  it('续会话仍失败时停止，不无限重试',async()=>{
    let writes=0;
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
      if(url.endsWith('/session')) return {ok:true,json:async()=>({data:{authenticated:true}})};
      writes++;
      return {ok:false,status:401,json:async()=>({error:{code:'SESSION_REQUIRED',message_zh:'会话失效'}})};
    }));
    const {post}=await import('./api');
    await expect(post('/securities/a/activate')).rejects.toMatchObject({code:'SESSION_REQUIRED'});
    expect(writes).toBe(2);
  });
  it('网络超时或业务401均不重放',async()=>{
    let writes=0;
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
      if(url.endsWith('/session')) return {ok:true,json:async()=>({data:{authenticated:true}})};
      writes++;
      if(writes===1) throw new TypeError('Failed to fetch');
      return {ok:false,status:401,json:async()=>({error:{code:'OTHER_AUTH',message_zh:'业务拒绝'}})};
    }));
    const {post}=await import('./api');
    await expect(post('/example')).rejects.toThrow('Failed to fetch');
    await expect(post('/example')).rejects.toMatchObject({code:'OTHER_AUTH'});
    expect(writes).toBe(2);
  });
});
