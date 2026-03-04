"""
宏观风险评分服务

根据 MODULE_4 设计实现：
- 计算5维度宏观风险评分（货币政策、地缘政治、行业泡沫、经济周期、市场情绪）
- 综合风险等级判定（LOW/MEDIUM/HIGH/EXTREME）
- 风险预警生成
- 6小时数据缓存
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
import asyncio
import logging
import random
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import yfinance as yf

from app.models.macro_risk import MacroRiskScore, GeopoliticalEvent
from app.services.api_monitoring_service import api_monitor, APIProvider, APIRateLimit

logger = logging.getLogger(__name__)


# 延迟导入避免循环依赖
def _get_session():
    from app.models.db import SessionLocal
    return SessionLocal()


class RiskLevel(str, Enum):
    """风险等级枚举"""
    LOW = "LOW"           # 低风险 (80-100分)
    MEDIUM = "MEDIUM"     # 中等风险 (60-79分)
    HIGH = "HIGH"         # 高风险 (40-59分)
    EXTREME = "EXTREME"   # 极端风险 (0-39分)


class MacroRiskScoringService:
    """宏观风险评分服务"""
    
    # 5个维度的权重配置
    WEIGHT_MONETARY_POLICY = 0.30   # 货币政策 30%
    WEIGHT_GEOPOLITICAL = 0.20      # 地缘政治 20%
    WEIGHT_SECTOR_BUBBLE = 0.20     # 行业泡沫 20%
    WEIGHT_ECONOMIC_CYCLE = 0.20    # 经济周期 20%
    WEIGHT_MARKET_SENTIMENT = 0.10  # 市场情绪 10%
    
    def __init__(self):
        self.cache_duration = timedelta(hours=24)  # 延长到24小时减少API调用
        self.max_retries = 2  # 最大重试次数
        self.retry_delay = 5.0  # 重试延迟（秒）
        self.request_delay = 1.0  # 请求间延迟（秒）
        self.retry_backoff_cap = 20.0  # 重试最大等待（秒）
        self.jitter_ratio = 0.3  # 抖动比例
        self._last_market_shock_snapshot: Optional[Dict[str, Any]] = None

    async def get_market_shock_snapshot(self) -> Dict[str, Any]:
        """获取市场体感校准快照（用于前端解释展示）。"""
        if self._last_market_shock_snapshot:
            return self._last_market_shock_snapshot

        penalty = await self._calculate_with_retry(
            self._calculate_market_shock_penalty,
            "market_shock_penalty_snapshot",
            0.0,
            provider=APIProvider.YAHOO_FINANCE
        )

        if self._last_market_shock_snapshot:
            return self._last_market_shock_snapshot

        return {
            "enabled": True,
            "window": "5d",
            "penalty": round(float(penalty or 0.0), 2),
            "regime": "NEUTRAL",
            "factors": {
                "vix_change_pct": 0.0,
                "oil_change_pct": 0.0,
                "dxy_change_pct": 0.0,
            },
            "drivers": [],
        }
    
    async def calculate_macro_risk_score(self, use_cache: bool = True) -> MacroRiskScore:
        """
        计算宏观风险评分
        
        Args:
            use_cache: 是否使用缓存
            
        Returns:
            MacroRiskScore: 完整的风险评分对象
        """
        async with _get_session() as session:
            # 1. 检查缓存
            if use_cache:
                cached = await self._get_cached_risk_score(session)
                if cached and (datetime.now() - cached.timestamp) < self.cache_duration:
                    return cached
            
            # 2. 计算所有维度评分
            dimension_scores = await self._calculate_all_risk_scores(session)
            
            # 3. 计算综合评分
            overall_score = self._calculate_overall_risk_score(
                dimension_scores["monetary_policy"],
                dimension_scores["geopolitical"],
                dimension_scores["sector_bubble"],
                dimension_scores["economic_cycle"],
                dimension_scores["market_sentiment"]
            )
            
            # 4. 判定风险等级
            risk_level = self._determine_risk_level(overall_score)
            
            # 5. 生成风险摘要
            risk_summary = self._generate_risk_summary(overall_score, dimension_scores)
            key_concerns = self._generate_key_concerns(dimension_scores)
            
            # 6. 创建风险评分对象
            risk_score = MacroRiskScore(
                timestamp=datetime.now(),
                monetary_policy_score=int(dimension_scores["monetary_policy"]),
                geopolitical_score=int(dimension_scores["geopolitical"]),
                sector_bubble_score=int(dimension_scores["sector_bubble"]),
                economic_cycle_score=int(dimension_scores["economic_cycle"]),
                sentiment_score=int(dimension_scores["market_sentiment"]),
                overall_score=int(overall_score),
                risk_level=risk_level.value,
                risk_summary=risk_summary,
                key_concerns=json.dumps(key_concerns, ensure_ascii=False),
                recommendations=self._generate_recommendations(risk_level, dimension_scores),
                data_sources="FRED, yfinance, geopolitical_events",
                confidence=self._calculate_confidence(dimension_scores)
            )
            
            # 7. 保存到数据库
            session.add(risk_score)
            await session.commit()
            await session.refresh(risk_score)
            
            return risk_score
    
    async def generate_risk_alerts(self) -> List[Dict[str, Any]]:
        """
        生成风险预警列表
        
        Returns:
            风险预警字典列表
        """
        risk_score = await self.calculate_macro_risk_score(use_cache=True)
        
        alerts = []
        
        # 整体风险预警
        if risk_score.overall_score < 40:
            alerts.append({
                "level": "CRITICAL",
                "type": "OVERALL_RISK",
                "message": f"综合宏观风险评分{risk_score.overall_score}，处于极端风险区间，强烈建议降低仓位",
                "score": risk_score.overall_score
            })
        elif risk_score.overall_score < 60:
            alerts.append({
                "level": "WARNING",
                "type": "OVERALL_RISK",
                "message": f"综合宏观风险评分{risk_score.overall_score}，处于高风险区间，建议谨慎操作",
                "score": risk_score.overall_score
            })
        
        # 各维度风险预警
        dimension_alerts = [
            ("monetary_policy_score", "货币政策", "MONETARY"),
            ("geopolitical_score", "地缘政治", "GEOPOLITICAL"),
            ("sector_bubble_score", "行业泡沫", "SECTOR_BUBBLE"),
            ("economic_cycle_score", "经济周期", "ECONOMIC_CYCLE"),
            ("sentiment_score", "市场情绪", "SENTIMENT")
        ]
        
        for field, name, alert_type in dimension_alerts:
            score = getattr(risk_score, field)
            if score < 30:
                alerts.append({
                    "level": "CRITICAL",
                    "type": alert_type,
                    "message": f"{name}风险评分{score}，存在极端风险",
                    "score": score
                })
            elif score < 50:
                alerts.append({
                    "level": "WARNING",
                    "type": alert_type,
                    "message": f"{name}风险评分{score}，风险偏高，需要关注",
                    "score": score
                })
        
        return alerts
    
    async def get_latest_risk_score(self) -> Optional[MacroRiskScore]:
        """
        获取最新的风险评分
        
        Returns:
            最新的MacroRiskScore对象，如果不存在则返回None
        """
        async with _get_session() as session:
            return await self._get_cached_risk_score(session)
    
    # ============= 私有方法：风险评分计算 =============
    
    async def _calculate_with_retry(
        self,
        calc_func,
        dimension_name: str,
        fallback_value: float,
        provider: Optional[APIProvider] = None
    ) -> float:
        """
        带重试机制的计算函数
        
        Args:
            calc_func: 计算函数
            dimension_name: 维度名称
            fallback_value: 回退值（来自缓存或默认值）
        
        Returns:
            计算结果或回退值
        """
        if provider:
            gate = await api_monitor.can_call_provider(provider)
            if not gate.get("can_call", True):
                logger.warning(
                    f"Skipping {dimension_name} due to cooldown/limit: {gate.get('reason') or 'blocked'}"
                )
                return fallback_value

        for attempt in range(self.max_retries):
            try:
                result = await calc_func()
                if result is not None:
                    return result
                if attempt < self.max_retries - 1:
                    await self._sleep_backoff(attempt)
                    continue
            except Exception as e:
                error_msg = str(e)
                if self._is_rate_limit_error(error_msg):
                    if provider:
                        await api_monitor.set_cooldown(
                            provider, APIRateLimit.DEFAULT_COOLDOWN_SECONDS, error_msg
                        )
                    logger.warning(
                        f"Rate limited for {dimension_name}, using fallback value: {fallback_value}"
                    )
                    break
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"Error calculating {dimension_name}: {error_msg}. Retrying..."
                    )
                    await self._sleep_backoff(attempt)
                    continue
                logger.error(f"Error calculating {dimension_name}: {error_msg}")
                break
        
        # 所有重试失败，使用回退值
        logger.info(f"Using fallback value for {dimension_name}: {fallback_value}")
        return fallback_value
    
    async def _calculate_all_risk_scores(self, session: AsyncSession) -> Dict[str, float]:
        """
        计算所有维度的风险评分（带延迟和错误恢复）
        
        Returns:
            各维度评分字典
        """
        # 首先尝试从缓存加载，失败的维度使用缓存值
        cached = await self._get_cached_risk_score(session)
        
        # 地缘政治维度不依赖外部API，优先计算
        geopolitical = await self._calculate_geopolitical_risk(session)
        await self._sleep_request_delay()
        
        # 其他维度依赖yfinance，需要错误处理
        monetary = await self._calculate_with_retry(
            self._calculate_monetary_policy_risk,
            "monetary_policy",
            cached.monetary_policy_score if cached else 65.0,
            provider=APIProvider.YAHOO_FINANCE
        )
        await self._sleep_request_delay()
        
        sector_bubble = await self._calculate_with_retry(
            self._calculate_sector_bubble_risk,
            "sector_bubble",
            cached.sector_bubble_score if cached else 60.0,
            provider=APIProvider.YAHOO_FINANCE
        )
        await self._sleep_request_delay()
        
        economic_cycle = await self._calculate_with_retry(
            self._calculate_economic_cycle_risk,
            "economic_cycle",
            cached.economic_cycle_score if cached else 65.0,
            provider=APIProvider.YAHOO_FINANCE
        )
        await self._sleep_request_delay()
        
        market_sentiment = await self._calculate_with_retry(
            self._calculate_market_sentiment_risk,
            "market_sentiment",
            cached.sentiment_score if cached else 65.0,
            provider=APIProvider.YAHOO_FINANCE
        )

        # 市场体感校准层：当跨资产出现同步风险冲击时，温和下调相关维度评分
        shock_penalty = await self._calculate_with_retry(
            self._calculate_market_shock_penalty,
            "market_shock_penalty",
            0.0,
            provider=APIProvider.YAHOO_FINANCE
        )

        if shock_penalty > 0:
            monetary = max(0.0, monetary - shock_penalty * 0.5)
            geopolitical = max(0.0, geopolitical - shock_penalty * 0.35)
            market_sentiment = max(0.0, market_sentiment - shock_penalty * 0.7)
        
        return {
            "monetary_policy": monetary,
            "geopolitical": geopolitical,
            "sector_bubble": sector_bubble,
            "economic_cycle": economic_cycle,
            "market_sentiment": market_sentiment
        }

    async def _calculate_market_shock_penalty(self) -> float:
        """
        计算市场冲击惩罚项（0-20）。

        目的：在“战争升级/避险升温/降息预期降温”这类快速再定价阶段，
        让宏观评分更贴近盘面体感。

        使用代理指标：
        - VIX（^VIX）5日变化：恐慌上升
        - 原油（CL=F）5日变化：地缘与通胀再抬头风险
        - 美元指数（DX-Y.NYB）5日变化：全球避险与流动性收紧压力
        """
        start_time = datetime.now()
        success = False
        error_msg = None
        try:
            vix = yf.Ticker("^VIX")
            oil = yf.Ticker("CL=F")
            dxy = yf.Ticker("DX-Y.NYB")

            vix_data = vix.history(period="10d")
            oil_data = oil.history(period="10d")
            dxy_data = dxy.history(period="10d")

            if vix_data.empty and oil_data.empty and dxy_data.empty:
                self._last_market_shock_snapshot = {
                    "enabled": False,
                    "window": "5d",
                    "penalty": 0.0,
                    "regime": "NEUTRAL",
                    "factors": {
                        "vix_change_pct": 0.0,
                        "oil_change_pct": 0.0,
                        "dxy_change_pct": 0.0,
                    },
                    "drivers": [],
                }
                return 0.0

            vix_change = self._safe_pct_change(vix_data)
            oil_change = self._safe_pct_change(oil_data)
            dxy_change = self._safe_pct_change(dxy_data)

            penalty = 0.0
            drivers: List[str] = []

            # VIX 冲击：风险偏好急降的核心信号
            if vix_change > 20:
                penalty += 10.0
                drivers.append("VIX近5日大幅上行，风险偏好显著下降")
            elif vix_change > 12:
                penalty += 6.0
                drivers.append("VIX近5日明显抬升，市场避险需求上升")
            elif vix_change > 6:
                penalty += 3.0
                drivers.append("VIX温和上行，情绪转向谨慎")

            # 原油冲击：地缘风险与通胀再定价
            if oil_change > 10:
                penalty += 6.0
                drivers.append("原油近5日急涨，地缘与通胀压力上行")
            elif oil_change > 6:
                penalty += 4.0
                drivers.append("原油持续上行，通胀再定价风险升温")
            elif oil_change > 3:
                penalty += 2.0
                drivers.append("原油小幅上行，对风险资产形成边际压制")

            # 美元指数上行：流动性偏紧 / 风险资产承压
            if dxy_change > 2.0:
                penalty += 4.0
                drivers.append("美元指数明显走强，全球流动性环境趋紧")
            elif dxy_change > 1.0:
                penalty += 2.5
                drivers.append("美元指数上行，风险资产估值承压")
            elif dxy_change > 0.5:
                penalty += 1.0
                drivers.append("美元指数温和走强，避险资金流入美元")

            # 同步共振：至少两项同时显著上行，额外惩罚
            active_shocks = 0
            if vix_change > 12:
                active_shocks += 1
            if oil_change > 6:
                active_shocks += 1
            if dxy_change > 1.0:
                active_shocks += 1
            if active_shocks >= 2:
                penalty += 3.0
                drivers.append("跨资产风险信号共振，市场进入risk-off状态")

            final_penalty = round(max(0.0, min(20.0, penalty)), 2)
            if final_penalty >= 12:
                regime = "RISK_OFF"
            elif final_penalty >= 6:
                regime = "CAUTIOUS"
            else:
                regime = "NEUTRAL"

            self._last_market_shock_snapshot = {
                "enabled": True,
                "window": "5d",
                "penalty": final_penalty,
                "regime": regime,
                "factors": {
                    "vix_change_pct": round(vix_change, 2),
                    "oil_change_pct": round(oil_change, 2),
                    "dxy_change_pct": round(dxy_change, 2),
                },
                "drivers": drivers,
            }

            success = True
            return final_penalty
        except Exception as e:
            error_msg = str(e)
            if not self._is_rate_limit_error(error_msg):
                logger.warning(f"Error calculating market shock penalty: {e}")
            self._last_market_shock_snapshot = {
                "enabled": False,
                "window": "5d",
                "penalty": 0.0,
                "regime": "NEUTRAL",
                "factors": {
                    "vix_change_pct": 0.0,
                    "oil_change_pct": 0.0,
                    "dxy_change_pct": 0.0,
                },
                "drivers": [],
            }
            return None
        finally:
            await self._record_yahoo_call("macro:market_shock", success, error_msg, start_time)

    @staticmethod
    def _safe_pct_change(data) -> float:
        """计算最近约5个交易日涨跌幅百分比，异常时返回0。"""
        try:
            if data is None or data.empty:
                return 0.0
            closes = data["Close"]
            if len(closes) < 2:
                return 0.0
            start_idx = -6 if len(closes) >= 6 else 0
            start = float(closes.iloc[start_idx])
            end = float(closes.iloc[-1])
            if abs(start) < 1e-9:
                return 0.0
            return (end - start) / abs(start) * 100.0
        except Exception:
            return 0.0
    
    async def _calculate_monetary_policy_risk(self) -> float:
        """
        计算货币政策风险评分 (0-100，分数越高风险越低)
        
        考虑因素:
        1. 利率水平 (40%): 极低(<1%)=50分, 正常(2-4%)=80分, 高(>5%)=40分
        2. 收益率曲线 (30%): 陡峭(>1.5%)=80分, 正常=70分, 平坦=50分, 倒挂(<0)=20分
        3. 通胀压力 (30%): 温和(2-3%)=80分, 低(<2%)=60分, 高(>4%)=30分, 恶性(>7%)=10分
        
        Returns:
            货币政策风险评分
        """
        start_time = datetime.now()
        success = False
        error_msg = None
        try:
            # 获取市场数据
            treasury_10y = yf.Ticker("^TNX")  # 10年期国债收益率
            treasury_2y = yf.Ticker("^IRX")   # 3个月国债
            
            data_10y = treasury_10y.history(period="5d")
            data_2y = treasury_2y.history(period="5d")
            
            if data_10y.empty or data_2y.empty:
                return 65.0
            
            rate_10y = float(data_10y["Close"].iloc[-1])
            rate_2y = float(data_2y["Close"].iloc[-1])

            # 使用短期变化捕捉“降息预期快速减弱/重新定价”
            # 2Y 上行通常意味着市场对未来政策路径更鹰派
            if len(data_2y["Close"]) >= 5:
                rate_2y_5d_ago = float(data_2y["Close"].iloc[-5])
            else:
                rate_2y_5d_ago = float(data_2y["Close"].iloc[0])
            if len(data_10y["Close"]) >= 5:
                rate_10y_5d_ago = float(data_10y["Close"].iloc[-5])
            else:
                rate_10y_5d_ago = float(data_10y["Close"].iloc[0])

            delta_2y = rate_2y - rate_2y_5d_ago
            delta_10y = rate_10y - rate_10y_5d_ago
            
            fed_rate = rate_2y
            inflation = 3.0  # 简化，实际应从FRED获取
            
            scores = []
            
            # 1. 利率水平评分
            if fed_rate < 1.0:
                scores.append(50 * 0.4)
            elif 2.0 <= fed_rate <= 4.0:
                scores.append(80 * 0.4)
            elif fed_rate > 5.0:
                scores.append(40 * 0.4)
            else:
                scores.append(70 * 0.4)
            
            # 2. 收益率曲线评分
            yield_curve = rate_10y - rate_2y
            if yield_curve > 1.5:
                scores.append(80 * 0.3)
            elif 0.5 <= yield_curve <= 1.5:
                scores.append(70 * 0.3)
            elif 0 <= yield_curve < 0.5:
                scores.append(50 * 0.3)
            else:  # 倒挂
                scores.append(20 * 0.3)
            
            # 3. 通胀评分
            if 2.0 <= inflation <= 3.0:
                scores.append(80 * 0.3)
            elif inflation < 2.0:
                scores.append(60 * 0.3)
            elif 3.0 < inflation <= 4.0:
                scores.append(50 * 0.3)
            elif 4.0 < inflation <= 7.0:
                scores.append(30 * 0.3)
            else:
                scores.append(10 * 0.3)

            # 4. 利率预期重定价惩罚（快速上行 => 风险上升）
            # 单位近似为“百分点变化”（例如 +0.20 表示 +20bps）
            repricing_penalty = 0.0
            if delta_2y > 0.30:
                repricing_penalty += 18.0
            elif delta_2y > 0.20:
                repricing_penalty += 12.0
            elif delta_2y > 0.10:
                repricing_penalty += 6.0

            if delta_10y > 0.25:
                repricing_penalty += 8.0
            elif delta_10y > 0.15:
                repricing_penalty += 5.0

            # 曲线更深倒挂（或平坦化过快）也增加政策误判/衰退风险
            if yield_curve < -0.5:
                repricing_penalty += 5.0
            
            result = round(max(0.0, sum(scores) - repricing_penalty), 2)
            success = True
            return result
            
        except Exception as e:
            error_msg = str(e)
            if not self._is_rate_limit_error(error_msg):
                logger.warning(f"Error calculating monetary policy risk: {e}")
            return None
        finally:
            await self._record_yahoo_call("macro:monetary_policy", success, error_msg, start_time)
    
    async def _calculate_geopolitical_risk(self, session: AsyncSession) -> float:
        """
        计算地缘政治风险评分 (0-100，分数越高风险越低)
        
        考虑因素:
        1. 活跃事件数量: 0-1个=90分, 2-3个=70分, 4-5个=50分, >5个=30分
        2. 事件严重程度: 平均<3=80分, 3-5=60分, >5=30分
        3. 市场影响评分: 平均<30=80分, 30-50=60分, >50=40分
        
        Returns:
            地缘政治风险评分
        """
        try:
            now = datetime.now()
            thirty_days_ago = now - timedelta(days=30)
            seven_days_ago = now - timedelta(days=7)

            stmt = select(GeopoliticalEvent).where(GeopoliticalEvent.event_date >= thirty_days_ago)
            result = await session.execute(stmt)
            events = result.scalars().all()
            
            if not events:
                return 90.0
            
            event_count = len(events)
            recent_events = [e for e in events if getattr(e, "event_date", now) >= seven_days_ago]
            recent_count = len(recent_events)
            
            # 1. 事件数量评分（近7天权重更高）
            weighted_count = event_count + recent_count * 1.5
            if weighted_count <= 2:
                count_score = 90
            elif weighted_count <= 5:
                count_score = 70
            elif weighted_count <= 8:
                count_score = 50
            else:
                count_score = 25
            
            # 2. 严重程度评分（近7天高危事件放大）
            severity_map = {"LOW": 2, "MEDIUM": 5, "HIGH": 7, "CRITICAL": 9}
            severities = [severity_map.get(getattr(e, "severity", "MEDIUM"), 5) for e in events]
            avg_severity = sum(severities) / len(severities)
            recent_critical_or_high = sum(
                1 for e in recent_events if str(getattr(e, "severity", "MEDIUM")).upper() in {"HIGH", "CRITICAL"}
            )
            
            if avg_severity < 3:
                severity_score = 80
            elif avg_severity <= 5:
                severity_score = 60
            elif avg_severity <= 7:
                severity_score = 40
            else:
                severity_score = 25

            # 最近一周若连续出现高危事件，直接下调
            if recent_critical_or_high >= 3:
                severity_score -= 20
            elif recent_critical_or_high >= 2:
                severity_score -= 12
            elif recent_critical_or_high == 1:
                severity_score -= 6
            
            # 3. 市场影响评分（近期事件额外权重）
            impacts = [getattr(e, "market_impact_score", None) or 40 for e in events]
            avg_impact = sum(impacts) / len(impacts)

            if recent_events:
                recent_impacts = [getattr(e, "market_impact_score", None) or 40 for e in recent_events]
                recent_avg_impact = sum(recent_impacts) / len(recent_impacts)
                blended_impact = avg_impact * 0.6 + recent_avg_impact * 0.4
            else:
                blended_impact = avg_impact
            
            if blended_impact < 30:
                impact_score = 80
            elif blended_impact <= 50:
                impact_score = 60
            elif blended_impact <= 70:
                impact_score = 45
            else:
                impact_score = 30

            # 冲突类别直接惩罚（WAR/能源冲击）
            war_like_recent = sum(
                1 for e in recent_events if str(getattr(e, "category", "")).upper() in {"WAR", "ENERGY_CRISIS"}
            )
            category_penalty = 0.0
            if war_like_recent >= 3:
                category_penalty = 12.0
            elif war_like_recent >= 1:
                category_penalty = 6.0
            
            final_score = count_score * 0.35 + severity_score * 0.35 + impact_score * 0.30
            final_score = max(0.0, min(100.0, final_score - category_penalty))
            return round(final_score, 2)
            
        except Exception as e:
            logger.warning(f"Error calculating geopolitical risk: {e}")
            return 70.0
    
    async def _calculate_sector_bubble_risk(self) -> float:
        """
        计算行业泡沫风险评分 (0-100，分数越高风险越低)
        
        考虑因素:
        1. 纳斯达克PE估值 (50%): <20=80分, 20-30=60分, 30-40=40分, >40=20分
        2. 市场集中度 (30%): <30%=80分, 30-40%=60分, 40-50%=40分, >50%=20分
        3. IPO热度 (20%): 低=80分, 正常=60分, 过热=30分
        
        Returns:
            行业泡沫风险评分
        """
        start_time = datetime.now()
        success = False
        error_msg = None
        try:
            ndx = yf.Ticker("^NDX")
            info = ndx.info
            
            pe_ratio = info.get("trailingPE", 25.0)
            
            # 1. 估值水平评分
            if pe_ratio < 20:
                valuation_score = 80
            elif pe_ratio < 30:
                valuation_score = 60
            elif pe_ratio < 40:
                valuation_score = 40
            else:
                valuation_score = 20
            
            # 2. 市场集中度（简化）
            concentration_score = 60
            
            # 3. IPO热度（简化）
            ipo_score = 60
            
            final_score = (
                valuation_score * 0.5 +
                concentration_score * 0.3 +
                ipo_score * 0.2
            )
            
            result = round(final_score, 2)
            success = True
            return result
            
        except Exception as e:
            error_msg = str(e)
            if not self._is_rate_limit_error(error_msg):
                logger.warning(f"Error calculating sector bubble risk: {e}")
            return None
        finally:
            await self._record_yahoo_call("macro:sector_bubble", success, error_msg, start_time)
    
    async def _calculate_economic_cycle_risk(self) -> float:
        """
        计算经济周期风险评分 (0-100，分数越高风险越低)
        
        考虑因素:
        1. 周期阶段: 复苏期=85分, 扩张期=75分, 繁荣期=50分, 衰退期=25分
        2. GDP增长趋势: 加快=+10分, 稳定=0分, 放缓=-15分
        3. 失业率趋势: 下降=+10分, 稳定=0分, 上升=-15分
        
        Returns:
            经济周期风险评分
        """
        start_time = datetime.now()
        success = False
        error_msg = None
        try:
            spy = yf.Ticker("SPY")
            data = spy.history(period="6mo")
            
            if data.empty:
                return 65.0
            
            current_price = float(data["Close"].iloc[-1])
            six_month_ago = float(data["Close"].iloc[0])
            change_pct = ((current_price - six_month_ago) / six_month_ago) * 100
            
            if change_pct > 15:
                base_score = 75  # 扩张期
            elif change_pct > 5:
                base_score = 85  # 复苏期
            elif change_pct > -5:
                base_score = 60  # 过渡期
            else:
                base_score = 35  # 衰退期
            
            result = round(base_score, 2)
            success = True
            return result
            
        except Exception as e:
            error_msg = str(e)
            if not self._is_rate_limit_error(error_msg):
                logger.warning(f"Error calculating economic cycle risk: {e}")
            return None
        finally:
            await self._record_yahoo_call("macro:economic_cycle", success, error_msg, start_time)
    
    async def _calculate_market_sentiment_risk(self) -> float:
        """
        计算市场情绪风险评分 (0-100，分数越高风险越低)
        
        考虑因素:
        - VIX恐慌指数: <15=85分, 15-20=75分, 20-30=55分, >30=30分
        - Put/Call比率: 0.7-1.0=80分, 1.0-1.3=60分, >1.3=40分
        
        Returns:
            市场情绪风险评分
        """
        start_time = datetime.now()
        success = False
        error_msg = None
        try:
            vix = yf.Ticker("^VIX")
            vix_data = vix.history(period="5d")
            
            if vix_data.empty:
                return 65.0
            
            vix_value = float(vix_data["Close"].iloc[-1])
            
            if vix_value < 15:
                vix_score = 85
            elif vix_value < 20:
                vix_score = 75
            elif vix_value < 30:
                vix_score = 55
            else:
                vix_score = 30
            
            put_call_score = 70  # 简化
            
            final_score = vix_score * 0.7 + put_call_score * 0.3
            
            result = round(final_score, 2)
            success = True
            return result
            
        except Exception as e:
            error_msg = str(e)
            if not self._is_rate_limit_error(error_msg):
                logger.warning(f"Error calculating market sentiment risk: {e}")
            return None
        finally:
            await self._record_yahoo_call("macro:market_sentiment", success, error_msg, start_time)
    
    def _calculate_overall_risk_score(
        self,
        monetary: float,
        geopolitical: float,
        sector_bubble: float,
        economic_cycle: float,
        market_sentiment: float
    ) -> float:
        """计算综合风险评分（加权平均）"""
        overall = (
            monetary * self.WEIGHT_MONETARY_POLICY +
            geopolitical * self.WEIGHT_GEOPOLITICAL +
            sector_bubble * self.WEIGHT_SECTOR_BUBBLE +
            economic_cycle * self.WEIGHT_ECONOMIC_CYCLE +
            market_sentiment * self.WEIGHT_MARKET_SENTIMENT
        )
        return round(overall, 2)
    
    def _determine_risk_level(self, score: float) -> RiskLevel:
        """判定风险等级"""
        if score >= 80:
            return RiskLevel.LOW
        elif score >= 60:
            return RiskLevel.MEDIUM
        elif score >= 40:
            return RiskLevel.HIGH
        else:
            return RiskLevel.EXTREME
    
    # ============= 私有方法：数据库操作 =============
    
    async def _get_cached_risk_score(self, session: AsyncSession) -> Optional[MacroRiskScore]:
        """获取缓存的最新风险评分"""
        try:
            stmt = select(MacroRiskScore).order_by(
                MacroRiskScore.timestamp.desc()
            ).limit(1)
            
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"Error getting cached risk score: {e}")
            return None
    
    # ============= 私有方法：辅助功能 =============
    
    def _generate_risk_summary(self, overall_score: float, dimension_scores: Dict[str, float]) -> str:
        """生成风险摘要"""
        risk_level = self._determine_risk_level(overall_score)
        
        if risk_level == RiskLevel.LOW:
            summary = "宏观环境总体良好，风险可控"
        elif risk_level == RiskLevel.MEDIUM:
            summary = "宏观环境稳定，存在一定风险因素"
        elif risk_level == RiskLevel.HIGH:
            summary = "宏观环境面临较大压力，需要谨慎应对"
        else:
            summary = "宏观环境极度恶化，建议大幅降低风险敞口"
        
        min_dimension = min(dimension_scores.items(), key=lambda x: x[1])
        dimension_names = {
            "monetary_policy": "货币政策",
            "geopolitical": "地缘政治",
            "sector_bubble": "行业泡沫",
            "economic_cycle": "经济周期",
            "market_sentiment": "市场情绪"
        }
        
        summary += f"。主要风险来自{dimension_names[min_dimension[0]]}维度。"
        
        return summary
    
    def _generate_key_concerns(self, dimension_scores: Dict[str, float]) -> List[str]:
        """生成关键关注点"""
        concerns = []
        
        if dimension_scores["monetary_policy"] < 50:
            concerns.append("货币政策收紧压力")
        if dimension_scores["geopolitical"] < 50:
            concerns.append("地缘政治不确定性")
        if dimension_scores["sector_bubble"] < 50:
            concerns.append("行业估值过高风险")
        if dimension_scores["economic_cycle"] < 50:
            concerns.append("经济衰退风险上升")
        if dimension_scores["market_sentiment"] < 50:
            concerns.append("市场恐慌情绪蔓延")
        
        if not concerns:
            concerns.append("无重大风险因素")
        
        return concerns
    
    def _generate_recommendations(self, risk_level: RiskLevel, dimension_scores: Dict[str, float]) -> str:
        """生成投资建议"""
        if risk_level == RiskLevel.LOW:
            return "可适度提高风险资产配置，关注成长型投资机会"
        elif risk_level == RiskLevel.MEDIUM:
            return "保持均衡配置，适当增加防御性资产"
        elif risk_level == RiskLevel.HIGH:
            return "降低风险敞口，增加现金和避险资产比例，考虑对冲策略"
        else:
            return "大幅降低风险资产，转向现金和国债等避险资产，暂停主动交易"
    
    def _calculate_confidence(self, dimension_scores: Dict[str, float]) -> float:
        """
        计算评分置信度
        
        基于数据完整性和一致性
        """
        scores = list(dimension_scores.values())
        mean_score = sum(scores) / len(scores)
        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
        std_dev = variance ** 0.5
        
        confidence = max(0.5, min(1.0, 1.0 - (std_dev / 100)))
        
        return round(confidence, 2)

    @staticmethod
    def _is_rate_limit_error(error_message: str) -> bool:
        msg = (error_message or "").lower()
        return "rate limited" in msg or "too many requests" in msg or "429" in msg

    async def _record_yahoo_call(self, endpoint: str, success: bool, error_msg: Optional[str], start_time: datetime) -> None:
        try:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            await api_monitor.record_api_call(
                provider=APIProvider.YAHOO_FINANCE,
                endpoint=endpoint,
                success=success,
                response_time_ms=response_time,
                error_message=error_msg,
            )
        except Exception:
            pass

    async def _sleep_backoff(self, attempt: int) -> None:
        base = min(self.retry_backoff_cap, self.retry_delay * (2 ** attempt))
        jitter = base * self.jitter_ratio
        wait_time = max(0.0, random.uniform(base - jitter, base + jitter))
        await asyncio.sleep(wait_time)

    async def _sleep_request_delay(self) -> None:
        jitter = self.request_delay * self.jitter_ratio
        wait_time = max(0.0, random.uniform(self.request_delay - jitter, self.request_delay + jitter))
        await asyncio.sleep(wait_time)
