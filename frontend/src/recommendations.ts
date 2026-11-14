import { post } from "./api";
import type { Recommendation } from "./types";

/** 选股算法必须显式提交，避免界面选择与服务端默认算法不一致。 */
export function runSelection(algorithmId: string) {
  if (!algorithmId) throw new Error("请先选择选股算法");
  return post<Recommendation[]>("/recommendations/run", {
    algorithm_id: algorithmId,
  });
}
