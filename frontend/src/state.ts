import { reactive, ref } from "vue";
import { api, post } from "./api";
import type {
  Algorithm,
  Dashboard,
  Meta,
  Notice,
  Recommendation,
  Security,
  Settings,
  Signal,
  WatchItem,
  Monitor,
  Review,
} from "./types";
export const state = reactive({
  meta: {
    mode: "EMPTY",
    source: "尚未连接",
    as_of: null,
    stale: false,
    request_id: "",
  } as Meta,
  securities: [] as Security[],
  watchlists: [] as WatchItem[],
  algorithms: [] as Algorithm[],
  recommendations: [] as Recommendation[],
  signals: [] as Signal[],
  monitors: [] as Monitor[],
  reviews: [] as Review[],
  notifications: [] as Notice[],
  settings: null as Settings | null,
  dashboard: null as Dashboard | null,
});
export const loading = ref(false),
  error = ref(""),
  toast = ref("");
let toastTimer: ReturnType<typeof setTimeout>;
export function inform(message: string) {
  toast.value = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.value = ""), 5000);
}
export async function action<T>(fn: () => Promise<T>, success?: string) {
  try {
    const r = await fn();
    if (success) inform(success);
    return r;
  } catch (e) {
    inform(e instanceof Error ? e.message : "操作失败");
    return undefined;
  }
}
export async function refresh() {
  loading.value = true;
  error.value = "";
  try {
    const [sec, w, a, r, s, m, n, settings, d, rev] = await Promise.all([
      api<Security[]>("/securities"),
      api<WatchItem[]>("/watchlists"),
      api<Algorithm[]>("/algorithms"),
      api<Recommendation[]>("/recommendations"),
      api<Signal[]>("/signals"),
      api<Monitor[]>("/monitors"),
      api<Notice[]>("/notifications"),
      api<Settings>("/settings"),
      api<Dashboard>("/dashboard"),
      api<Review[]>("/reviews"),
    ]);
    Object.assign(state, {
      securities: sec.data,
      watchlists: w.data,
      algorithms: a.data,
      recommendations: r.data,
      signals: s.data,
      monitors: m.data,
      notifications: n.data,
      settings: settings.data,
      dashboard: d.data,
      reviews: rev.data,
      meta: sec.meta,
    });
  } catch (e) {
    error.value = e instanceof Error ? e.message : "无法连接本地服务";
  } finally {
    loading.value = false;
  }
}
export async function seed() {
  const result = await action(() => post<{ message: string }>("/demo/seed"));
  if (result) {
    inform(result.data.message);
    await refresh();
  }
}
export async function addWatch(security_id: string, group_name = "我的自选") {
  const result = await action(async () => {
    if (security_id.startsWith("LIVE."))
      await post(`/securities/${encodeURIComponent(security_id)}/activate`);
    return post("/watchlists", { security_id, group_name });
  }, "已加入自选，重复记录会自动合并");
  if (result) await refresh();
}
