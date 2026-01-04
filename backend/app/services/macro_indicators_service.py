"""
宏观指标服务

根据 MODULE_3 设计实现：
- 从FRED API获取15个经济指标
- 货币政策分析（利率、通胀、收益率曲线）
- 经济周期分析（GDP、失业率、PMI）
- 市场情绪分析（VIX、看跌/看涨比率）
- 6小时数据缓存
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import yfinance as yf
from fredapi import Fred
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.macro_risk import MacroIndicator
from app.core.config import settings


# 延迟导入避免循环依赖
def _get_session():
    from app.main import SessionLocal
    return SessionLocal()


class MacroIndicatorsService:
    """宏观指标服务"""
    
    # FRED数据系列ID映射
    FRED_SERIES = {
        # 货币政策指标
        "fed_funds_rate": "DFF",              # 联邦基金利率
        "10y_treasury": "DGS10",              # 10年期国债收益率
        "2y_treasury": "DGS2",                # 2年期国债收益率
        "m2_money_supply": "M2SL",            # M2货币供应量
        "cpi": "CPIAUCSL",                    # 消费者物价指数
        "core_cpi": "CPILFESL",               # 核心CPI
        "pce": "PCE",                         # 个人消费支出
        
        # 经济周期指标
        "gdp": "GDPC1",                       # 实际GDP
        "unemployment": "UNRATE",             # 失业率
        "initial_claims": "ICSA",             # 初次申请失业金人数
        "industrial_production": "INDPRO",    # 工业生产指数
        "retail_sales": "RSXFS",              # 零售销售
        "housing_starts": "HOUST",            # 新屋开工
        
        # 其他
        "consumer_sentiment": "UMCSENT",      # 密歇根消费者信心指数
    }
    
    def __init__(self):
        self.fred = Fred(api_key=settings.FRED_API_KEY) if settings.FRED_API_KEY else None
        self.cache_ttl_hours = settings.CACHE_TTL_MACRO_HOURS

    async def get_macro_indicators(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        获取所有宏观指标
        
        Args:
            force_refresh: 是否强制刷新
            
        Returns:
            包含所有宏观指标的字典
        """
        async with _get_session() as session:
            indicators = {}
            
            for indicator_name, series_id in self.FRED_SERIES.items():
                if not force_refresh:
                    cached = await self._get_cached_indicator(session, indicator_name)
                    if cached:
                        indicators[indicator_name] = {
                            "value": cached.fed_rate if indicator_name == "fed_funds_rate" else None,
                            "timestamp": cached.timestamp
                        }
                        continue
                
                # 获取新数据
                indicator_data = await self._fetch_fred_indicator(indicator_name, series_id)
                if indicator_data:
                    indicators[indicator_name] = indicator_data
            
            # 获取VIX
            vix_value = await self._fetch_vix()
            if vix_value:
                indicators["vix"] = {
                    "value": vix_value,
                    "timestamp": datetime.now()
                }
            
            return indicators

    async def get_monetary_policy_stance(self) -> Dict[str, Any]:
        """
        获取货币政策立场分析
        
        Returns:
            包含货币政策分析的字典
        """
        async with _get_session() as session:
            # 获取关键指标
            fed_rate_data = await self._get_or_fetch_indicator(session, "fed_funds_rate", "DFF")
            treasury_10y_data = await self._get_or_fetch_indicator(session, "10y_treasury", "DGS10")
            treasury_2y_data = await self._get_or_fetch_indicator(session, "2y_treasury", "DGS2")
            cpi_data = await self._get_or_fetch_indicator(session, "cpi", "CPIAUCSL")
            m2_data = await self._get_or_fetch_indicator(session, "m2_money_supply", "M2SL")
            
            # 提取值
            fed_rate = fed_rate_data["value"] if fed_rate_data else 5.0
            treasury_10y = treasury_10y_data["value"] if treasury_10y_data else 4.5
            treasury_2y = treasury_2y_data["value"] if treasury_2y_data else 4.2
            inflation_rate = cpi_data["change_1y"] if cpi_data and "change_1y" in cpi_data else 3.0
            m2_growth = m2_data["change_1y"] if m2_data and "change_1y" in m2_data else 5.0
            
            # 计算收益率曲线
            yield_curve = self._calculate_yield_curve(treasury_2y, treasury_10y)
            
            # 判断货币政策立场
            stance = self._analyze_monetary_policy_stance(fed_rate, inflation_rate, m2_growth)
            
            return {
                "fed_funds_rate": fed_rate,
                "treasury_10y": treasury_10y,
                "treasury_2y": treasury_2y,
                "yield_curve_slope": yield_curve,
                "inflation_rate": inflation_rate,
                "m2_growth": m2_growth,
                "policy_stance": stance,
                "last_updated": datetime.now()
            }

    async def get_economic_cycle_phase(self) -> Dict[str, Any]:
        """
        获取经济周期阶段分析
        
        Returns:
            包含经济周期分析的字典
        """
        async with _get_session() as session:
            # 获取关键指标
            gdp_data = await self._get_or_fetch_indicator(session, "gdp", "GDPC1")
            unemployment_data = await self._get_or_fetch_indicator(session, "unemployment", "UNRATE")
            industrial_data = await self._get_or_fetch_indicator(session, "industrial_production", "INDPRO")
            sentiment_data = await self._get_or_fetch_indicator(session, "consumer_sentiment", "UMCSENT")
            
            # 提取值
            gdp_growth = gdp_data["change_1y"] if gdp_data and "change_1y" in gdp_data else 2.5
            unemployment = unemployment_data["value"] if unemployment_data else 4.0
            industrial_growth = industrial_data["change_1y"] if industrial_data and "change_1y" in industrial_data else 2.0
            consumer_sentiment = sentiment_data["value"] if sentiment_data else 75.0
            
            # 简化的PMI估算（基于工业生产）
            estimated_pmi = 50 + (industrial_growth * 2)
            
            # 判断经济周期阶段
            cycle_phase = self._determine_economic_cycle_phase(gdp_growth, unemployment, estimated_pmi)
            
            # 计算衰退概率
            recession_prob = self._calculate_recession_probability(gdp_growth, unemployment, estimated_pmi)
            
            return {
                "gdp_growth_rate": gdp_growth,
                "unemployment_rate": unemployment,
                "industrial_production_growth": industrial_growth,
                "estimated_pmi": estimated_pmi,
                "consumer_sentiment": consumer_sentiment,
                "cycle_phase": cycle_phase,
                "recession_probability": recession_prob,
                "last_updated": datetime.now()
            }

    async def refresh_all_indicators(self) -> Dict[str, int]:
        """
        刷新所有宏观指标（定时任务调用）
        
        Returns:
            {"success": 成功数量, "failed": 失败数量}
        """
        if not self.fred:
            return {"success": 0, "failed": len(self.FRED_SERIES), "error": "FRED API key not configured"}
        
        async with _get_session() as session:
            success_count = 0
            failed_count = 0
            
            for indicator_name, series_id in self.FRED_SERIES.items():
                try:
                    indicator_data = await self._fetch_fred_indicator(indicator_name, series_id)
                    if indicator_data:
                        await self._save_indicator_to_db(session, indicator_name, indicator_data)
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    print(f"Failed to refresh {indicator_name}: {e}")
                    failed_count += 1
            
            # 刷新VIX
            try:
                vix_value = await self._fetch_vix()
                if vix_value:
                    await self._save_vix_to_db(session, vix_value)
                    success_count += 1
            except Exception as e:
                print(f"Failed to refresh VIX: {e}")
                failed_count += 1
            
            await session.commit()
            
            return {
                "success": success_count,
                "failed": failed_count,
                "total": success_count + failed_count
            }

    async def _get_or_fetch_indicator(
        self,
        session: AsyncSession,
        indicator_name: str,
        series_id: str
    ) -> Optional[Dict[str, Any]]:
        """获取指标（优先使用缓存）"""
        # 检查缓存
        cached = await self._get_cached_indicator(session, indicator_name)
        if cached:
            cutoff_time = datetime.now() - timedelta(hours=self.cache_ttl_hours)
            if cached.timestamp >= cutoff_time:
                return self._extract_indicator_from_db(cached, indicator_name)
        
        # 获取新数据
        return await self._fetch_fred_indicator(indicator_name, series_id)

    async def _get_cached_indicator(
        self,
        session: AsyncSession,
        indicator_name: str
    ) -> Optional[MacroIndicator]:
        """从数据库获取缓存指标"""
        stmt = select(MacroIndicator).where(
            MacroIndicator.indicator_type == self._get_indicator_type(indicator_name)
        ).order_by(MacroIndicator.timestamp.desc()).limit(1)
        
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _fetch_fred_indicator(
        self,
        indicator_name: str,
        series_id: str,
        lookback_days: int = 365
    ) -> Optional[Dict[str, Any]]:
        """
        从FRED API获取单个指标
        
        Args:
            indicator_name: 指标名称
            series_id: FRED系列ID
            lookback_days: 回溯天数
            
        Returns:
            指标数据字典
        """
        if not self.fred:
            return None
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)
            
            series = self.fred.get_series(
                series_id,
                observation_start=start_date,
                observation_end=end_date
            )
            
            if series.empty:
                return None
            
            # 获取最新值
            latest_value = float(series.iloc[-1])
            latest_date = series.index[-1]
            
            # 计算变化
            change_1m = self._calculate_change(series, 30)
            change_3m = self._calculate_change(series, 90)
            change_1y = self._calculate_change(series, 365)
            
            return {
                "value": latest_value,
                "date": latest_date,
                "change_1m": change_1m,
                "change_3m": change_3m,
                "change_1y": change_1y,
                "unit": self._get_unit(indicator_name),
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            print(f"Error fetching {indicator_name} from FRED: {e}")
            return None

    async def _fetch_vix(self) -> Optional[float]:
        """获取VIX恐慌指数"""
        try:
            vix = yf.Ticker("^VIX")
            data = vix.history(period="1d")
            if not data.empty:
                return float(data["Close"].iloc[-1])
            return None
        except Exception as e:
            print(f"Error fetching VIX: {e}")
            return None

    def _calculate_change(self, series, days: int) -> float:
        """计算时间段内的变化率"""
        try:
            if len(series) < days:
                days = len(series) - 1
            if days <= 0:
                return 0.0
            
            current_value = float(series.iloc[-1])
            past_value = float(series.iloc[-days])
            
            if past_value == 0:
                return 0.0
            
            return round(((current_value - past_value) / past_value * 100), 2)
        except:
            return 0.0

    def _calculate_yield_curve(self, two_year: float, ten_year: float) -> float:
        """
        计算收益率曲线斜率
        
        收益率曲线 = 10年期 - 2年期
        
        解读:
        - > 1.0: 陡峭，经济扩张预期
        - 0.5-1.0: 正常
        - 0-0.5: 平坦，经济放缓
        - < 0: 倒挂，衰退预警
        """
        return round(ten_year - two_year, 2)

    def _analyze_monetary_policy_stance(
        self,
        fed_funds_rate: float,
        inflation_rate: float,
        m2_growth: float
    ) -> str:
        """
        分析货币政策立场
        
        判断逻辑:
        1. 利率 < 2% 且 M2增速 > 10% → 宽松
        2. 利率 > 4% 且 通胀 > 5% → 紧缩
        3. 其他 → 中性
        """
        if fed_funds_rate < 2.0 and m2_growth > 10:
            return "宽松 (Accommodative)"
        elif fed_funds_rate > 4.0 and inflation_rate > 5:
            return "紧缩 (Restrictive)"
        elif fed_funds_rate > 3.0 and inflation_rate > 3:
            return "偏紧 (Slightly Restrictive)"
        elif fed_funds_rate < 3.0:
            return "偏松 (Slightly Accommodative)"
        else:
            return "中性 (Neutral)"

    def _determine_economic_cycle_phase(
        self,
        gdp_growth: float,
        unemployment: float,
        pmi: float
    ) -> str:
        """
        判断经济周期阶段
        
        四阶段模型:
        1. 扩张期 (Expansion): GDP增长加速, 失业率下降, PMI > 50
        2. 繁荣期 (Peak): GDP高增长, 失业率极低, PMI > 55
        3. 衰退期 (Contraction): GDP放缓, 失业率上升, PMI < 50
        4. 复苏期 (Trough/Recovery): GDP开始回升, 失业率见顶, PMI回到50附近
        """
        if gdp_growth > 3.0 and unemployment < 4.0 and pmi > 55:
            return "繁荣期 (Peak)"
        elif gdp_growth > 2.0 and pmi > 50:
            return "扩张期 (Expansion)"
        elif gdp_growth < 1.0 and pmi < 50:
            return "衰退期 (Contraction)"
        elif gdp_growth < 2.0 and pmi >= 50:
            return "复苏期 (Recovery)"
        else:
            return "过渡期 (Transition)"

    def _calculate_recession_probability(
        self,
        gdp_growth: float,
        unemployment: float,
        pmi: float
    ) -> float:
        """
        计算衰退概率（0-100%）
        
        基于多个指标的综合评估
        """
        prob = 0.0
        
        # GDP增长率
        if gdp_growth < 0:
            prob += 40
        elif gdp_growth < 1:
            prob += 30
        elif gdp_growth < 2:
            prob += 15
        
        # 失业率
        if unemployment > 6:
            prob += 30
        elif unemployment > 5:
            prob += 20
        elif unemployment > 4:
            prob += 10
        
        # PMI
        if pmi < 45:
            prob += 30
        elif pmi < 50:
            prob += 20
        
        return min(100.0, prob)

    def _get_unit(self, indicator_name: str) -> str:
        """获取指标单位"""
        units = {
            "fed_funds_rate": "%",
            "10y_treasury": "%",
            "2y_treasury": "%",
            "cpi": "Index",
            "core_cpi": "Index",
            "pce": "Billions",
            "gdp": "Billions",
            "unemployment": "%",
            "initial_claims": "Thousands",
            "industrial_production": "Index",
            "retail_sales": "Millions",
            "housing_starts": "Thousands",
            "consumer_sentiment": "Index",
            "m2_money_supply": "Billions",
            "vix": "Index",
        }
        return units.get(indicator_name, "")

    def _get_indicator_type(self, indicator_name: str) -> str:
        """获取指标类型"""
        monetary_indicators = ["fed_funds_rate", "10y_treasury", "2y_treasury", "m2_money_supply", "cpi", "core_cpi", "pce"]
        economic_indicators = ["gdp", "unemployment", "initial_claims", "industrial_production", "retail_sales", "housing_starts"]
        sentiment_indicators = ["consumer_sentiment", "vix"]
        
        if indicator_name in monetary_indicators:
            return "MONETARY"
        elif indicator_name in economic_indicators:
            return "ECONOMIC"
        elif indicator_name in sentiment_indicators:
            return "SENTIMENT"
        else:
            return "OTHER"

    def _extract_indicator_from_db(self, db_indicator: MacroIndicator, indicator_name: str) -> Dict[str, Any]:
        """从数据库对象提取指标数据"""
        # 根据指标名称从MacroIndicator对象提取对应字段
        value_map = {
            "fed_funds_rate": db_indicator.fed_rate,
            "cpi": db_indicator.inflation_rate,
            "m2_money_supply": db_indicator.m2_growth_rate,
            "gdp": db_indicator.gdp_growth,
            "unemployment": db_indicator.unemployment_rate,
            "industrial_production": db_indicator.pmi_index,
            "consumer_sentiment": db_indicator.vix_index,
            "vix": db_indicator.vix_index,
        }
        
        value = value_map.get(indicator_name)
        if value is None:
            return None
        
        return {
            "value": value,
            "timestamp": db_indicator.timestamp
        }

    async def _save_indicator_to_db(
        self,
        session: AsyncSession,
        indicator_name: str,
        indicator_data: Dict[str, Any]
    ) -> None:
        """保存指标到数据库"""
        indicator_type = self._get_indicator_type(indicator_name)
        
        # 创建新的MacroIndicator记录
        macro_indicator = MacroIndicator(
            indicator_type=indicator_type,
            timestamp=datetime.now()
        )
        
        # 根据指标名称设置对应字段
        value = indicator_data.get("value")
        if indicator_name == "fed_funds_rate":
            macro_indicator.fed_rate = value
        elif indicator_name == "cpi":
            macro_indicator.inflation_rate = value
        elif indicator_name == "m2_money_supply":
            macro_indicator.m2_growth_rate = indicator_data.get("change_1y", 0)
        elif indicator_name == "gdp":
            macro_indicator.gdp_growth = indicator_data.get("change_1y", 0)
        elif indicator_name == "unemployment":
            macro_indicator.unemployment_rate = value
        elif indicator_name == "industrial_production":
            macro_indicator.pmi_index = value
        elif indicator_name == "consumer_sentiment":
            macro_indicator.vix_index = value
        elif indicator_name == "10y_treasury":
            macro_indicator.yield_curve_2y10y = value
        
        session.add(macro_indicator)

    async def _save_vix_to_db(self, session: AsyncSession, vix_value: float) -> None:
        """保存VIX到数据库"""
        macro_indicator = MacroIndicator(
            indicator_type="SENTIMENT",
            vix_index=vix_value,
            timestamp=datetime.now()
        )
        session.add(macro_indicator)
