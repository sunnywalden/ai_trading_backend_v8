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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import yfinance as yf

from app.models.macro_risk import MacroRiskScore, GeopoliticalEvent

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
                key_concerns=str(key_concerns),
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
        fallback_value: float
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
        for attempt in range(self.max_retries):
            try:
                result = await calc_func()
                if result is not None:
                    return result
            except Exception as e:
                error_msg = str(e)
                if "Rate limited" in error_msg or "Too Many Requests" in error_msg:
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (attempt + 1)  # 指数退避
                        logger.warning(
                            f"Rate limited for {dimension_name}, retrying in {wait_time}s... "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.warning(
                            f"Rate limited for {dimension_name} after {self.max_retries} attempts, "
                            f"using fallback value: {fallback_value}"
                        )
                else:
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
        await asyncio.sleep(self.request_delay)
        
        # 其他维度依赖yfinance，需要错误处理
        monetary = await self._calculate_with_retry(
            self._calculate_monetary_policy_risk,
            "monetary_policy",
            cached.monetary_policy_score if cached else 65.0
        )
        await asyncio.sleep(self.request_delay)
        
        sector_bubble = await self._calculate_with_retry(
            self._calculate_sector_bubble_risk,
            "sector_bubble",
            cached.sector_bubble_score if cached else 60.0
        )
        await asyncio.sleep(self.request_delay)
        
        economic_cycle = await self._calculate_with_retry(
            self._calculate_economic_cycle_risk,
            "economic_cycle",
            cached.economic_cycle_score if cached else 65.0
        )
        await asyncio.sleep(self.request_delay)
        
        market_sentiment = await self._calculate_with_retry(
            self._calculate_market_sentiment_risk,
            "market_sentiment",
            cached.sentiment_score if cached else 65.0
        )
        
        return {
            "monetary_policy": monetary,
            "geopolitical": geopolitical,
            "sector_bubble": sector_bubble,
            "economic_cycle": economic_cycle,
            "market_sentiment": market_sentiment
        }
    
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
            
            return round(sum(scores), 2)
            
        except Exception as e:
            logger.warning(f"Error calculating monetary policy risk: {e}")
            # 返回None触发重试机制
            return None
    
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
            thirty_days_ago = datetime.now() - timedelta(days=30)
            stmt = select(GeopoliticalEvent).where(
                GeopoliticalEvent.event_date >= thirty_days_ago
            )
            result = await session.execute(stmt)
            events = result.scalars().all()
            
            if not events:
                return 90.0
            
            event_count = len(events)
            
            # 1. 事件数量评分
            if event_count <= 1:
                count_score = 90
            elif event_count <= 3:
                count_score = 70
            elif event_count <= 5:
                count_score = 50
            else:
                count_score = 30
            
            # 2. 严重程度评分
            severity_map = {"LOW": 2, "MEDIUM": 5, "HIGH": 7, "CRITICAL": 9}
            severities = [severity_map.get(e.severity, 5) for e in events]
            avg_severity = sum(severities) / len(severities)
            
            if avg_severity < 3:
                severity_score = 80
            elif avg_severity <= 5:
                severity_score = 60
            else:
                severity_score = 30
            
            # 3. 市场影响评分
            impacts = [e.market_impact_score or 40 for e in events]
            avg_impact = sum(impacts) / len(impacts)
            
            if avg_impact < 30:
                impact_score = 80
            elif avg_impact <= 50:
                impact_score = 60
            else:
                impact_score = 40
            
            final_score = count_score * 0.4 + severity_score * 0.3 + impact_score * 0.3
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
            
            return round(final_score, 2)
            
        except Exception as e:
            logger.warning(f"Error calculating sector bubble risk: {e}")
            # 返回None触发重试机制
            return None
    
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
            
            return round(base_score, 2)
            
        except Exception as e:
            logger.warning(f"Error calculating economic cycle risk: {e}")
            # 返回None触发重试机制
            return None
    
    async def _calculate_market_sentiment_risk(self) -> float:
        """
        计算市场情绪风险评分 (0-100，分数越高风险越低)
        
        考虑因素:
        - VIX恐慌指数: <15=85分, 15-20=75分, 20-30=55分, >30=30分
        - Put/Call比率: 0.7-1.0=80分, 1.0-1.3=60分, >1.3=40分
        
        Returns:
            市场情绪风险评分
        """
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
            
            return round(final_score, 2)
            
        except Exception as e:
            logger.warning(f"Error calculating market sentiment risk: {e}")
            # 返回None触发重试机制
            return None
    
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
