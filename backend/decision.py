"""无交易权限的复核过滤层；纯函数可独立验证，不调用模型或账本。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def evaluate_gate(
    signal: dict,
    monitor: dict | None,
    review: dict | None,
    current_input_hash: str | None,
    algorithm_version: str | None,
    agent_configured: bool,
    evaluated_at: datetime | None = None,
    current_research_hash: str | None = None,
) -> dict:
    instant = evaluated_at or datetime.now(timezone.utc)
    mode = monitor.get("agent_mode", "OFF") if monitor else "OFF"
    checks: list[dict] = []

    def check(key: str, label: str, passed: bool | None, detail: str):
        checks.append(dict(id=key, label=label, passed=passed, detail=detail))

    confirmed, expires = timestamp(signal.get("confirmed_at")), timestamp(signal.get("valid_until"))
    timely = bool(signal.get("status") == "CONFIRMED" and confirmed and expires and confirmed <= instant < expires)
    snapshot_matches = bool(signal.get("input_snapshot_hash") and current_input_hash == signal["input_snapshot_hash"])
    version_matches = bool(algorithm_version and signal.get("algorithm_version", signal.get("version")) == algorithm_version)
    active = bool(monitor and monitor.get("enabled"))
    actionable = signal.get("kind") in {"BUY", "SELL", "T_BUY", "T_SELL"}
    check("monitor", "监测启用", active, "已启用当前算法监测" if active else "监测已暂停或不存在")
    check("signal_time", "信号有效期", timely, "处于确认后的有效期内" if timely else "尚未确认、已过期或有效期不完整")
    check("input_snapshot", "行情与参数快照", snapshot_matches, "与信号计算快照一致" if snapshot_matches else "行情或参数已改变，需重新计算信号")
    check("algorithm_version", "算法版本", version_matches, "当前版本与信号版本一致" if version_matches else "算法版本已变更或旧信号缺少版本记录")
    check("signal_kind", "买卖观察条件", actionable, "已有买卖或做T观察信号" if actionable else "当前仅为关注状态，不具备买卖观察条件")

    def result(status: str, label: str, passed: bool | None, reasons: list[str]):
        return dict(agent_mode=mode, status=status, label=label, gate_passed=passed,
                    reasons=reasons, checks=checks, execution_permission="NOT_EVALUATED",
                    execution_label="未核对账户，不构成下单许可", evaluated_at=instant.isoformat().replace("+00:00", "Z"))

    failures = [item["detail"] for item in checks if item["passed"] is False]
    if failures:
        return result("BLOCKED", "基础条件未通过", False, failures)
    if mode == "OFF":
        return result("OFF", "Agent已关闭，不参与过滤", None, ["保留算法观察；不会调用模型或批准交易"])
    if mode == "EXPLAIN":
        return result("EXPLAIN_ONLY", "仅解释，不参与过滤", None, ["复核意见只辅助理解，不改变算法信号"])
    if mode != "FILTER":
        return result("BLOCKED", "未知复核模式", False, ["无法识别监测配置，保持阻断"])

    check("agent_available", "模型已配置", agent_configured, "模型连接已配置，仍需核对本次结果" if agent_configured else "未配置LLM，参与过滤模式不能放行")
    if not review:
        check("review", "本次模型复核", False, "尚无复核结果")
        return result("WAITING_REVIEW", "等待有效模型复核", False, ["缺少复核结果" if agent_configured else "未配置LLM，保持等待"])
    bound = (
        review.get("signal_id") == signal.get("id")
        and review.get("signal_version") == signal.get("version")
        and review.get("input_snapshot_hash") == signal.get("input_snapshot_hash")
    )
    started, until = timestamp(review.get("created_at")), timestamp(review.get("valid_until"))
    review_timely = bool(started and until and confirmed <= started <= instant < until <= expires)
    actual_model = review.get("mode") == "LLM"
    check("review_binding", "复核绑定当前信号", bound, "信号编号、版本及快照匹配" if bound else "复核与当前信号版本或输入不一致")
    if current_research_hash is not None:
        research_matches = review.get('research_revision_hash') == current_research_hash
        check('research_binding', '研究资料版本绑定', research_matches,
              '研究资料版本与本次复核一致' if research_matches else '研究资料已变化或旧复核未绑定证据，请手动重新复核')
    check("review_time", "复核有效期", review_timely, "复核尚有效且不超过信号期限" if review_timely else "复核已过期、时间不符或超过信号有效期")
    check("review_model", "真实模型复核", actual_model, "已收到结构化模型复核" if actual_model else "未配置结果或规则演示不能代替模型通过")
    failures = [item["detail"] for item in checks if item["passed"] is False]
    if failures:
        return result("WAITING_REVIEW", "缺少有效模型复核", False, failures)
    verdict = review.get("verdict")
    if verdict == "SUPPORT" and not review.get("conditions"):
        return result("PASSED", "复核过滤通过", True, ["有效模型支持且无未核对附加条件；尚未检查账户、库存、价格及交易规则"])
    if verdict == "REJECT":
        return result("REJECTED", "模型反对，过滤未通过", False, ["保留原始信号与反对证据"])
    if verdict == "CONDITIONAL" or review.get("conditions"):
        return result("CONDITIONAL", "附加条件待核对", False, ["软件尚未验证附加条件，不能视为已满足"])
    return result("WAITING_REVIEW", "模型保持等待", False, ["模型没有给出无附加条件的有效支持"])
