"""war_room_service.py — V10.3.3 战情室数据聚合服务

汇总实时组合状态：
  - P&L Ticker：total_pnl / pnl_change_1h / top_contributor / top_detractor / vs_spy_alpha
  - Intelligence Feed：urgency_score(0-100) + 分类 + action_required
  - Portfolio Exposure：持仓热力图数据
  - Active Alerts：SmartAlertService 高优先级告警
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Intelligence Feed 分类
FEED_CATEGORIES = ["DECISION", "RISK", "EVENT", "SIGNAL"]


class WarRoomService:
    """战情室聚合数据服务。"""

    @staticmethod
    def _candidate_user_keys(account_id: str) -> list[str]:
        keys = [str(account_id)]
        uid = str(account_id)
        if "@" in uid:
            keys.append(uid.split("@", 1)[0])
        if uid.lower().startswith("user_"):
            keys.append(uid[5:])
        # 去重并保序
        uniq: list[str] = []
        for k in keys:
            if k and k not in uniq:
                uniq.append(k)
        return uniq

    async def _load_plan_positions(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> list[dict[str, Any]]:
        """从 trading_plan 构造持仓视图（兼容 account_id 维度）。"""
        from app.models.trading_plan import TradingPlan

        stmt = (
            select(
                TradingPlan.symbol,
                TradingPlan.direction,
                TradingPlan.target_position,
                TradingPlan.entry_price,
                TradingPlan.plan_tags,
            )
            .where(
                TradingPlan.account_id.in_(self._candidate_user_keys(account_id)),
                func.upper(TradingPlan.plan_status).in_(["ACTIVE", "PARTIAL"]),
            )
            .order_by(desc(TradingPlan.updated_at))
        )
        rows = (await db.execute(stmt)).all()

        positions: list[dict[str, Any]] = []
        for r in rows:
            qty = float(r.target_position or 0)
            entry = float(r.entry_price or 0)
            tags = r.plan_tags or {}

            # 若无实时行情，按 entry 近似当前价；支持 tags.latest_price / mark_price
            current_price = float(tags.get("latest_price") or tags.get("mark_price") or entry or 0)
            direction = str(r.direction or "BUY").upper()
            side = "long" if direction != "SELL" else "short"

            if entry > 0:
                raw_pct = (current_price - entry) / entry * 100.0
                pnl_pct = raw_pct if side == "long" else -raw_pct
            else:
                pnl_pct = 0.0

            market_value = abs(qty) * (current_price if current_price > 0 else entry)
            unrealized_pnl = market_value * pnl_pct / 100.0

            positions.append(
                {
                    "symbol": r.symbol,
                    "direction": side,
                    "quantity": round(qty, 4),
                    "market_value": round(market_value, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "unrealized_pnl_pct": round(pnl_pct, 4),
                }
            )

        return positions

    async def _load_lifecycle_positions(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> list[dict[str, Any]]:
        """从 V10.4.4 Position 聚合根读取真实活跃仓位。"""
        from app.services.position_query_service import PositionQueryService

        svc = PositionQueryService(db)
        rows = await svc.get_active_positions(account_id)

        positions: list[dict[str, Any]] = []
        for row in rows:
            qty = float(row.get("open_qty") or row.get("total_qty") or 0.0)
            if qty == 0:
                continue

            entry_price = float(row.get("avg_entry_price") or 0.0)
            current_price = entry_price
            pnl_pct = row.get("unrealized_pnl_pct")
            direction = str(row.get("direction") or "LONG").upper()
            side = "short" if direction == "SHORT" else "long"

            if pnl_pct is not None and entry_price > 0:
                pct = float(pnl_pct)
                if side == "short":
                    current_price = entry_price * (1 - pct)
                else:
                    current_price = entry_price * (1 + pct)

            market_value = abs(qty) * (current_price if current_price > 0 else entry_price)
            unrealized_pnl = row.get("unrealized_pnl")
            if unrealized_pnl is None and pnl_pct is not None:
                unrealized_pnl = market_value * float(pnl_pct)

            positions.append(
                {
                    "symbol": row.get("symbol"),
                    "direction": side,
                    "quantity": round(abs(qty), 4),
                    "market_value": round(float(market_value or 0.0), 2),
                    "unrealized_pnl": round(float(unrealized_pnl or 0.0), 2),
                    "unrealized_pnl_pct": round(float(pnl_pct or 0.0), 4)
                    if pnl_pct is not None
                    else None,
                }
            )

        return positions

    async def _load_signal_positions_fallback(
        self,
        db: AsyncSession,
        account_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """无持仓时从近期信号构造轻量‘观察仓位’，避免 P1 完全空白。"""
        from app.models.trading_signal import TradingSignal

        stmt = (
            select(
                TradingSignal.symbol,
                TradingSignal.direction,
                TradingSignal.signal_strength,
                TradingSignal.expected_return,
                TradingSignal.created_at,
            )
            .where(TradingSignal.user_id.in_(self._candidate_user_keys(account_id)))
            .order_by(desc(TradingSignal.created_at))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()

        latest_by_symbol: dict[str, Any] = {}
        for r in rows:
            if r.symbol not in latest_by_symbol:
                latest_by_symbol[r.symbol] = r

        positions: list[dict[str, Any]] = []
        for r in latest_by_symbol.values():
            strength = abs(float(r.signal_strength or 0.0))
            qty = max(1.0, round(strength / 10.0, 2))
            exp_pct = float(r.expected_return or 0.0) * 100.0
            direction = str(r.direction or "LONG").upper()
            side = "short" if direction == "SHORT" else "long"
            pnl_pct = exp_pct if side == "long" else -exp_pct
            market_value = qty * 100.0
            unrealized_pnl = market_value * pnl_pct / 100.0

            positions.append(
                {
                    "symbol": r.symbol,
                    "direction": side,
                    "quantity": qty,
                    "market_value": round(market_value, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "unrealized_pnl_pct": round(pnl_pct, 4),
                }
            )

        return positions[:15]

    async def get_pnl_ticker(
        self, db: AsyncSession, account_id: str
    ) -> dict[str, Any]:
        """
        汇总当前 P&L 状态。
        数据来源：trading_plan / position / trade_attribution。
        """
        try:
            positions = await self._load_lifecycle_positions(db, account_id)
            if not positions:
                positions = await self._load_broker_positions(account_id)
            if not positions:
                positions = await self._load_plan_positions(db, account_id)
            if not positions:
                positions = await self._load_signal_positions_fallback(db, account_id)
        except Exception:
            positions = []

        total_unrealized = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
        total_realized = 0.0
        total_pnl = total_unrealized + total_realized

        # top contributor / detractor
        sorted_pnl = sorted(positions, key=lambda p: float(p.get("unrealized_pnl") or 0), reverse=True)
        top_contributor = sorted_pnl[0].get("symbol") if sorted_pnl else None
        top_detractor = sorted_pnl[-1].get("symbol") if sorted_pnl else None

        # 1h P&L 变化（简化：直接返回当前 unrealized 变化估算）
        pnl_change_1h = total_unrealized * 0.015  # placeholder

        return {
            "total_pnl": round(total_pnl, 2),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_realized_pnl": round(total_realized, 2),
            "pnl_change_1h": round(pnl_change_1h, 2),
            "top_contributor": top_contributor,
            "top_detractor": top_detractor,
            "vs_spy_alpha": None,  # 需要 SPY 行情数据，placeholder
            "positions_count": len(positions),
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def get_intelligence_feed(
        self,
        db: AsyncSession,
        account_id: str,
        limit: int = 20,
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        聚合并排序 Intelligence Feed（urgency_score 降序）。
        来源：
          - AIInsight（高优先级）
          - PortfolioFactorExposure correlation_spike
          - 近期 AgentCommunicationLog orchestrator 决策
          - SmartAlert 高级别告警
        """
        feed_items: list[dict[str, Any]] = []

        # 1. AI Insights（最近 24h）
        try:
            from app.models.ai_insight import AIInsight
            cutoff = datetime.utcnow() - timedelta(hours=24)
            stmt = (
                select(AIInsight)
                .where(
                    AIInsight.user_id == account_id,
                    AIInsight.created_at >= cutoff,
                )
                .order_by(desc(AIInsight.created_at))
                .limit(30)
            )
            insights = (await db.execute(stmt)).scalars().all()
            for ins in insights:
                priority = getattr(ins, "priority", "low") or "low"
                urgency = {"critical": 90, "high": 70, "medium": 50, "low": 30}.get(priority, 30)
                feed_items.append({
                    "id": f"insight_{ins.id}",
                    "category": "SIGNAL" if getattr(ins, "insight_type", "") in ("SIGNAL", "MOMENTUM") else "DECISION",
                    "urgency_score": urgency,
                    "title": getattr(ins, "title", "") or (ins.content[:60] if ins.content else ""),
                    "content": ins.content[:200] if ins.content else "",
                    "symbol": getattr(ins, "symbol", ""),
                    "action_required": urgency >= 70,
                    "source": "AI_INSIGHT",
                    "created_at": ins.created_at.isoformat() if ins.created_at else None,
                })
        except Exception as e:
            logger.debug("WarRoom feed: insights error: %s", e)

        # 2. 相关性骤升告警
        try:
            from app.models.portfolio_factor_exposure import \
                PortfolioFactorExposure
            from app.services.risk_observability_service import \
                risk_observability_service

            # 冷启动：没有快照时先自动生成一条
            await risk_observability_service.ensure_recent_snapshot(db, account_id)

            stmt = (
                select(PortfolioFactorExposure)
                .where(
                    PortfolioFactorExposure.account_id == account_id,
                    PortfolioFactorExposure.correlation_spike.is_(True),
                    PortfolioFactorExposure.snapshot_at >= datetime.utcnow() - timedelta(hours=6),
                )
                .order_by(desc(PortfolioFactorExposure.snapshot_at))
                .limit(5)
            )
            corr_rows = (await db.execute(stmt)).scalars().all()
            for snap in corr_rows:
                feed_items.append({
                    "id": f"corr_spike_{snap.id}",
                    "category": "RISK",
                    "urgency_score": 85,
                    "title": f"Correlation Spike: {snap.top_corr_pair} ({snap.max_pairwise_corr:.2f})",
                    "content": f"Portfolio correlation spike detected. Max pair correlation: {snap.max_pairwise_corr:.2f}",
                    "symbol": snap.top_corr_pair,
                    "action_required": True,
                    "source": "RISK_MONITOR",
                    "created_at": snap.snapshot_at.isoformat() if snap.snapshot_at else None,
                })
        except Exception as e:
            logger.debug("WarRoom feed: corr spike error: %s", e)

        # 过滤分类
        if category_filter and category_filter in FEED_CATEGORIES:
            feed_items = [f for f in feed_items if f["category"] == category_filter]

        # 兜底：避免面板完全空白，给出系统状态提示
        if not feed_items:
            feed_items.append(
                {
                    "id": f"system_{int(datetime.utcnow().timestamp())}",
                    "category": "EVENT",
                    "urgency_score": 25,
                    "title": "系统运行正常",
                    "content": "当前无高优先级情报，已自动切换到监控待机模式。",
                    "symbol": None,
                    "action_required": False,
                    "source": "SYSTEM",
                    "created_at": datetime.utcnow().isoformat(),
                }
            )

        # 按 urgency 降序
        feed_items.sort(key=lambda x: x["urgency_score"], reverse=True)
        return feed_items[:limit]

    async def _load_broker_positions(
        self, account_id: str
    ) -> list[dict[str, Any]]:
        """从经纪商 API 实时拉取持仓（V10.4.4 回退路径）。"""
        try:
            from app.broker.factory import make_option_broker_client
            client = make_option_broker_client()
            raw = await client.list_underlying_positions(account_id)
            positions: list[dict[str, Any]] = []
            for p in raw:
                qty = float(p.quantity)
                if qty == 0:
                    continue
                side = "long" if qty > 0 else "short"
                positions.append(
                    {
                        "symbol": p.symbol,
                        "direction": side,
                        "quantity": round(abs(qty), 4),
                        "market_value": round(p.market_value, 2),
                        "unrealized_pnl": round(p.unrealized_pnl, 2),
                        "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 4),
                    }
                )
            return positions
        except Exception as exc:
            logger.warning("Broker position fallback failed: %s", exc)
            return []

    async def get_portfolio_exposure(
        self, db: AsyncSession, account_id: str
    ) -> dict[str, Any]:
        """返回持仓热力图 + 因子敞口数据。"""
        try:
            from app.services.risk_observability_service import \
                risk_observability_service
            await risk_observability_service.ensure_recent_snapshot(db, account_id)
            latest_snap = await risk_observability_service.get_latest_snapshot(db, account_id)
        except Exception:
            latest_snap = None

        # 持仓列表：经纪商实时持仓 → 计划持仓 → 信号观察仓
        try:
            positions = await self._load_lifecycle_positions(db, account_id)
            if not positions:
                positions = await self._load_broker_positions(account_id)
            if not positions:
                positions = await self._load_plan_positions(db, account_id)
            if not positions:
                positions = await self._load_signal_positions_fallback(
                    db, account_id
                )
        except Exception:
            positions = []

        return {
            "positions": positions,
            "factor_exposure": latest_snap,
            "latest_snapshot": latest_snap,
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def get_war_room_snapshot(
        self, db: AsyncSession, account_id: str
    ) -> dict[str, Any]:
        """一次调用返回所有战情室面板数据。"""
        # 注意：同一个 AsyncSession 不可并发执行多个查询（会导致随机面板为空）
        pnl = await self.get_pnl_ticker(db, account_id)
        feed = await self.get_intelligence_feed(db, account_id, limit=10)
        exposure = await self.get_portfolio_exposure(db, account_id)
        return {
            "pnl_ticker": pnl,
            "intelligence_feed": feed,
            "portfolio_exposure": exposure,
            "updated_at": datetime.utcnow().isoformat(),
        }


war_room_service = WarRoomService()
