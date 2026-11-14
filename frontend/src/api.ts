import type { Envelope } from "./types";
let session: Promise<unknown> | undefined;
function ensureSession() {
  session ??= api('/session').catch((error) => { session = undefined; throw error; });
  return session;
}
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  init: RequestInit = {},
  retried = false,
): Promise<Envelope<T>> {
  let usedSession: Promise<unknown> | undefined;
  if (path != "/session") {
    usedSession = ensureSession();
    await usedSession;
  }
  const body = init.body;
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    // 行情和资料都可能在服务端后台更新；浏览器不能复用旧的 GET 响应。
    cache: init.cache ?? "no-store",
    credentials: "same-origin",
    headers: {
      ...(body && !(body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init.headers,
    },
  });
  let payload: any;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("INVALID_RESPONSE", "服务暂时不可用，请确认后端已启动");
  }
  // SESSION_REQUIRED由服务端中间件在业务执行前返回，可安全恢复一次。
  // 网络超时、业务拒绝和其他401不重放，避免重复提交有副作用的操作。
  if (response.status === 401 && payload.error?.code === 'SESSION_REQUIRED' && path !== '/session' && !retried) {
    if (session === usedSession) session = undefined;
    await ensureSession();
    return api<T>(path, init, true);
  }
  if (!response.ok)
    throw new ApiError(
      payload.error?.code ?? String(response.status),
      payload.error?.message_zh ?? "请求失败",
      payload.meta?.request_id,
    );
  return payload;
}
export const post = <T>(path: string, data: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(data) });
export const patch = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
