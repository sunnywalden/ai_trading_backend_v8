"""
基本面分析服务

根据 MODULE_1 设计实现：
- 估值分析 (PE, PB, PEG)
- 盈利能力分析 (ROE, ROA, 利润率)
- 成长性分析 (营收增长, 盈利增长)
- 财务健康度分析 (流动性, 杠杆率)
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import yfinance as yf
import time
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fundamental_data import FundamentalData
from app.core.config import settings
from app.services.api_monitoring_service import api_monitor, APIProvider


# 延迟导入避免循环依赖
def _get_session():
    from app.models.db import SessionLocal
    return SessionLocal()


class FundamentalAnalysisService:
    """基本面分析服务"""

    def __init__(self):
        self.cache_ttl_hours = settings.CACHE_TTL_FUNDAMENTAL_HOURS

    async def get_fundamental_data(
        self, 
        symbol: str, 
        force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        获取基本面数据（带缓存）
        
        Args:
            symbol: 股票代码
            force_refresh: 是否强制刷新
            
        Returns:
            包含基本面数据和评分的字典，如果失败返回None
        """
        async with _get_session() as session:
            # 检查缓存
            if not force_refresh:
                cached = await self._get_cached_data(session, symbol)
                if cached:
                    # 将ORM对象转换为字典并添加评分
                    return self._build_result_dict(cached)
            
            # 获取新数据
            fundamental_dict = await self._fetch_fundamental_from_yfinance(symbol)
            if not fundamental_dict:
                # 发生错误或频率限制时，尝试从本地缓存回退
                cached = await self._get_cached_data(session, symbol)
                if cached:
                    print(f"[Fundamental] Yielding cached data for {symbol} due to API issues.")
                    return self._build_result_dict(cached)
                return None
            
            print(f"[Fundamental] Fetched {symbol} from yfinance. Sector={fundamental_dict.get('sector')}")
            # 计算各维度评分
            valuation_score = self._calculate_valuation_score(fundamental_dict)
            profitability_score = self._calculate_profitability_score(fundamental_dict)
            growth_score = self._calculate_growth_score(fundamental_dict)
            health_score = self._calculate_health_score(fundamental_dict)
            
            # 计算综合评分 (各维度权重相等)
            overall_score = (
                valuation_score + profitability_score + 
                growth_score + health_score
            ) / 4.0
            
            # 保存到数据库
            fundamental = FundamentalData(
                symbol=symbol,
                fiscal_date=datetime.now().date(),
                data_type='LATEST',
                sector=fundamental_dict.get("sector"),
                industry=fundamental_dict.get("industry"),
                # 估值
                pe_ratio=fundamental_dict.get("pe_ratio"),
                pb_ratio=fundamental_dict.get("pb_ratio"),
                peg_ratio=fundamental_dict.get("peg_ratio"),
                beta=fundamental_dict.get("beta"),
                # 盈利能力
                roe=fundamental_dict.get("roe"),
                roa=fundamental_dict.get("roa"),
                net_margin=fundamental_dict.get("profit_margin"),  # 映射到net_margin
                # 增长
                revenue_growth_yoy=fundamental_dict.get("revenue_growth"),
                eps_growth_yoy=fundamental_dict.get("earnings_growth"),
                # 财务健康
                current_ratio=fundamental_dict.get("current_ratio"),
                debt_to_equity=fundamental_dict.get("debt_to_equity")
            )
            
            session.add(fundamental)
            await session.commit()
            await session.refresh(fundamental)
            
            # 返回包含评分的字典
            return self._build_result_dict(
                fundamental,
                valuation_score,
                profitability_score,
                growth_score,
                health_score,
                overall_score
            )

    def _build_result_dict(
        self,
        data: FundamentalData,
        valuation_score: Optional[float] = None,
        profitability_score: Optional[float] = None,
        growth_score: Optional[float] = None,
        health_score: Optional[float] = None,
        overall_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """将ORM对象转换为包含评分的字典"""
        # 如果没有提供评分，重新计算
        if valuation_score is None:
            fundamental_dict = {
                "pe_ratio": data.pe_ratio,
                "pb_ratio": data.pb_ratio,
                "peg_ratio": data.peg_ratio,
                "roe": data.roe,
                "roa": data.roa,
                "profit_margin": data.net_margin,
                "revenue_growth": data.revenue_growth_yoy,
                "earnings_growth": data.eps_growth_yoy,
                "current_ratio": data.current_ratio,
                "debt_to_equity": data.debt_to_equity,
            }
            valuation_score = self._calculate_valuation_score(fundamental_dict)
            profitability_score = self._calculate_profitability_score(fundamental_dict)
            growth_score = self._calculate_growth_score(fundamental_dict)
            health_score = self._calculate_health_score(fundamental_dict)
            overall_score = (valuation_score + profitability_score + growth_score + health_score) / 4.0
        
        # 创建结果字典（使用命名空间对象模拟ORM对象属性访问）
        from types import SimpleNamespace
        from datetime import datetime
        result = SimpleNamespace(
            symbol=data.symbol,
            fiscal_date=data.fiscal_date,
            timestamp=datetime.now(),  # 添加timestamp字段
            sector=data.sector,
            industry=data.industry,
            pe_ratio=data.pe_ratio,
            pb_ratio=data.pb_ratio,
            peg_ratio=data.peg_ratio,
            beta=data.beta,
            roe=data.roe,
            roa=data.roa,
            profit_margin=data.net_margin,  # 映射回profit_margin
            revenue_growth=data.revenue_growth_yoy,
            earnings_growth=data.eps_growth_yoy,
            current_ratio=data.current_ratio,
            debt_to_equity=data.debt_to_equity,
            valuation_score=valuation_score,
            profitability_score=profitability_score,
            growth_score=growth_score,
            health_score=health_score,
            overall_score=overall_score
        )
        return result

    async def _get_cached_data(
        self, 
        session: AsyncSession, 
        symbol: str
    ) -> Optional[FundamentalData]:
        """获取缓存的基本面数据"""
        cutoff_date = (datetime.now() - timedelta(hours=self.cache_ttl_hours)).date()
        
        stmt = select(FundamentalData).where(
            FundamentalData.symbol == symbol,
            FundamentalData.fiscal_date >= cutoff_date
        ).order_by(FundamentalData.fiscal_date.desc())
        
        result = await session.execute(stmt)
        # 这里可能命中多行（例如同一天多次写入），scalar_one_or_none 会抛 Multiple rows 错误。
        # 由于已按日期倒序排序，取最新一行即可。
        return result.scalars().first()

    async def _fetch_fundamental_from_yfinance(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        从yfinance获取基本面数据
        
        Returns:
            包含所有基本面指标的字典，失败返回None
        """
        gate = await api_monitor.can_call_provider(APIProvider.YAHOO_FINANCE)
        if not gate.get("can_call", True):
            print(f"[Fundamental] Skip Yahoo Finance due to cooldown/limit: {gate.get('reason')}")
            return None

        start_time = time.time()
        success = False
        error_msg = None
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # 检查是否成功获取数据
            if not info or "symbol" not in info:
                error_msg = "Empty info returned"
                return None
            
            # 提取所需指标
            fundamental = {
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                # 估值指标
                "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "peg_ratio": info.get("pegRatio"),
                "beta": info.get("beta"),
                
                # 盈利能力指标
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),
                "profit_margin": info.get("profitMargins"),
                
                # 成长性指标
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth"),
                
                # 财务健康指标
                "current_ratio": info.get("currentRatio"),
                "debt_to_equity": info.get("debtToEquity"),
            }
            
            # 转换百分比为小数
            if fundamental["roe"]:
                fundamental["roe"] = fundamental["roe"] * 100  # yfinance返回的是小数
            if fundamental["roa"]:
                fundamental["roa"] = fundamental["roa"] * 100
            if fundamental["profit_margin"]:
                fundamental["profit_margin"] = fundamental["profit_margin"] * 100
            if fundamental["revenue_growth"]:
                fundamental["revenue_growth"] = fundamental["revenue_growth"] * 100
            if fundamental["earnings_growth"]:
                fundamental["earnings_growth"] = fundamental["earnings_growth"] * 100
            
            success = True
            return fundamental
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error fetching fundamental data for {symbol}: {e}")
            return None
        finally:
            response_time = (time.time() - start_time) * 1000
            await api_monitor.record_api_call(
                provider=APIProvider.YAHOO_FINANCE,
                endpoint=f"fundamental:{symbol}",
                success=success,
                response_time_ms=response_time,
                error_message=error_msg,
            )

    def _calculate_valuation_score(self, data: Dict[str, Any]) -> float:
        """
        计算估值评分 (0-100)
        
        评分规则：
        - PE < 15: 90-100分 (低估)
        - PE 15-25: 60-90分 (合理)
        - PE 25-40: 30-60分 (略高)
        - PE > 40: 0-30分 (高估)
        
        - PB < 1: 90-100分 (低估)
        - PB 1-3: 60-90分 (合理)
        - PB 3-5: 30-60分 (略高)
        - PB > 5: 0-30分 (高估)
        
        - PEG < 1: 90-100分 (优秀)
        - PEG 1-2: 60-90分 (良好)
        - PEG > 2: 0-60分 (一般)
        """
        scores = []
        
        # PE评分
        pe = data.get("pe_ratio")
        if pe and pe > 0:
            if pe < 15:
                pe_score = 90 + (15 - pe) / 15 * 10  # 90-100
            elif pe < 25:
                pe_score = 60 + (25 - pe) / 10 * 30  # 60-90
            elif pe < 40:
                pe_score = 30 + (40 - pe) / 15 * 30  # 30-60
            else:
                pe_score = max(0, 30 - (pe - 40) / 10 * 5)  # 0-30
            scores.append(min(100, max(0, pe_score)))
        
        # PB评分
        pb = data.get("pb_ratio")
        if pb and pb > 0:
            if pb < 1:
                pb_score = 90 + (1 - pb) / 1 * 10  # 90-100
            elif pb < 3:
                pb_score = 60 + (3 - pb) / 2 * 30  # 60-90
            elif pb < 5:
                pb_score = 30 + (5 - pb) / 2 * 30  # 30-60
            else:
                pb_score = max(0, 30 - (pb - 5) / 5 * 30)  # 0-30
            scores.append(min(100, max(0, pb_score)))
        
        # PEG评分
        peg = data.get("peg_ratio")
        if peg and peg > 0:
            if peg < 1:
                peg_score = 90 + (1 - peg) / 1 * 10  # 90-100
            elif peg < 2:
                peg_score = 60 + (2 - peg) / 1 * 30  # 60-90
            else:
                peg_score = max(0, 60 - (peg - 2) / 3 * 60)  # 0-60
            scores.append(min(100, max(0, peg_score)))
        
        # 返回平均分，如果没有任何指标则返回50
        return sum(scores) / len(scores) if scores else 50.0

    def _calculate_profitability_score(self, data: Dict[str, Any]) -> float:
        """
        计算盈利能力评分 (0-100)
        
        评分规则：
        - ROE > 20%: 90-100分 (优秀)
        - ROE 15-20%: 70-90分 (良好)
        - ROE 10-15%: 50-70分 (一般)
        - ROE < 10%: 0-50分 (较差)
        
        - ROA > 10%: 90-100分 (优秀)
        - ROA 5-10%: 70-90分 (良好)
        - ROA 2-5%: 50-70分 (一般)
        - ROA < 2%: 0-50分 (较差)
        
        - 利润率 > 20%: 90-100分
        - 利润率 10-20%: 70-90分
        - 利润率 5-10%: 50-70分
        - 利润率 < 5%: 0-50分
        """
        scores = []
        
        # ROE评分
        roe = data.get("roe")
        if roe is not None:
            if roe >= 20:
                roe_score = 90 + min((roe - 20) / 10 * 10, 10)  # 90-100
            elif roe >= 15:
                roe_score = 70 + (roe - 15) / 5 * 20  # 70-90
            elif roe >= 10:
                roe_score = 50 + (roe - 10) / 5 * 20  # 50-70
            else:
                roe_score = max(0, roe / 10 * 50)  # 0-50
            scores.append(min(100, max(0, roe_score)))
        
        # ROA评分
        roa = data.get("roa")
        if roa is not None:
            if roa >= 10:
                roa_score = 90 + min((roa - 10) / 10 * 10, 10)  # 90-100
            elif roa >= 5:
                roa_score = 70 + (roa - 5) / 5 * 20  # 70-90
            elif roa >= 2:
                roa_score = 50 + (roa - 2) / 3 * 20  # 50-70
            else:
                roa_score = max(0, roa / 2 * 50)  # 0-50
            scores.append(min(100, max(0, roa_score)))
        
        # 利润率评分
        margin = data.get("profit_margin")
        if margin is not None:
            if margin >= 20:
                margin_score = 90 + min((margin - 20) / 10 * 10, 10)  # 90-100
            elif margin >= 10:
                margin_score = 70 + (margin - 10) / 10 * 20  # 70-90
            elif margin >= 5:
                margin_score = 50 + (margin - 5) / 5 * 20  # 50-70
            else:
                margin_score = max(0, margin / 5 * 50)  # 0-50
            scores.append(min(100, max(0, margin_score)))
        
        return sum(scores) / len(scores) if scores else 50.0

    def _calculate_growth_score(self, data: Dict[str, Any]) -> float:
        """
        计算成长性评分 (0-100)
        
        评分规则：
        - 营收增长 > 30%: 90-100分
        - 营收增长 15-30%: 70-90分
        - 营收增长 5-15%: 50-70分
        - 营收增长 < 5%: 0-50分
        
        - 盈利增长同理
        """
        scores = []
        
        # 营收增长评分
        revenue_growth = data.get("revenue_growth")
        if revenue_growth is not None:
            if revenue_growth >= 30:
                rev_score = 90 + min((revenue_growth - 30) / 20 * 10, 10)  # 90-100
            elif revenue_growth >= 15:
                rev_score = 70 + (revenue_growth - 15) / 15 * 20  # 70-90
            elif revenue_growth >= 5:
                rev_score = 50 + (revenue_growth - 5) / 10 * 20  # 50-70
            else:
                rev_score = max(0, revenue_growth / 5 * 50)  # 0-50 (负增长得0分)
            scores.append(min(100, max(0, rev_score)))
        
        # 盈利增长评分
        earnings_growth = data.get("earnings_growth")
        if earnings_growth is not None:
            if earnings_growth >= 30:
                earn_score = 90 + min((earnings_growth - 30) / 20 * 10, 10)  # 90-100
            elif earnings_growth >= 15:
                earn_score = 70 + (earnings_growth - 15) / 15 * 20  # 70-90
            elif earnings_growth >= 5:
                earn_score = 50 + (earnings_growth - 5) / 10 * 20  # 50-70
            else:
                earn_score = max(0, earnings_growth / 5 * 50)  # 0-50
            scores.append(min(100, max(0, earn_score)))
        
        return sum(scores) / len(scores) if scores else 50.0

    def _calculate_health_score(self, data: Dict[str, Any]) -> float:
        """
        计算财务健康度评分 (0-100)
        
        评分规则：
        - 流动比率 > 2: 90-100分 (优秀)
        - 流动比率 1.5-2: 70-90分 (良好)
        - 流动比率 1-1.5: 50-70分 (一般)
        - 流动比率 < 1: 0-50分 (风险)
        
        - 资产负债率 < 30%: 90-100分 (优秀)
        - 资产负债率 30-60%: 70-90分 (良好)
        - 资产负债率 60-80%: 50-70分 (一般)
        - 资产负债率 > 80%: 0-50分 (风险)
        """
        scores = []
        
        # 流动比率评分
        current_ratio = data.get("current_ratio")
        if current_ratio is not None:
            if current_ratio >= 2:
                cr_score = 90 + min((current_ratio - 2) / 2 * 10, 10)  # 90-100
            elif current_ratio >= 1.5:
                cr_score = 70 + (current_ratio - 1.5) / 0.5 * 20  # 70-90
            elif current_ratio >= 1:
                cr_score = 50 + (current_ratio - 1) / 0.5 * 20  # 50-70
            else:
                cr_score = max(0, current_ratio / 1 * 50)  # 0-50
            scores.append(min(100, max(0, cr_score)))
        
        # 资产负债率评分 (debt_to_equity是负债/权益比，需要转换)
        debt_to_equity = data.get("debt_to_equity")
        if debt_to_equity is not None:
            # 转换为资产负债率: D/E → D/(D+E) = D/E / (1 + D/E)
            debt_ratio = debt_to_equity / (1 + debt_to_equity) * 100
            
            if debt_ratio < 30:
                debt_score = 90 + (30 - debt_ratio) / 30 * 10  # 90-100
            elif debt_ratio < 60:
                debt_score = 70 + (60 - debt_ratio) / 30 * 20  # 70-90
            elif debt_ratio < 80:
                debt_score = 50 + (80 - debt_ratio) / 20 * 20  # 50-70
            else:
                debt_score = max(0, 50 - (debt_ratio - 80) / 20 * 50)  # 0-50
            scores.append(min(100, max(0, debt_score)))
        
        return sum(scores) / len(scores) if scores else 50.0

    async def batch_refresh_fundamentals(self, symbols: list[str]) -> Dict[str, bool]:
        """
        并发批量刷新基本面数据（受 EXTERNAL_API_CONCURRENCY 限制）
        
        Args:
            symbols: 股票代码列表
            
        Returns:
            {symbol: success} 字典
        """
        results = {}
        sem = asyncio.Semaphore(settings.EXTERNAL_API_CONCURRENCY)

        async def _refresh(sym: str):
            async with sem:
                try:
                    data = await self.get_fundamental_data(sym, force_refresh=True)
                    return sym, data is not None
                except Exception as e:
                    print(f"Error refreshing fundamental for {sym}: {e}")
                    return sym, False

        pairs = await asyncio.gather(*[_refresh(s) for s in symbols]) if symbols else []
        results = {k: v for k, v in pairs}
        return results
