"""持久化的本地监测调度。只调用研究服务，不持有任何交易接口。"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parsed(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class AutomationBusy(Exception):
    pass


class Automation:
    LEASE_SECONDS = 90

    def __init__(self, store, work: Callable, active_count: Callable):
        self.store, self.work, self.active_count = store, work, active_count
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        self.run_lock = threading.Lock()
        self.ownership_lock = threading.Lock()
        self.stop_generation = 0

    def config(self) -> dict:
        return self.store.get("automation", "main", False) or dict(
            id="main", enabled=False, interval_seconds=60, auto_review=False,
            next_run_at=None, last_run_at=None, last_status="IDLE", last_error=None,
            cancel_generation=0, owner=None, lease_until=None,
        )

    def status(self) -> dict:
        config = self.config()
        return {**{key: config[key] for key in (
            "enabled", "interval_seconds", "auto_review", "next_run_at",
            "last_run_at", "last_status", "last_error",
        )}, "active_monitor_count": self.active_count(),
            "worker_running": bool(self.thread and self.thread.is_alive()),
            "limitations": [
                "仅在本地后端服务运行期间检查已保存日线；停止服务后不继续监测",
                "不自动获取实时行情，不进行模拟或真实交易",
                "自动复核需显式开启且模型已配置；可能产生模型费用，每轮最多5次、每信号最多自动尝试一次",
                "关闭阻止后续步骤；已开始的模型请求无法撤回费用，迟到结果保留等待",
                "停机不逐次补跑；失败或中断的模型调用请人工检查后手动重试",
            ]}

    def configure(self, changes: dict) -> dict:
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            config = self.config()
            was_enabled = config["enabled"]
            config.update(changes)
            if changes.get("enabled") is False or changes.get("auto_review") is False:
                config["cancel_generation"] += 1
            if not config["enabled"]:
                config["next_run_at"] = None
            elif not was_enabled or not config.get("next_run_at"):
                config["next_run_at"] = stamp(utcnow())
            elif "interval_seconds" in changes:
                config["next_run_at"] = stamp(utcnow() + timedelta(seconds=config["interval_seconds"]))
            self.store.put("automation", config)
        return self.status()

    def runs(self) -> list[dict]:
        return list(reversed(self.store.all("automation_run")))[0:30]

    def _recover_locked(self, config: dict):
        if config.get("owner") and parsed(config.get("lease_until")) <= utcnow():
            previous = self.store.get("automation_run", config["owner"], False)
            if previous and previous["status"] == "RUNNING":
                previous.update(status="INTERRUPTED", finished_at=stamp(utcnow()),
                                error="上次运行心跳中断，已保留记录；不会重发已尝试的模型请求")
                self.store.put("automation_run", previous)
            config.update(owner=None, lease_until=None, last_status="INTERRUPTED",
                          last_error="上次运行中断，租约已回收")
            self.store.put("automation", config)

    def tick(self) -> dict | None:
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            config = self.config()
            self._recover_locked(config)
        if not config["enabled"] or not config.get("next_run_at") or parsed(config["next_run_at"]) > utcnow():
            return None
        try:
            return self.run("SCHEDULED")
        except AutomationBusy:
            return None

    def run(self, trigger: str = "MANUAL") -> dict | None:
        if not self.run_lock.acquire(blocking=False):
            raise AutomationBusy()
        heartbeat_stop = threading.Event()
        heartbeat_thread = None
        stop_generation = self.stop_generation
        try:
            with self.store.lock, self.store.db:
                self.store.db.execute("BEGIN IMMEDIATE")
                config = self.config()
                self._recover_locked(config)
                if config.get("owner"):
                    raise AutomationBusy()
                if trigger == "SCHEDULED" and (not config["enabled"] or not config.get("next_run_at") or parsed(config["next_run_at"]) > utcnow()):
                    return None
                if trigger == "SCHEDULED":
                    # 原子地预定下一次检查，避免两个进程同时看到到期任务后分别开始。
                    config["next_run_at"] = stamp(utcnow() + timedelta(seconds=config["interval_seconds"]))
                    self.store.put("automation", config)
                run_id = uuid.uuid4().hex
                started = stamp(utcnow())
                run = dict(id=run_id, status="RUNNING", trigger=trigger, started_at=started,
                           finished_at=None, generated=0, reviewed=0, skipped=0, error=None, details=[])
                config.update(owner=run_id, lease_until=stamp(utcnow() + timedelta(seconds=self.LEASE_SECONDS)),
                              heartbeat_at=started, last_run_at=started, last_status="RUNNING", last_error=None)
                self.store.put("automation", config)
                self.store.put("automation_run", run)
                # 仅保留最近30条终态，不删除当前RUNNING记录。
                old = self.store.all("automation_run")[:-30]
                for item in old:
                    self.store.db.execute("DELETE FROM documents WHERE kind='automation_run' AND id=?", (item["id"],))

            def cancelled() -> bool:
                current = self.config()
                return bool(self.stop_generation != stop_generation or current.get("owner") != run_id
                            or not parsed(current.get("lease_until")) or parsed(current["lease_until"]) <= utcnow()
                            or current["cancel_generation"] != config["cancel_generation"]
                            or (trigger == "SCHEDULED" and not current["enabled"]))

            def heartbeat():
                while not heartbeat_stop.wait(2):
                    with self.store.lock, self.store.db:
                        self.store.db.execute("BEGIN IMMEDIATE")
                        current = self.config()
                        if current.get("owner") != run_id or parsed(current.get("lease_until")) <= utcnow():
                            return
                        current.update(heartbeat_at=stamp(utcnow()),
                                       lease_until=stamp(utcnow() + timedelta(seconds=self.LEASE_SECONDS)))
                        self.store.put("automation", current)

            heartbeat_thread = threading.Thread(target=heartbeat, daemon=True, name="monitor-heartbeat")
            heartbeat_thread.start()
            try:
                result = self.work(config, cancelled)
                run.update(result)
                run["status"] = "CANCELLED" if cancelled() else result.get("status", "SUCCEEDED")
            except Exception:
                run.update(status="FAILED", error="监测运行失败，未执行交易；请检查数据与监测配置后重试")
            run["finished_at"] = stamp(utcnow())
            with self.ownership_lock, self.store.lock, self.store.db:
                self.store.db.execute("BEGIN IMMEDIATE")
                current = self.config()
                # 丢失租约不能覆盖新执行者状态或将旧任务标为成功。
                if current.get("owner") == run_id:
                    current.update(owner=None, lease_until=None, last_status=run["status"], last_error=run["error"],
                                   next_run_at=stamp(utcnow() + timedelta(seconds=current["interval_seconds"])) if current["enabled"] else None)
                    self.store.put("automation_run", run)
                    self.store.put("automation", current)
                else:
                    run = self.store.get("automation_run", run_id)
            return run
        finally:
            heartbeat_stop.set()
            if heartbeat_thread:
                heartbeat_thread.join(timeout=3)
            self.run_lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            config = self.config()
            # 服务重启不补跑停机期间错过的周期。
            if config["enabled"] and not config.get("owner"):
                config["next_run_at"] = stamp(utcnow() + timedelta(seconds=config["interval_seconds"]))
                self.store.put("automation", config)

        def loop():
            while not self.stopping.is_set():
                try:
                    self.tick()
                except Exception:
                    # SQLite等暂时异常不终止调度线程；业务错误保留在运行记录中。
                    pass
                self.stopping.wait(1)

        self.thread = threading.Thread(target=loop, daemon=True, name="saved-market-monitor")
        self.thread.start()

    def stop(self):
        self.stop_generation += 1
        self.stopping.set()
        if self.thread:
            # 当前HTTP模型调用有20秒超时；允许其结束并保存取消状态。
            self.thread.join(timeout=25)
        with self.ownership_lock:
            pass
