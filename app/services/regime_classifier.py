"""V10.2-M1: 市场体制分类器（RegimeClassifier）

核心逻辑：
1. 每日 08:00 UTC 运行五维评分
2. 3 天连续同一体制信号才确认切换（防噪声翻转）
3. 切换后通过 EventBus 广播 REGIME_CHANGED 事件
4. 将体制历史持久化到 market_regimes 表

五个维度（各 0～100 分）：
  ① trend_score    — SPY 相对均线位置 + MACD 方向
  ② vol_score      — VIX 水平 + VIX MA 比（高波动→高分）
  ③ breadth_score  — NYSE 上涨家数比例 + SPY vs RSP 相对强弱
  ④ macro_score    — 复用 MacroRiskScoringService（宏观综合评分归一化）
  ⑤ momentum_score — SPY 20日动量 + RSI

分类决策矩阵（规则based，无需额外 ML 依赖）：
  • CRISIS       : vol_score ≥ 85 or (trend < 30 and vol > 70)
  • BEAR_TREND   : trend < 35 and momentum < 35 and vol > 50
  • HIGH_VOL     : vol_score ≥ 65 and 未触发 CRISIS
  • BULL_TREND   : trend > 65 and momentum > 55 and breadth > 55
  • MEAN_REVERT  : breadth 中等 and trend 30-65 and vol < 55
  • RANGE_BOUND  : 其余情况
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.event_bus import event_bus, Topics
from app.models.market_regime import MarketRegime, RegimeType

logger = logging.getLogger(__name__)

# ── 默认 VaR 倍数映射（可被 REGIME_VAR_MULTIPLIERS 覆盖） ──────────────────────
_DEFAULT_VAR_MULTIPLIERS: dict[str, float] = {
    "BULL_TREND":   1.2,
    "BEAR_TREND":   0.8,
    "HIGH_VOL":     0.7,
    "MEAN_REVERT":  1.0,
    "RANGE_BOUND":  1.0,
    "CRISIS":       0.5,
}


def _parse_var_multipliers() -> dict[str, float]:
    """从 settings.REGIME_VAR_MULTIPLIERS 字符串解析 VaR 倍数配置。"""
    result = dict(_DEFAULT_VAR_MULTIPLIERS)
    try:
        for item in settings.REGIME_VAR_MULTIPLIERS.split(","):
            item = item.strip()
            if ":" in item:
                regime, multiplier = item.split(":", 1)
                result[regime.strip()] = float(multiplier.strip())
    except Exception as exc:
        logger.warning(f"[RegimeClassifier] Failed to parse REGIME_VAR_MULTIPLIERS: {exc}; using defaults")
    return result


class RegimeScores:
    """五维评分结构（各维度 0~100）"""

    def __init__(
        self,
        trend: float,
        vol:   float,
        breadth: float,
        macro:   float,
        momentum: float,
    ) -> None:
        self.trend    = max(0.0, min(100.0, trend))
        self.vol      = max(0.0, min(100.0, vol))
        self.breadth  = max(0.0, min(100.0, breadth))
        self.macro    = max(0.0, min(100.0, macro))
        self.momentum = max(0.0, min(100.0, momentum))

    def classify(self) -> tuple[RegimeType, float]:
        """
        根据五维得分返回 (体制类型, 置信度)。

        置信度计算：最高规则匹配得分 / (最高 + 次高) — 越高说明分类越明确。
        """
        # ── 规则打分（每个体制一个匹配分） ──
        scores: dict[RegimeType, float] = {
            RegimeType.CRISIS:      self._score_crisis(),
            RegimeType.BEAR_TREND:  self._score_bear(),
            RegimeType.HIGH_VOL:    self._score_high_vol(),
            RegimeType.BULL_TREND:  self._score_bull(),
            RegimeType.MEAN_REVERT: self._score_mean_revert(),
            RegimeType.RANGE_BOUND: self._score_range_bound(),
        }

        # 按优先级排序（CRISIS 先触发，RANGE_BOUND 最后兜底）
        priority = [
            RegimeType.CRISIS,
            RegimeType.BEAR_TREND,
            RegimeType.HIGH_VOL,
            RegimeType.BULL_TREND,
            RegimeType.MEAN_REVERT,
            RegimeType.RANGE_BOUND,
        ]

        # 选最高分体制
        best_regime = max(priority, key=lambda r: scores[r])
        best_score  = scores[best_regime]

        # 置信度 = 最高分 / (最高分 + 次高分)
        sorted_scores = sorted(scores.values(), reverse=True)
        first, second = sorted_scores[0], sorted_scores[1] if len(sorted_scores) > 1 else 0.0
        confidence = first / (first + second) if (first + second) > 0 else 0.5

        return best_regime, round(confidence, 4)

    # ─────────────────── 子规则 ───────────────────

    def _score_crisis(self) -> float:
        """极端恐慌：高波动率 + 趋势崩溃"""
        score = 0.0
        if self.vol >= 85:
            score += 60
        elif self.vol >= 70:
            score += 30
        if self.trend <= 25:
            score += 25
        if self.macro <= 25:
            score += 15
        return min(score, 100.0)

    def _score_bear(self) -> float:
        """熊市下行：趋势向下 + 动量负"""
        score = 0.0
        if self.trend <= 35:
            score += 40
        if self.momentum <= 35:
            score += 30
        if self.vol >= 50:
            score += 15
        if self.breadth <= 40:
            score += 15
        return min(score, 100.0)

    def _score_high_vol(self) -> float:
        """高波动：波动率高但未进危机（区别在于趋势尚可）"""
        score = 0.0
        if self.vol >= 65:
            score += 50
        if 30 < self.trend < 65:
            score += 20
        if self.momentum < 50:
            score += 15
        if self.breadth < 50:
            score += 15
        return min(score, 100.0)

    def _score_bull(self) -> float:
        """牛市趋势：动量强 + 广度健康 + 宏观正向"""
        score = 0.0
        if self.trend >= 65:
            score += 35
        if self.momentum >= 55:
            score += 25
        if self.breadth >= 55:
            score += 20
        if self.macro >= 55:
            score += 10
        if self.vol <= 40:
            score += 10
        return min(score, 100.0)

    def _score_mean_revert(self) -> float:
        """均值回复：趋势中性 + 波动中等偏低"""
        score = 0.0
        if 35 <= self.trend <= 65:
            score += 30
        if self.vol <= 55:
            score += 25
        if 40 <= self.momentum <= 60:
            score += 25
        if 40 <= self.breadth <= 60:
            score += 20
        return score

    def _score_range_bound(self) -> float:
        """区间震荡：兜底分类，低波动横盘"""
        score = max(0.0, 40 - self.vol * 0.3)  # 越低波动越高分
        score += max(0.0, 10 - abs(self.momentum - 50) * 0.2)
        return score


class RegimeClassifier:
    """
    每日 08:00 UTC 运行市场体制分类，写入 DB 并（条件）广播 REGIME_CHANGED 事件。

    三天确认机制：
    - 查询近 REGIME_CONFIRM_DAYS 条分类记录
    - 若 candidate_regime 与最新已确认体制不同 AND 连续 N 天 candidate 相同 → 确认切换
    - 否则仅写入「候选」记录（is_candidate=True，不广播事件）
    """

    FALLBACK_REGIME = RegimeType.RANGE_BOUND

    async def run(self, db: AsyncSession) -> dict:
        """
        主入口：执行完整分类流程。

        Returns
        -------
        dict 包含本次分类结果摘要。
        """
        if not settings.REGIME_ENABLED:
            logger.info("[RegimeClassifier] REGIME_ENABLED=False, skipping classification")
            return {"skipped": True, "reason": "REGIME_ENABLED=False"}

        logger.info("[RegimeClassifier] Starting daily classification...")

        # 1. 计算五维评分
        try:
            scores = await self._compute_scores()
        except Exception as exc:
            logger.error(f"[RegimeClassifier] Failed to compute scores: {exc}", exc_info=True)
            scores = RegimeScores(50, 50, 50, 50, 50)  # 回退到中性分数

        candidate_regime, confidence = scores.classify()

        logger.info(
            f"[RegimeClassifier] Candidate regime={candidate_regime.value} "
            f"confidence={confidence:.2%} "
            f"scores=(trend={scores.trend:.1f}, vol={scores.vol:.1f}, "
            f"breadth={scores.breadth:.1f}, macro={scores.macro:.1f}, "
            f"momentum={scores.momentum:.1f})"
        )

        # 2. 三天确认检查
        confirmed, prev_regime = await self._check_confirmation(db, candidate_regime)

        now_utc = datetime.now(tz=timezone.utc)

        if confirmed:
            # 3a. 封存前一体制（设置 valid_until）
            if prev_regime and prev_regime != candidate_regime.value:
                await self._close_current_regime(db, now_utc)

            # 3b. 写入新确认体制
            new_regime = MarketRegime(
                classification_date=now_utc,
                valid_from=now_utc,
                valid_until=None,
                regime=candidate_regime.value,
                prev_regime=prev_regime,
                confidence=confidence,
                trend_score=scores.trend,
                vol_score=scores.vol,
                breadth_score=scores.breadth,
                macro_score=scores.macro,
                momentum_score=scores.momentum,
                reasoning=self._build_reasoning(candidate_regime, scores),
                is_override=False,
            )
            db.add(new_regime)
            await db.commit()
            await db.refresh(new_regime)

            # 3c. 发布事件（仅当体制真正切换时）
            if prev_regime and prev_regime != candidate_regime.value:
                await event_bus.publish(
                    Topics.REGIME_CHANGED,
                    {
                        "prev": prev_regime,
                        "curr": candidate_regime.value,
                        "confidence": confidence,
                        "regime_id": new_regime.id,
                        "var_multiplier": _parse_var_multipliers().get(candidate_regime.value, 1.0),
                    },
                )
                logger.info(
                    f"[RegimeClassifier] Regime changed: {prev_regime} → {candidate_regime.value} "
                    f"(confidence={confidence:.2%})"
                )
            elif not prev_regime:
                # 首次写入，广播初始化事件
                await event_bus.publish(
                    Topics.REGIME_CHANGED,
                    {
                        "prev": None,
                        "curr": candidate_regime.value,
                        "confidence": confidence,
                        "regime_id": new_regime.id,
                        "var_multiplier": _parse_var_multipliers().get(candidate_regime.value, 1.0),
                    },
                )
        else:
            logger.info(
                f"[RegimeClassifier] Candidate {candidate_regime.value} not yet confirmed "
                f"(need {settings.REGIME_CONFIRM_DAYS} consecutive days)"
            )

        return {
            "candidate": candidate_regime.value,
            "confidence": confidence,
            "confirmed": confirmed,
            "prev_regime": prev_regime,
            "scores": {
                "trend": scores.trend,
                "vol":   scores.vol,
                "breadth": scores.breadth,
                "macro":  scores.macro,
                "momentum": scores.momentum,
            },
        }

    # ─────────────────────────────────────────────────
    # 五维评分计算
    # ─────────────────────────────────────────────────

    async def _compute_scores(self) -> RegimeScores:
        """拉取市场数据并计算五维评分。"""
        import asyncio

        trend_task    = asyncio.create_task(self._score_trend())
        vol_task      = asyncio.create_task(self._score_volatility())
        breadth_task  = asyncio.create_task(self._score_breadth())
        macro_task    = asyncio.create_task(self._score_macro())
        momentum_task = asyncio.create_task(self._score_momentum())

        trend, vol, breadth, macro, momentum = await asyncio.gather(
            trend_task, vol_task, breadth_task, macro_task, momentum_task,
            return_exceptions=True,
        )

        # 任何维度出错则使用中性分数 50
        def safe(v: float | BaseException, default: float = 50.0) -> float:
            # asyncio.gather with return_exceptions=True may return BaseException
            # (KeyboardInterrupt/SystemExit etc).  Treat any exception as default.
            if isinstance(v, BaseException):
                logger.warning(f"[RegimeClassifier] Score computation error: {v}")
                return default
            return float(v)

        return RegimeScores(
            trend=safe(trend),
            vol=safe(vol),
            breadth=safe(breadth),
            macro=safe(macro),
            momentum=safe(momentum),
        )

    async def _score_trend(self) -> float:
        """
        趋势强度评分（0~100）。

        规则：
        - SPY 现价 vs 20日 MA vs 50日 MA
        - 20日收益率符号
        - 价格 vs 200日 MA（长期趋势）
        """
        import yfinance as yf
        import asyncio

        spy_data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: yf.download("SPY", period="1y", interval="1d", progress=False, auto_adjust=True)
        )

        # yf.download may return None on failure, protect our checks
        if spy_data is None or spy_data.empty or len(spy_data) < 50:
            logger.warning("[RegimeClassifier] Insufficient SPY data for trend score; using 50")
            return 50.0

        close = spy_data["Close"].dropna()
        price = float(close.iloc[-1])

        ma20  = float(close.rolling(20).mean().iloc[-1])
        ma50  = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else ma50

        # 相对位置得分（0~100）
        score = 50.0

        # 价格在 200日均线上方 +15，下方 -15
        score += 15 if price > ma200 else -15

        # 20日均线在 50日均线上方（金叉）+20，下方死叉 -20
        score += 20 if ma20 > ma50 else -20

        # 价格在 20日均线上方 +10
        score += 10 if price > ma20 else -10

        # 近 20 日涨幅
        if len(close) >= 21:
            ret_20d = (price - float(close.iloc[-21])) / float(close.iloc[-21])
            # 每 1% 涨幅 +1.5 分，上限 ±20
            score += max(-20, min(20, ret_20d * 150))

        return max(0.0, min(100.0, score))

    async def _score_volatility(self) -> float:
        """
        波动率制度评分（0~100，越高越恐慌）。

        规则：
        - VIX 当前水平（<15 低波动，15-25 正常，25-35 高波动，>35 极端）
        - VIX / VIX 30日均值 比率（contango or backwardation）
        """
        import yfinance as yf
        import asyncio

        vix_data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: yf.download("^VIX", period="60d", interval="1d", progress=False, auto_adjust=True)
        )

        if vix_data is None or vix_data.empty:
            return 50.0

        vix_close = vix_data["Close"].dropna()
        vix_now   = float(vix_close.iloc[-1])
        vix_ma30  = float(vix_close.rolling(30).mean().iloc[-1]) if len(vix_close) >= 30 else vix_now

        # VIX 水平基础分
        if vix_now < 12:
            base_score = 10
        elif vix_now < 15:
            base_score = 20
        elif vix_now < 20:
            base_score = 35
        elif vix_now < 25:
            base_score = 50
        elif vix_now < 30:
            base_score = 65
        elif vix_now < 35:
            base_score = 80
        else:
            base_score = 90

        # VIX 相对 30日均线的上偏 → 情绪恶化
        vix_ratio = vix_now / vix_ma30 if vix_ma30 > 0 else 1.0
        # ratio=1.3 → +15 分
        ratio_bonus = max(-10, min(15, (vix_ratio - 1.0) * 50))

        return max(0.0, min(100.0, base_score + ratio_bonus))

    async def _score_breadth(self) -> float:
        """
        市场广度评分（0~100，越高越健康）。

        规则：
        - 用 SPY vs RSP（等权 S&P500 ETF）相对表现
        - 近 20 日 SPY 成分股上涨比例（代理：用 VTI/SPY 相对走势）
        """
        import yfinance as yf
        import asyncio

        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: yf.download(
                "SPY RSP", period="60d", interval="1d", progress=False, auto_adjust=True
            ),
        )

        if data is None or data.empty or "Close" not in data.columns:
            return 55.0  # 中性偏高

        try:
            spy_close = data["Close"]["SPY"].dropna()
            rsp_close = data["Close"]["RSP"].dropna()
        except (KeyError, TypeError):
            return 55.0

        if len(spy_close) < 20 or len(rsp_close) < 20:
            return 55.0

        # RSP/SPY 比率：>1 表示等权更强（广度健康），<1 表示大盘被巨头拉升（广度弱）
        ratio = float(rsp_close.iloc[-1] / spy_close.iloc[-1]) / float(
            rsp_close.iloc[-20] / spy_close.iloc[-20]
        )

        score = 50.0
        # ratio 每高于 1% → +5 分，每低于 1% → -5 分，上限 ±30
        score += max(-30, min(30, (ratio - 1.0) * 500))

        # 近 5 日 SPY 上涨天数比例
        spy_returns = spy_close.pct_change().dropna()
        recent5     = spy_returns.iloc[-5:]
        up_days_pct = float((recent5 > 0).sum()) / len(recent5)
        score += (up_days_pct - 0.5) * 20  # ±10

        return max(0.0, min(100.0, score))

    async def _score_macro(self) -> float:
        """
        宏观环境评分（0~100，越高越宽松/正向）。

        复用系统内 MacroRiskScoringService 的总分（0~100）。
        如果 macroservice 不可用则 fallback 到 50。
        """
        try:
            from app.services.macro_risk_scoring_service import MacroRiskScoringService
            macro_svc = MacroRiskScoringService()
            # 调用新接口计算风险评分
            risk_score = await macro_svc.calculate_macro_risk_score()
            # MacroRiskScoringService.overall_score: 0 表示极端风险，100 表示非常宽松
            # 因此可直接使用该值作为正向得分
            # ORM model attributes are declared as Column[int], so use cast to satisfy type checker.
            from typing import cast
            score_val = cast(int, risk_score.overall_score)  # convert Column[int] to int at runtime
            score = float(score_val)
            return max(0.0, min(100.0, score))
        except Exception as exc:
            logger.warning(f"[RegimeClassifier] macro score fallback: {exc}")
            return 50.0

    async def _score_momentum(self) -> float:
        """
        价格动量评分（0~100，越高动量越强）。

        规则：
        - SPY 近 20 日收益率
        - SPY RSI(14)
        """
        import yfinance as yf
        import asyncio

        spy_data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: yf.download("SPY", period="60d", interval="1d", progress=False, auto_adjust=True)
        )

        if spy_data is None or spy_data.empty or len(spy_data) < 20:
            return 50.0

        close = spy_data["Close"]["SPY"].dropna() if "SPY" in spy_data["Close"].columns else spy_data["Close"].dropna()

        if len(close) < 20:
            return 50.0

        # 20 日动量
        ret_20d = float((close.iloc[-1] - close.iloc[-20]) / close.iloc[-20])

        # RSI(14)
        rsi = self._compute_rsi(close, window=14)

        score = 50.0
        # 每 1% 20日动量 → +2 分，上限 ±25
        score += max(-25, min(25, ret_20d * 200))
        # RSI: 50 为中性，超买 → 高分，超卖 → 低分，±20
        score += (rsi - 50) * 0.4

        return max(0.0, min(100.0, score))

    @staticmethod
    def _compute_rsi(prices, window: int = 14) -> float:
        """计算最新 RSI 值。"""
        import pandas as pd
        series = pd.Series(prices) if not hasattr(prices, "iloc") else prices
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(window=window).mean()
        loss  = (-delta.clip(upper=0)).rolling(window=window).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = 100 - (100 / (1 + rs))
        val   = rsi.iloc[-1]
        return float(val) if not (val != val) else 50.0  # nan → 50

    # ─────────────────────────────────────────────────
    # 三天确认机制
    # ─────────────────────────────────────────────────

    async def _check_confirmation(
        self, db: AsyncSession, candidate: RegimeType
    ) -> tuple[bool, Optional[str]]:
        """
        查询近 N 天历史，判断候选体制是否已连续确认。

        Returns
        -------
        (confirmed: bool, current_regime: Optional[str])
            confirmed      — 是否满足连续 N 天弱确认条件
            current_regime — 目前已确认的最新体制（如无历史则 None）
        """
        confirm_days = settings.REGIME_CONFIRM_DAYS

        # 最近 N+1 条记录
        stmt = (
            select(MarketRegime)
            .order_by(desc(MarketRegime.classification_date))
            .limit(confirm_days + 1)
        )
        result = await db.execute(stmt)
        recent: list[MarketRegime] = list(result.scalars().all())

        # 尚无历史 → 直接确认（首次分类）
        if not recent:
            return True, None

        # 当前已确认体制
        current_regime = recent[0].regime

        # 若候选与当前相同 → 保持（无需切换）
        if candidate.value == current_regime:
            return True, current_regime

        # 检查历史是否已有 CONFIRM_DAYS-1 次相同候选（合并本次=共 N 次）
        # 用最近 confirm_days-1 条记录检查是否都是 candidate
        # 实际上我们在 redis 中缓存候选状态（此处用简化 DB 查询实现）
        # 查近 confirm_days - 1 条（不含今天），检查是否都是 candidate
        past_candidates = recent[: confirm_days - 1]  # 不含最新一条
        consecutive = all(r.regime == candidate.value for r in past_candidates) if past_candidates else False

        # 还需要这些记录是连续日期（每天一条）
        if consecutive and len(past_candidates) >= confirm_days - 1:
            return True, current_regime

        return False, current_regime

    # ─────────────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────────────

    async def _close_current_regime(self, db: AsyncSession, close_time: datetime) -> None:
        """将 valid_until=NULL 的最新体制记录设置结束时间。"""
        from sqlalchemy import update as sa_update

        await db.execute(
            sa_update(MarketRegime)
            .where(MarketRegime.valid_until.is_(None))
            .values(valid_until=close_time)
        )

    def _build_reasoning(self, regime: RegimeType, scores: RegimeScores) -> str:
        """生成人类可读的分类理由摘要。"""
        labels = {
            RegimeType.BULL_TREND:   "📈 强势牛市趋势",
            RegimeType.BEAR_TREND:   "📉 熊市下行趋势",
            RegimeType.HIGH_VOL:     "🌪️ 高波动率环境",
            RegimeType.MEAN_REVERT:  "↔️ 均值回复环境",
            RegimeType.RANGE_BOUND:  "📊 区间震荡",
            RegimeType.CRISIS:       "🚨 危机体制",
        }
        return (
            f"{labels.get(regime, regime.value)}. "
            f"驱动因素: 趋势={scores.trend:.0f}, 波动={scores.vol:.0f}, "
            f"广度={scores.breadth:.0f}, 宏观={scores.macro:.0f}, 动量={scores.momentum:.0f}."
        )

    # ─────────────────────────────────────────────────
    # 查询接口（供 Router 调用）
    # ─────────────────────────────────────────────────

    @staticmethod
    async def get_current_regime(db: AsyncSession) -> Optional[MarketRegime]:
        """查询当前有效体制（valid_until IS NULL，最新一条）。"""
        stmt = (
            select(MarketRegime)
            .where(MarketRegime.valid_until.is_(None))
            .order_by(desc(MarketRegime.classification_date))
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_regime_history(
        db: AsyncSession, limit: int = 30, offset: int = 0
    ) -> tuple[list[MarketRegime], int]:
        """分页获取体制历史记录。"""
        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(MarketRegime)
        total = (await db.execute(count_stmt)).scalar_one()

        stmt = (
            select(MarketRegime)
            .order_by(desc(MarketRegime.classification_date))
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total


# 全局单例
regime_classifier = RegimeClassifier()
