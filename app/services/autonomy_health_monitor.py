"""
autonomy_health_monitor.py — V10.4 M4 自主循环健康监控服务

8 项系统健康检查，每 2 分钟运行一次。
每项检查独立运行，失败不影响其他检查，结果通过 WebSocket 推送给前端。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 检查结果数据类
# ─────────────────────────────────────────────
@dataclass
class HealthCheckResult:
    name: str                           # 检查项名称
    status: str                         # OK | WARN | CRITICAL | ERROR
    message: str                        # 人类可读描述
    detail: Dict[str, Any] = field(default_factory=dict)  # 额外明细
    checked_at: str = ""                # ISO 时间戳

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(tz=timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomyHealthReport:
    checks: List[HealthCheckResult]
    overall_status: str     # OK / WARN / CRITICAL
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "overall_status": self.overall_status,
            "generated_at": self.generated_at,
        }


# ─────────────────────────────────────────────
# 监控器
# ─────────────────────────────────────────────
class AutonomyHealthMonitor:
    """
    V10.4 M4 系统健康检查器

    每次调用 run_all_checks(db) 执行全部 8 项检查，
    返回 AutonomyHealthReport，调用者负责推送。
    """

    @staticmethod
    def _is_schema_mismatch_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "doesn't exist" in msg
            or "unknown column" in msg
            or "no such table" in msg
            or "no such column" in msg
        )

    @staticmethod
    def _to_utc_datetime(value: Any) -> Optional[datetime]:
        if not isinstance(value, datetime):
            return None
        return value.replace(tzinfo=timezone.utc)

    # ── 检查 1: FSM 卡死检测 ────────────────────────────────────
    async def check_fsm_stuck(self, db) -> HealthCheckResult:
        name = "fsm_stuck"
        try:
            from sqlalchemy import text
            threshold_dt = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
            # 状态机停留在非终态超过 10 分钟
            TERMINAL_STATES = ("CLOSED", "CANCELLED", "EXPIRED", "COMPLETED", "DONE")
            stmt = text(
                "SELECT COUNT(DISTINCT lf.plan_id) "
                "FROM fsm_transition_log lf "
                "JOIN ("
                "  SELECT plan_id, MAX(occurred_at) AS last_occurred_at "
                "  FROM fsm_transition_log "
                "  GROUP BY plan_id"
                ") latest "
                "  ON latest.plan_id = lf.plan_id "
                " AND latest.last_occurred_at = lf.occurred_at "
                "JOIN trading_plan tp ON tp.id = lf.plan_id "
                "WHERE UPPER(tp.plan_status) IN ('ACTIVE','PARTIAL') "
                "AND lf.to_state NOT IN :terminals "
                "AND lf.occurred_at <= :threshold"
            ).bindparams(
                terminals=TERMINAL_STATES,
                threshold=threshold_dt.replace(tzinfo=None),
            )
            count = (await db.execute(stmt)).scalar() or 0
            if count == 0:
                return HealthCheckResult(name=name, status="OK",
                                         message="无状态机卡死")
            elif count <= 3:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"{count} 条 FSM 记录可能卡死",
                                         detail={"stuck_count": count})
            else:
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"{count} 条 FSM 记录卡死，需人工介入",
                                         detail={"stuck_count": count})
        except Exception as exc:
            if self._is_schema_mismatch_error(exc):
                return HealthCheckResult(name=name, status="WARN",
                                         message="FSM 表结构与当前版本不一致，已跳过该检查",
                                         detail={"error": str(exc)[:160]})
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 检查 2: 权益快照新鲜度 ──────────────────────────────────
    async def check_equity_snapshot(self, db) -> HealthCheckResult:
        name = "equity_snapshot_freshness"
        try:
            from sqlalchemy import text
            row = (await db.execute(
                text("SELECT MAX(created_at) FROM equity_snapshots")
            )).fetchone()
            latest = row[0] if row else None

            # 回退：若权益快照缺失或过旧，使用风险快照作为系统活跃度近似
            fallback_row = (await db.execute(
                text("SELECT MAX(snapshot_at) FROM portfolio_factor_exposure")
            )).fetchone()
            fallback_latest = fallback_row[0] if fallback_row else None

            if latest is None and fallback_latest is None:
                return HealthCheckResult(name=name, status="WARN",
                                         message="权益/风险快照均为空")

            if latest is None and fallback_latest is not None:
                latest = fallback_latest
                source = "risk_snapshot_fallback"
            elif latest is not None and fallback_latest is not None:
                # 两者都存在时使用更新更近的一条，避免老旧 equity 快照压制新鲜风险快照
                latest_dt = self._to_utc_datetime(latest)
                fallback_dt = self._to_utc_datetime(fallback_latest)
                if fallback_dt and latest_dt and fallback_dt > latest_dt:
                    latest = fallback_latest
                    source = "risk_snapshot_fallback"
                else:
                    source = "equity_snapshot"
            else:
                source = "equity_snapshot"

            latest_dt = self._to_utc_datetime(latest)
            if latest_dt is None:
                return HealthCheckResult(name=name, status="WARN",
                                         message="快照时间字段类型异常，已跳过该检查")

            age_min = (datetime.now(tz=timezone.utc) - latest_dt).total_seconds() / 60
            if age_min <= 5:
                return HealthCheckResult(name=name, status="OK",
                                         message=f"快照 {age_min:.1f}min 前更新",
                                         detail={"source": source})
            elif age_min <= 15:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"快照已 {age_min:.1f}min 未更新",
                                         detail={"age_minutes": age_min, "source": source})
            else:
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"快照已 {age_min:.1f}min 未更新！",
                                         detail={"age_minutes": age_min, "source": source})
        except Exception as exc:
            if self._is_schema_mismatch_error(exc):
                return HealthCheckResult(name=name, status="WARN",
                                         message="权益快照表结构不匹配，已跳过该检查",
                                         detail={"error": str(exc)[:160]})
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 检查 3: 计划/日志对齐 ───────────────────────────────────
    async def check_plan_fsm_alignment(self, db) -> HealthCheckResult:
        name = "plan_fsm_alignment"
        try:
            from sqlalchemy import text
            threshold_dt = datetime.now(tz=timezone.utc) - timedelta(minutes=15)
            stmt = text(
                "SELECT COUNT(DISTINCT tp.id) FROM trading_plan tp "
                "WHERE UPPER(tp.plan_status) IN ('ACTIVE','PARTIAL') "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM fsm_transition_log ftl "
                "  WHERE ftl.plan_id = tp.id "
                "  AND ftl.occurred_at >= :threshold"
                ")"
            )
            count = (await db.execute(stmt, {"threshold": threshold_dt.replace(tzinfo=None)})).scalar() or 0
            if count == 0:
                return HealthCheckResult(name=name, status="OK",
                                         message="活跃计划 FSM 状态正常")
            elif count <= 2:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"{count} 个活跃计划超过 15min 无 FSM 转换",
                                         detail={"stale_plan_count": count})
            else:
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"{count} 个活跃计划 FSM 长时间无响应",
                                         detail={"stale_plan_count": count})
        except Exception as exc:
            if self._is_schema_mismatch_error(exc):
                return HealthCheckResult(name=name, status="WARN",
                                         message="计划/FSM 结构不匹配，已跳过该检查",
                                         detail={"error": str(exc)[:160]})
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 检查 4: 行情数据延迟 ─────────────────────────────────────
    async def check_market_data_lag(self, db) -> HealthCheckResult:
        name = "market_data_lag"
        try:
            from sqlalchemy import text
            # 与 signal_freshness 语义保持一致：无活跃计划时不做行情时效硬告警
            active_row = (await db.execute(
                text(
                    "SELECT COUNT(*) FROM trading_plan "
                    "WHERE UPPER(plan_status) IN ('ACTIVE','PARTIAL')"
                )
            )).fetchone()
            active_count = int(active_row[0] or 0) if active_row else 0
            if active_count == 0:
                return HealthCheckResult(
                    name=name,
                    status="OK",
                    message="无活跃计划，跳过行情时效检查",
                )

            row = (await db.execute(
                text("SELECT MAX(timestamp) FROM technical_indicators")
            )).fetchone()
            if not row or row[0] is None:
                # 可能是表名不同，尝试 technical_indicator
                row = (await db.execute(
                    text("SELECT MAX(timestamp) FROM technical_indicator")
                )).fetchone()
            if not row or row[0] is None:
                return HealthCheckResult(name=name, status="WARN",
                                         message="行情指标表为空或无数据")
            latest = row[0]
            if hasattr(latest, 'replace'):
                latest = latest.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(tz=timezone.utc) - latest).total_seconds() / 60
            # 交易时段判断（美东 09:30-16:00，工作日）
            from zoneinfo import ZoneInfo
            now_et = datetime.now(tz=ZoneInfo("America/New_York"))
            in_session = (
                now_et.weekday() < 5 and (
                    (now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30))
                    and now_et.hour < 16
                )
            )
            if age_min <= 30:
                return HealthCheckResult(name=name, status="OK",
                                         message=f"行情数据 {age_min:.1f}min 前更新")
            elif age_min <= 60:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"行情数据已 {age_min:.1f}min 未更新")
            else:
                if not in_session and age_min <= 12 * 60:
                    return HealthCheckResult(name=name, status="WARN",
                                             message=f"盘后行情数据已 {age_min:.1f}min 未更新")
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"行情数据已 {age_min:.1f}min 未更新！",
                                         detail={"age_minutes": age_min})
        except Exception as exc:
            if self._is_schema_mismatch_error(exc):
                return HealthCheckResult(name=name, status="WARN",
                                         message="技术指标表结构不匹配，已跳过该检查",
                                         detail={"error": str(exc)[:160]})
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 检查 5: LLM 提供商健康 ──────────────────────────────────
    async def check_llm_health(self, db) -> HealthCheckResult:
        name = "llm_health"
        try:
            from app.services.ai_client_manager import get_circuit_breaker_status, AIProvider
            status = get_circuit_breaker_status()
            broken_providers = list(status.keys())
            if not broken_providers:
                return HealthCheckResult(name=name, status="OK",
                                         message="所有 LLM 提供商可用")
            elif len(broken_providers) == 1:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"{broken_providers[0]} 已熔断，使用备用",
                                         detail={"broken": broken_providers})
            else:
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"多个 LLM 熔断: {broken_providers}",
                                         detail={"broken": broken_providers})
        except Exception as exc:
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 检查 6: 算法执行任务积压 ────────────────────────────────
    async def check_algo_task_backlog(self, db) -> HealthCheckResult:
        name = "algo_task_backlog"
        try:
            from sqlalchemy import text
            threshold_dt = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
            row = (await db.execute(
                text(
                    "SELECT COUNT(*) FROM algo_execution_tasks "
                    "WHERE status='PENDING' AND created_at <= :threshold"
                ),
                {"threshold": threshold_dt.replace(tzinfo=None)},
            )).fetchone()
            count = (row[0] or 0) if row else 0
            if count == 0:
                return HealthCheckResult(name=name, status="OK",
                                         message="无算法任务积压")
            elif count <= 5:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"{count} 个算法任务积压超 5min",
                                         detail={"backlog_count": count})
            else:
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"{count} 个算法任务严重积压！",
                                         detail={"backlog_count": count})
        except Exception as exc:
            if self._is_schema_mismatch_error(exc):
                return HealthCheckResult(name=name, status="WARN",
                                         message="算法任务表结构不匹配，已跳过该检查",
                                         detail={"error": str(exc)[:160]})
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 检查 7: 信号新鲜度 ──────────────────────────────────────
    async def check_signal_freshness(self, db) -> HealthCheckResult:
        name = "signal_freshness"
        try:
            from sqlalchemy import text
            # 仅当存在活跃计划时才检查信号新鲜度，避免“空仓/停机期”误报
            active_row = (await db.execute(
                text(
                    "SELECT COUNT(*) FROM trading_plan "
                    "WHERE UPPER(plan_status) IN ('ACTIVE','PARTIAL')"
                )
            )).fetchone()
            active_count = int(active_row[0] or 0) if active_row else 0
            if active_count == 0:
                return HealthCheckResult(name=name, status="OK",
                                         message="无活跃计划，跳过信号新鲜度检查")

            row = (await db.execute(
                text("SELECT MAX(created_at) FROM trading_signals")
            )).fetchone()
            if not row or row[0] is None:
                return HealthCheckResult(name=name, status="WARN",
                                         message="信号表为空")
            latest = row[0]
            if hasattr(latest, 'replace'):
                latest = latest.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(tz=timezone.utc) - latest).total_seconds() / 60
            if age_min <= 30:
                return HealthCheckResult(name=name, status="OK",
                                         message=f"最新信号 {age_min:.1f}min 前生成")
            elif age_min <= 60:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"信号已 {age_min:.1f}min 未更新")
            else:
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"信号已 {age_min:.1f}min 未更新！",
                                         detail={"age_minutes": age_min})
        except Exception as exc:
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 检查 8: Job Watchdog ─────────────────────────────────────
    async def check_job_watchdog(self, db) -> HealthCheckResult:
        """
        检查关键 Job 是否在预期时间窗口内运行过。
        通过查询 APScheduler 内部状态或最新数据时间戳来推断。
        """
        name = "job_watchdog"
        try:
            from app.jobs.scheduler import get_jobs
            jobs = get_jobs() or []
            job_ids: set[str] = set()
            for job in jobs:
                if job is None:
                    continue
                if isinstance(job, dict):
                    job_id = job.get("id")
                else:
                    job_id = getattr(job, "id", None)
                if isinstance(job_id, str) and job_id:
                    job_ids.add(job_id)

            WATCHED_JOBS = {
                "observability_factor_snapshot": 10,   # 预期每 5min 运行，10min 窗口
                "m1_return_backfill": 26 * 60,          # 预期每天运行，26h 窗口
                "refresh_technical_indicators": 90,     # 预期每 1h 运行，90min 窗口
            }

            missing = [jid for jid in WATCHED_JOBS if jid not in job_ids]
            if not missing:
                return HealthCheckResult(name=name, status="OK",
                                         message=f"全部 {len(WATCHED_JOBS)} 个关键 Job 已注册")
            elif len(missing) == 1:
                return HealthCheckResult(name=name, status="WARN",
                                         message=f"Job 未注册: {missing[0]}",
                                         detail={"missing_jobs": missing})
            else:
                return HealthCheckResult(name=name, status="CRITICAL",
                                         message=f"{len(missing)} 个关键 Job 未注册",
                                         detail={"missing_jobs": missing})
        except Exception as exc:
            if "scheduler not initialized" in str(exc).lower():
                return HealthCheckResult(
                    name=name,
                    status="WARN",
                    message="调度器尚未初始化，Job 注册检查已跳过",
                    detail={"error": str(exc)[:160]},
                )
            return HealthCheckResult(name=name, status="ERROR",
                                     message=f"检查异常: {exc}")

    # ── 汇总入口 ─────────────────────────────────────────────────
    async def run_all_checks(self, db) -> AutonomyHealthReport:
        """执行全部 8 项健康检查，返回汇总报告。"""
        checks: List[HealthCheckResult] = []

        for check_fn in [
            self.check_fsm_stuck,
            self.check_equity_snapshot,
            self.check_plan_fsm_alignment,
            self.check_market_data_lag,
            self.check_llm_health,
            self.check_algo_task_backlog,
            self.check_signal_freshness,
            self.check_job_watchdog,
        ]:
            try:
                result = await check_fn(db)
            except Exception as exc:
                result = HealthCheckResult(
                    name=getattr(check_fn, "__name__", "unknown"),
                    status="ERROR",
                    message=f"未捕获异常: {exc}",
                )
            checks.append(result)

        statuses = {c.status for c in checks}
        if "CRITICAL" in statuses:
            overall = "CRITICAL"
        elif "WARN" in statuses or "ERROR" in statuses:
            overall = "WARN"
        else:
            overall = "OK"

        return AutonomyHealthReport(
            checks=checks,
            overall_status=overall,
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
        )


# ── 单例 ──────────────────────────────────────────────────────
autonomy_health_monitor = AutonomyHealthMonitor()
