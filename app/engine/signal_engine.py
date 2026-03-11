"""
信号引擎 - 量化交易闭环的核心组件

功能:
1. 从多个来源(策略/研究/AI)收集交易信号
2. 统一信号格式和评分
3. 信号验证和风险过滤
4. 信号优先级排序
5. 信号生命周期管理
"""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.cache import cache
from app.core.trade_mode import TradeMode
from app.models.strategy import Strategy, StrategyRun, StrategyRunAsset
from app.models.trading_signal import (SignalPerformance, SignalSource,
                                       SignalStatus, SignalType, TradingSignal)
from app.services.account_service import AccountService
from app.services.risk_config_service import RiskConfigService
from app.services.safety_guard import SafetyGuard


class SignalEngine:
    """信号引擎 - 交易信号的生成、验证和管理"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.risk_svc = RiskConfigService(session)
        self.account_svc = AccountService(session)
        try:
            self.broker = make_option_broker_client()
        except Exception as e:
            print(f"初始化broker失败: {e}")
            self.broker = None
    
    async def generate_signals_from_strategy_run(
        self, 
        strategy_run_id: str,
        max_signals: int = 10
    ) -> List[TradingSignal]:
        """
        从策略运行结果生成交易信号
        这是研究到交易的桥梁
        """
        # 获取策略运行结果
        stmt = (
            select(StrategyRun)
            .where(StrategyRun.id == strategy_run_id)
        )
        result = await self.session.execute(stmt)
        strategy_run = result.scalars().first()
        
        if not strategy_run or strategy_run.status != "COMPLETED":
            return []
        
        # 获取策略资产(得分最高的标的)
        stmt = (
            select(StrategyRunAsset)
            .where(StrategyRunAsset.strategy_run_id == strategy_run_id)
            .order_by(desc(StrategyRunAsset.signal_strength))
            .limit(max_signals)
        )
        result = await self.session.execute(stmt)
        assets = result.scalars().all()
        
        signals = []
        for asset in assets:
            if (asset.signal_strength or 0) < (strategy_run.min_score or 60):
                continue
            
            signal = await self._create_signal_from_asset(
                strategy_run=strategy_run,
                asset=asset
            )
            signals.append(signal)
        
        return signals
    
    async def _infer_signal_type(
        self,
        symbol: str,
        direction: str,
        account_id: str
    ) -> SignalType:
        """
        根据当前持仓智能推断信号类型
        
        规则:
        - 无持仓 → ENTRY (开仓)
        - 有同向持仓 → ADD (加仓)  
        - 有反向持仓 → EXIT (平仓/换向)
        """
        if not self.broker:
            return SignalType.ENTRY  # Broker未初始化，默认ENTRY
        
        try:
            def _pos_symbol(p: Any) -> Optional[str]:
                if isinstance(p, dict):
                    return p.get("symbol") or p.get("ticker")
                return getattr(p, "symbol", None) or getattr(p, "ticker", None)

            def _pos_qty(p: Any) -> float:
                if isinstance(p, dict):
                    return float(p.get("qty") or p.get("quantity") or 0)
                return float(getattr(p, "qty", None) or getattr(p, "quantity", None) or 0)

            # 获取当前持仓
            positions = await self.broker.list_underlying_positions(account_id)
            
            # 查找该symbol的持仓
            position = next((p for p in positions if _pos_symbol(p) == symbol), None)
            
            if not position:
                return SignalType.ENTRY  # 无持仓 → 开仓
            
            position_qty = _pos_qty(position)
            
            # 判断方向
            if position_qty > 0:  # 多头持仓
                if direction == 'LONG':
                    return SignalType.ADD  # 同向 → 加仓
                else:
                    return SignalType.EXIT  # 反向 → 平仓
            elif position_qty < 0:  # 空头持仓
                if direction == 'SHORT':
                    return SignalType.ADD  # 同向 → 加仓
                else:
                    return SignalType.EXIT  # 反向 → 平仓
            else:
                return SignalType.ENTRY  # 持仓为0 → 开仓
                
        except Exception as e:
            print(f"推断信号类型失败: {e}")
            return SignalType.ENTRY  # 错误时默认ENTRY
    
    async def _create_signal_from_asset(
        self,
        strategy_run: StrategyRun,
        asset: StrategyRunAsset
    ) -> TradingSignal:
        """从策略资产创建交易信号（含去重检查）"""
        
        # 🔍 去重检查：查找相同symbol的活跃信号
        existing_signal_stmt = (
            select(TradingSignal)
            .where(TradingSignal.symbol == asset.symbol)
            .where(TradingSignal.account_id == strategy_run.account_id)
            .where(TradingSignal.status.in_([SignalStatus.GENERATED, SignalStatus.VALIDATED]))
            .where(
                or_(
                    TradingSignal.expired_at.is_(None),
                    TradingSignal.expired_at > datetime.utcnow()
                )
            )
            .order_by(desc(TradingSignal.signal_strength))
        )
        existing_result = await self.session.execute(existing_signal_stmt)
        existing_signal = existing_result.scalars().first()
        
        new_signal_strength = asset.signal_strength or 70.0
        
        # 如果已存在信号，比较信号强度决定是否更新
        if existing_signal:
            print(f"[SignalEngine] Found existing signal for {asset.symbol}, checking update...")
            if new_signal_strength > existing_signal.signal_strength:
                # 🔄 更新为更强的信号
                signal_dims = self._safe_dict(asset.signal_dimensions)
                existing_signal.signal_strength = new_signal_strength
                existing_signal.confidence = min(new_signal_strength / 100.0, 1.0)
                existing_signal.expected_return = signal_dims.get('expected_return', 0.05)
                existing_signal.risk_score = signal_dims.get('risk_score', 50.0)
                existing_signal.suggested_quantity = self._calculate_position_size(
                    new_signal_strength,
                    signal_dims.get('risk_score', 50.0)
                )
                existing_signal.quantity_mode = "PCT_EQUITY"
                existing_signal.quantity_value = existing_signal.suggested_quantity
                existing_signal.priority = int(new_signal_strength)
                existing_signal.strategy_run_id = strategy_run.id
                existing_signal.factor_scores = self._build_factor_scores_payload(
                    signal_dims,
                    new_signal_strength,
                )
                existing_meta = self._safe_dict(existing_signal.extra_metadata).copy()
                existing_meta.update(
                    {
                        "strategy_name": (
                            strategy_run.strategy.name if strategy_run.strategy else None
                        ),
                        "strategy_version": strategy_run.strategy_version,
                        "run_universe": strategy_run.target_universe,
                    }
                )
                existing_meta.update(
                    self._extract_watchtower_dimension_fields(signal_dims)
                )
                # P0.2: signal regenerated with higher strength — reset watchtower so it
                # goes through the full quality funnel again rather than carrying stale
                # REJECTED / PASSED state from a previous evaluation cycle.
                existing_meta.update(
                    {
                        "watchtower_stage": "SIGNAL_GENERATION",
                        "watchtower_result": "PENDING",
                        "watchtower_reason_code": None,
                        "watchtower_reason_detail": None,
                        "watchtower_reason_category": "GENERATION",
                        "watchtower_rejected_at_layer": None,
                    }
                )
                existing_signal.extra_metadata = existing_meta
                # P0.1: preserve or promote origin mode (SYNTHETIC overrides REAL)
                new_origin = signal_dims.get("signal_origin_mode")
                if new_origin:
                    existing_signal.signal_origin_mode = new_origin
                existing_signal.expired_at = datetime.utcnow() + timedelta(hours=24)
                
                await self.session.commit()
                await self.session.refresh(existing_signal)
                return existing_signal
            else:
                # ⏭️ 跳过较弱的信号，返回现有信号
                return existing_signal
        
        # 从signal_dimensions JSON字段提取分数,如果不存在则使用默认值
        signal_dims = self._safe_dict(asset.signal_dimensions)
        
        # 🧠 智能推断信号类型（基于当前持仓）
        signal_direction = strategy_run.direction or "LONG"
        signal_type = await self._infer_signal_type(
            symbol=asset.symbol,
            direction=signal_direction,
            account_id=strategy_run.account_id
        )
        suggested_qty = self._calculate_position_size(
            new_signal_strength,
            signal_dims.get('risk_score', 50.0)
        )
        
        signal_extra_metadata = {
            "strategy_name": (
                strategy_run.strategy.name if strategy_run.strategy else None
            ),
            "strategy_version": strategy_run.strategy_version,
            "run_universe": strategy_run.target_universe,
            "watchtower_stage": "SIGNAL_GENERATION",
            "watchtower_result": "PENDING",
            "watchtower_reason_category": "GENERATION",
        }
        signal_extra_metadata.update(
            self._extract_watchtower_dimension_fields(signal_dims)
        )

        # ✨ 创建新信号
        signal = TradingSignal(
            signal_id=str(uuid4()),
            signal_type=signal_type,
            signal_source=SignalSource.STRATEGY,
            signal_origin_mode=signal_dims.get("signal_origin_mode", "REAL"),  # P0.1
            status=SignalStatus.GENERATED,
            
            symbol=asset.symbol,
            direction=signal_direction,
            
            signal_strength=new_signal_strength,
            confidence=min(new_signal_strength / 100.0, 1.0),
            expected_return=signal_dims.get('expected_return', 0.05),
            risk_score=signal_dims.get('risk_score', 50.0),
            
            suggested_quantity=suggested_qty,
            quantity_mode="PCT_EQUITY",
            quantity_value=suggested_qty,
            
            strategy_id=strategy_run.strategy_id,
            strategy_run_id=strategy_run.id,
            
            factor_scores=self._build_factor_scores_payload(
                signal_dims,
                new_signal_strength,
            ),
            
            account_id=strategy_run.account_id,
            user_id=strategy_run.user_id,
            
            extra_metadata=signal_extra_metadata,
            
            priority=int(new_signal_strength),
            expired_at=datetime.utcnow() + timedelta(hours=24),  # 信号24小时有效
        )
        
        self.session.add(signal)
        await self.session.commit()
        await self.session.refresh(signal)
        
        return signal
    
    def _calculate_position_size(
        self, 
        signal_strength: float, 
        risk_score: float
    ) -> float:
        """
        基于信号强度和风险评分计算仓位大小
        Kelly Criterion的简化版本
        """
        # 基础仓位: 10% - 30%
        base_size = 0.10 + (signal_strength / 100.0) * 0.20
        
        # 风险调整
        risk_adjustment = 1.0 - (risk_score / 100.0) * 0.5
        
        position_size = base_size * risk_adjustment
        return max(0.05, min(0.30, position_size))  # 限制在5%-30%

    @staticmethod
    def _safe_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def _extract_watchtower_dimension_fields(
        cls,
        signal_dims: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for key in (
            "dimensions",
            "aligned_count",
            "aligned_dims",
            "opposing_dims",
            "neutral_dims",
            "adv_usd",
            "market_cap",
            "historical_ic",
            "timing_quality",
        ):
            if signal_dims.get(key) is not None:
                payload[key] = signal_dims.get(key)
        return payload

    @classmethod
    def _build_factor_scores_payload(
        cls,
        signal_dims: Dict[str, Any],
        signal_strength: float,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "technical_score": signal_dims.get("technical_score", 70.0),
            "fundamental_score": signal_dims.get("fundamental_score", 70.0),
            "momentum_score": signal_dims.get(
                "momentum_score",
                signal_dims.get("momentum", signal_dims.get("technical_score", 70.0)),
            ),
            "sentiment_score": signal_dims.get(
                "sentiment_score",
                signal_dims.get("sentiment", 70.0),
            ),
            "macro_score": signal_dims.get("macro_score", 70.0),
            "options_score": signal_dims.get("options_score", 70.0),
            "volume_anomaly_score": signal_dims.get(
                "volume_anomaly_score",
                signal_dims.get("volume", 70.0),
            ),
            "signal_strength": signal_strength,
            "signal_dimensions": dict(signal_dims),
        }
        payload.update(cls._extract_watchtower_dimension_fields(signal_dims))
        return payload

    async def _build_quality_watchtower_context(
        self,
        signal: TradingSignal,
    ) -> Dict[str, Any]:
        from app.services.regime_classifier import RegimeClassifier
        from app.services.signal_quality_funnel import (SignalFunnelInput,
                                                        signal_quality_funnel)

        extra = self._safe_dict(signal.extra_metadata)
        factor_scores = self._safe_dict(signal.factor_scores)
        current_regime = await RegimeClassifier.get_current_regime(self.session)
        regime = (
            getattr(current_regime, "regime", None)
            or extra.get("watchtower_regime")
            or "SIDEWAYS"
        )
        confidence = float(signal.confidence or 0.0)
        composite_ratio = confidence / 100.0 if confidence > 1.0 else confidence
        aligned_dims = extra.get("aligned_dims") or factor_scores.get("aligned_dims") or []
        opposing_dims = extra.get("opposing_dims") or factor_scores.get("opposing_dims") or []
        neutral_dims = extra.get("neutral_dims") or factor_scores.get("neutral_dims") or []

        funnel_input = SignalFunnelInput(
            signal_id=getattr(signal, "id", None),
            symbol=str(signal.symbol or ""),
            direction=str(signal.direction or "LONG").upper(),
            regime=regime,
            signal_type=(
                signal.signal_type.value
                if getattr(signal, "signal_type", None)
                else "ENTRY"
            ),
            signal_strength=float(signal.signal_strength or 0.0),
            composite_score=composite_ratio,
            aligned_count=int(
                extra.get("aligned_count")
                or factor_scores.get("aligned_count")
                or 0
            ),
            aligned_dims=list(aligned_dims or []),
            opposing_dims=list(opposing_dims or []),
            neutral_dims=list(neutral_dims or []),
            adv_usd=extra.get("adv_usd") or factor_scores.get("adv_usd"),
            market_cap=extra.get("market_cap") or factor_scores.get("market_cap"),
            historical_ic=(
                extra.get("historical_ic")
                or factor_scores.get("historical_ic")
            ),
            timing_quality=(
                extra.get("timing_quality")
                or factor_scores.get("timing_quality")
            ),
        )
        profile = signal_quality_funnel.preview_quality(funnel_input)
        return {
            "regime": regime,
            "signal_quality_score": round(profile.score, 2),
            "signal_quality_tier": profile.tier,
            "signal_quality_quota_exempt": profile.quota_exempt,
            "anti_resonance_triggered": bool(
                profile.conviction and profile.conviction.anti_resonance_killed
            ),
        }

    async def _stamp_watchtower_metadata(
        self,
        signal: TradingSignal,
        *,
        stage: str,
        result: str,
        reason_code: str | None = None,
        reason_detail: str | None = None,
        rejected_at_layer: int | None = None,
        reason_category: str = "VALIDATION",
    ) -> None:
        meta = self._safe_dict(signal.extra_metadata).copy()
        meta.update(await self._build_quality_watchtower_context(signal))
        meta.update(
            {
                "watchtower_stage": stage,
                "watchtower_result": result,
                "watchtower_reason_code": reason_code,
                "watchtower_reason_detail": reason_detail,
                "watchtower_reason_category": reason_category,
                "watchtower_rejected_at_layer": rejected_at_layer,
                "watchtower_updated_at": datetime.utcnow().isoformat(),
            }
        )
        signal.extra_metadata = meta

    @staticmethod
    def _record_transition(
        meta: dict,
        *,
        from_status: str,
        to_status: str,
        reason: str | None = None,
    ) -> None:
        """P1.1: 追加一条状态流转记录到 extra_metadata["status_history"]（保留最近 20 条）。"""
        history: list = meta.get("status_history", [])
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "from": from_status,
                "to": to_status,
                "at": datetime.utcnow().isoformat(),
                "reason": reason,
            }
        )
        meta["status_history"] = history[-20:]
    
    async def validate_signal(self, signal_id: str) -> bool:
        """
        验证信号 - 风险检查和合规性检查
        """
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return False
        
        # 检查信号是否过期
        if signal.expired_at and signal.expired_at < datetime.utcnow():
            _pre_meta = self._safe_dict(signal.extra_metadata).copy()
            self._record_transition(_pre_meta, from_status=signal.status.value, to_status="EXPIRED", reason="SIGNAL_EXPIRED")
            signal.extra_metadata = _pre_meta
            signal.status = SignalStatus.EXPIRED
            await self._stamp_watchtower_metadata(
                signal,
                stage="SIGNAL_VALIDATION",
                result="REJECTED",
                reason_code="SIGNAL_EXPIRED",
                reason_detail="Signal expired before validation",
            )
            await self.session.commit()
            return False
        
        # 风险检查
        eff_state = await self.risk_svc.get_effective_state(signal.account_id)
        
        if eff_state.effective_trade_mode == TradeMode.OFF:
            _pre_meta = self._safe_dict(signal.extra_metadata).copy()
            self._record_transition(_pre_meta, from_status=signal.status.value, to_status="REJECTED", reason="TRADING_MODE_OFF")
            signal.extra_metadata = _pre_meta
            signal.status = SignalStatus.REJECTED
            signal.risk_check_passed = "NO"
            signal.risk_check_details = {"reason": "Trading mode is OFF"}
            await self._stamp_watchtower_metadata(
                signal,
                stage="SIGNAL_VALIDATION",
                result="REJECTED",
                reason_code="TRADING_MODE_OFF",
                reason_detail="Trading mode is OFF",
            )
            await self.session.commit()
            return False
        
        # 使用SafetyGuard进行详细检查
        guard = SafetyGuard(signal.account_id, eff_state.limits, self.session)
        notional = (signal.suggested_price or 100.0) * (signal.suggested_quantity or 100.0)
        
        check = await guard.check_order(signal.direction, notional)
        
        if not check.allowed:
            _pre_meta = self._safe_dict(signal.extra_metadata).copy()
            self._record_transition(_pre_meta, from_status=signal.status.value, to_status="REJECTED", reason=str(check.reason or "SafetyGuard blocked order"))
            signal.extra_metadata = _pre_meta
            signal.status = SignalStatus.REJECTED
            signal.risk_check_passed = "NO"
            signal.risk_check_details = {
                "reason": check.reason,
                "triggers": getattr(check, "triggers", [])
            }
            signal.validation_errors = {"errors": [str(check.reason)]}
            await self._stamp_watchtower_metadata(
                signal,
                stage="SIGNAL_VALIDATION",
                result="REJECTED",
                reason_code="SIGNAL_VALIDATION_BLOCKED",
                reason_detail=str(check.reason or "SafetyGuard blocked order"),
            )
            await self.session.commit()
            return False
        
        # 验证通过
        _pre_meta = self._safe_dict(signal.extra_metadata).copy()
        self._record_transition(_pre_meta, from_status=signal.status.value, to_status="VALIDATED", reason="PASSED_ALL_CHECKS")
        signal.extra_metadata = _pre_meta
        signal.status = SignalStatus.VALIDATED
        signal.risk_check_passed = "YES"
        signal.validated_at = datetime.utcnow()
        await self._stamp_watchtower_metadata(
            signal,
            stage="SIGNAL_VALIDATION",
            result="PASSED",
        )
        await self.session.commit()
        
        return True
    
    async def get_pending_signals(
        self,
        account_id: Optional[str] = None,
        status: Optional[SignalStatus] = SignalStatus.VALIDATED,
        limit: int = 20
    ) -> List[TradingSignal]:
        """获取待执行的信号(按优先级排序)"""
        
        stmt = select(TradingSignal)
        
        if status:
            stmt = stmt.where(TradingSignal.status == status)
        
        if account_id:
            stmt = stmt.where(TradingSignal.account_id == account_id)
        
        # 未过期的信号
        stmt = stmt.where(
            or_(
                TradingSignal.expired_at.is_(None),
                TradingSignal.expired_at > datetime.utcnow()
            )
        )
        
        # 按优先级和时间排序
        stmt = stmt.order_by(
            desc(TradingSignal.priority),
            TradingSignal.generated_at
        ).limit(limit)
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def update_signal_execution(
        self,
        signal_id: str,
        order_id: str,
        executed_price: float,
        executed_quantity: float
    ) -> None:
        """更新信号执行状态"""
        
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return
        
        signal.status = SignalStatus.EXECUTED
        signal.order_id = order_id
        signal.executed_at = datetime.utcnow()
        signal.executed_price = executed_price
        signal.executed_quantity = executed_quantity
        
        # 计算滑点
        if signal.suggested_price:
            slippage = (executed_price - signal.suggested_price) / signal.suggested_price
            signal.execution_slippage = slippage
        
        await self.session.commit()
    
    async def evaluate_signal_performance(
        self,
        signal_id: str,
        actual_return: float,
        pnl: float,
        holding_days: int
    ) -> None:
        """评估信号表现 - 用于反馈优化"""
        
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return
        
        signal.actual_return = actual_return
        signal.pnl = pnl
        signal.holding_days = holding_days
        
        # 计算评分(0-100)
        evaluation_score = self._calculate_evaluation_score(
            pnl_pct=actual_return,
            expected_return=signal.expected_return or 0,
            risk_score=float(signal.risk_score or 50),
            holding_days=holding_days,
        )
        
        signal.evaluation_score = evaluation_score
        
        # 生成评估说明
        if actual_return >= (signal.expected_return or 0):
            signal.evaluation_notes = f"Signal performed well: actual {actual_return:.2%} vs expected {signal.expected_return:.2%}"
        else:
            signal.evaluation_notes = f"Signal underperformed: actual {actual_return:.2%} vs expected {signal.expected_return:.2%}"
        
        await self.session.commit()
    
    async def calculate_performance_stats(
        self,
        dimension_type: str,
        dimension_value: str,
        days: int = 30
    ) -> Optional[SignalPerformance]:
        """
        计算特定维度的信号性能统计
        dimension_type: 'strategy', 'source', 'symbol', 'factor'
        """
        period_start = datetime.utcnow() - timedelta(days=days)
        period_end = datetime.utcnow()
        
        # 构建查询
        stmt = select(TradingSignal).where(
            and_(
                TradingSignal.generated_at >= period_start,
                TradingSignal.generated_at <= period_end
            )
        )
        
        if dimension_type == "strategy":
            stmt = stmt.where(TradingSignal.strategy_id == dimension_value)
        elif dimension_type == "source":
            stmt = stmt.where(TradingSignal.signal_source == dimension_value)
        elif dimension_type == "symbol":
            stmt = stmt.where(TradingSignal.symbol == dimension_value)
        
        result = await self.session.execute(stmt)
        signals = result.scalars().all()
        
        if not signals:
            return None
        
        # 计算统计指标
        total_signals = len(signals)
        executed_signals = sum(1 for s in signals if s.status == SignalStatus.EXECUTED)
        
        # 只统计已评估的信号
        evaluated_signals = [s for s in signals if s.evaluation_score is not None]
        
        if not evaluated_signals:
            return None
        
        winning_signals = sum(1 for s in evaluated_signals if s.actual_return and s.actual_return > 0)
        losing_signals = sum(1 for s in evaluated_signals if s.actual_return and s.actual_return <= 0)
        
        total_return = sum(s.actual_return or 0 for s in evaluated_signals)
        avg_return = total_return / len(evaluated_signals) if evaluated_signals else 0
        win_rate = winning_signals / len(evaluated_signals) if evaluated_signals else 0
        
        # 创建或更新性能记录
        perf = SignalPerformance(
            dimension_type=dimension_type,
            dimension_value=dimension_value,
            period_start=period_start,
            period_end=period_end,
            total_signals=total_signals,
            executed_signals=executed_signals,
            winning_signals=winning_signals,
            losing_signals=losing_signals,
            total_return=total_return,
            avg_return=avg_return,
            win_rate=win_rate,
            avg_confidence=sum(s.confidence for s in signals) / total_signals,
            avg_signal_strength=sum(s.signal_strength for s in signals) / total_signals,
            sample_size=len(evaluated_signals),
            last_calculated_at=datetime.utcnow()
        )
        
        self.session.add(perf)
        await self.session.commit()
        await self.session.refresh(perf)
        
        return perf
    
    async def update_signal_outcome(
        self,
        signal_id: str,
        exit_price: float,
        exit_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        信号平仓后更新结果（关键：标记is_winner）
        
        Args:
            signal_id: 信号ID
            exit_price: 平仓价格
            exit_time: 平仓时间（默认当前时间）
            
        Returns:
            更新结果
        """
        # 获取信号
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return {"error": "信号不存在"}
        
        if signal.status != SignalStatus.EXECUTED:
            return {"error": f"信号状态不正确: {signal.status.value}"}
        
        if not signal.executed_price or not signal.executed_quantity:
            return {"error": "缺少执行价格或数量"}
        
        # 计算盈亏
        entry_price = float(signal.executed_price)
        quantity = float(signal.executed_quantity)
        
        if signal.direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price
            pnl_amount = (exit_price - entry_price) * quantity
        else:  # SHORT
            pnl_pct = (entry_price - exit_price) / entry_price
            pnl_amount = (entry_price - exit_price) * quantity
        
        # 更新信号
        signal.pnl = pnl_amount
        signal.pnl_pct = pnl_pct
        signal.actual_return = pnl_pct
        signal.is_winner = "YES" if pnl_amount > 0 else "NO"
        
        # 计算持仓天数
        if exit_time and signal.executed_at:
            holding_days = (exit_time - signal.executed_at).days
            signal.holding_days = holding_days
        
        # 计算评估分数（综合考虑收益率、风险、持仓时间）
        signal.evaluation_score = self._calculate_evaluation_score(
            pnl_pct=pnl_pct,
            expected_return=signal.expected_return or 0.05,
            risk_score=signal.risk_score or 50,
            holding_days=signal.holding_days or 1
        )
        
        signal.updated_at = datetime.utcnow()
        
        await self.session.commit()
        await self.session.refresh(signal)
        
        return {
            "signal_id": signal_id,
            "pnl": pnl_amount,
            "pnl_pct": pnl_pct,
            "is_winner": signal.is_winner,
            "evaluation_score": signal.evaluation_score,
            "message": "信号结果已更新"
        }
    
    def _calculate_evaluation_score(
        self,
        pnl_pct: float,
        expected_return: float,
        risk_score: float,
        holding_days: int
    ) -> float:
        """
        计算信号评估分数（0-100）
        
        评分维度：
        1. 实际vs预期收益（40%权重）
        2. 风险调整收益（30%权重）
        3. 时间效率（30%权重）
        """
        # 1. 收益达成度（0-40分）
        if expected_return > 0:
            return_achievement = min(pnl_pct / expected_return, 2.0)  # 最多2倍
        else:
            return_achievement = 1.0 if pnl_pct > 0 else 0.0
        
        return_score = return_achievement * 40
        
        # 2. 风险调整收益（0-30分）
        # 风险越高，要求收益越高
        required_return_for_risk = risk_score / 1000  # 50分风险要求5%收益
        if pnl_pct > required_return_for_risk:
            risk_adjusted_score = 30
        else:
            risk_adjusted_score = (pnl_pct / required_return_for_risk) * 30 if required_return_for_risk > 0 else 0
        
        # 3. 时间效率（0-30分）
        # 持仓时间越短越好（假设目标是5天）
        target_days = 5
        if holding_days <= target_days:
            time_score = 30
        else:
            time_score = max(0, 30 - (holding_days - target_days) * 2)
        
        # 总分
        total_score = return_score + risk_adjusted_score + time_score
        
        # 如果亏损，大幅降分
        if pnl_pct < 0:
            total_score = min(total_score, 30)  # 亏损最多30分
        
        return max(0, min(100, total_score))
    
    async def batch_update_signal_outcomes(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """
        批量更新所有已执行但未评估的信号结果
        （需要从持仓历史或订单记录中获取平仓信息）
        
        Returns:
            更新统计
        """
        # 获取已执行但未评估的信号
        stmt = (
            select(TradingSignal)
            .where(
                and_(
                    TradingSignal.account_id == account_id,
                    TradingSignal.status == SignalStatus.EXECUTED,
                    TradingSignal.is_winner.is_(None)  # 未评估
                )
            )
        )
        
        result = await self.session.execute(stmt)
        signals = result.scalars().all()
        
        if not signals:
            return {
                "total_signals": 0,
                "updated": 0,
                "message": "没有待更新的信号"
            }
        
        updated_count = 0
        
        # TODO: 这里需要从broker获取持仓历史来判断是否已平仓及平仓价格
        # 当前简化处理：如果持仓时间超过max_holding_days，标记为过期
        
        for signal in signals:
            if signal.executed_at:
                days_held = (datetime.utcnow() - signal.executed_at).days
                
                # 如果超过最大持仓天数且未平仓，标记为过期
                if signal.max_holding_days and days_held > signal.max_holding_days:
                    signal.status = SignalStatus.EXPIRED
                    signal.evaluation_notes = f"超过最大持仓天数({signal.max_holding_days}天)未平仓"
                    updated_count += 1
        
        if updated_count > 0:
            await self.session.commit()
        
        return {
            "total_signals": len(signals),
            "updated": updated_count,
            "message": f"已更新{updated_count}个信号"
        }

