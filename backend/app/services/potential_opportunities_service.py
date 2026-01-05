"""潜在机会模块服务

职责：
- 维护股票池（Universe）
- 计算技术/基本面/情绪三维评分并筛选机会
- 结合宏观风险结果调整阈值/名额
- 将扫描结果落库，支持 latest / runs 查询

说明：
- 为降低 yfinance 限流风险：默认 force_refresh=False，尽量使用缓存结果
- 并发控制：对外部数据请求做 semaphore 限制
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple, Any

from zoneinfo import ZoneInfo
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.opportunity_scan import OpportunityScanRun, OpportunityScanItem
from app.services.technical_analysis_service import TechnicalAnalysisService
from app.services.fundamental_analysis_service import FundamentalAnalysisService
from app.services.macro_risk_scoring_service import MacroRiskScoringService
from app.providers.market_data_provider import MarketDataProvider
from app.models.symbol_profile_cache import SymbolProfileCache


BJ_TZ = ZoneInfo("Asia/Shanghai")


class UniverseName:
    US_LARGE_MID_TECH = "US_LARGE_MID_TECH"


# Universe 构建策略：
# 1) 从较大的 seed list 开始（可后续配置化）
# 2) 通过 yfinance 动态按“市值 + 行业/赛道”筛选，得到中大型科技股列表
#
# 说明：yfinance 本身不提供“全市场股票列表”，因此需要一个 seed list 作为候选集合。
# 动态性体现在：每次都会基于最新 marketCap/sector/industry 来筛选/排序。
_UNIVERSE_SEED_SYMBOLS: List[str] = [
    # Mega/large cap & common tech/tech-adjacent universe
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "ORCL", "CRM",
    "AMD", "INTU", "ADBE", "QCOM", "NFLX", "TXN", "IBM", "CSCO", "NOW", "PANW",
    "INTC", "AMAT", "MU", "KLAC", "LRCX", "ASML", "TSM", "SNPS", "CDNS", "ANSS",
    "SHOP", "UBER", "LYFT", "ABNB", "PYPL", "SQ", "NET", "DDOG", "SNOW", "CRWD",
    "ZS", "OKTA", "MDB", "PLTR", "TEAM", "DOCU", "TWLO", "ROKU", "EA", "TTWO",
    "DELL", "HPQ", "SMCI", "WDAY", "SAP", "SONY", "ERIC", "NOK", "NTES", "BIDU",
    "TSLA", "RIVN", "LCID", "NIO", "LI", "XPEV",
    "INTU", "ADBE", "SPOT", "UBER", "LYFT",
    # infra / cloud / security
    "AKAM", "FSLY", "GDDY", "SPLK", "FTNT", "CHKP", "S", "NET", "PANW",
]


# 进程内缓存：减少 yfinance.info 调用次数
_PROFILE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_UNIVERSE_CACHE: Dict[str, Tuple[float, List[str]]] = {}

_PROFILE_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6h
_UNIVERSE_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6h

# 静态兜底：当外部数据完全不可用时，至少不返回空 universe
_FALLBACK_TECH_SYMBOLS: List[str] = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "AVGO",
    "ORCL",
    "CRM",
    "AMD",
    "ADBE",
    "QCOM",
    "NFLX",
    "TXN",
    "INTC",
    "AMAT",
    "MU",
    "LRCX",
    "SNPS",
    "CDNS",
]


@dataclass
class ScoredSymbol:
    symbol: str
    current_price: Optional[float]
    technical_score: int
    fundamental_score: int
    sentiment_score: int
    overall_score: int
    recommendation: str
    reason: str


class PotentialOpportunitiesService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._fundamental = FundamentalAnalysisService()
        self._macro = MacroRiskScoringService()
        self._market = MarketDataProvider()

        # 并发控制（yfinance 容易限流，宁可慢一点也别全挂）
        self._semaphore = asyncio.Semaphore(3)

    async def get_universe_symbols(self, universe_name: str, force_refresh: bool = False) -> Tuple[List[str], Dict[str, Any]]:
        """动态构建 Universe。

        要求：按市值/行业筛选（中大型科技股）。
        """
        now = time.time()
        meta: Dict[str, Any] = {}

        cached = _UNIVERSE_CACHE.get(universe_name)
        if cached and not force_refresh:
            ts, symbols = cached
            if now - ts < _UNIVERSE_CACHE_TTL_SECONDS:
                meta["cache_hit"] = True
                meta["fallback_used"] = False
                return list(symbols), meta

        # 目前只实现 US_LARGE_MID_TECH
        seed = list(dict.fromkeys(_UNIVERSE_SEED_SYMBOLS))
        symbols = await self._build_large_mid_tech_universe(seed)
        if not symbols:
            # 若 yfinance 限流导致无法拉取 marketCap/sector，则回退到静态科技股清单，避免空扫描。
            # 仍保持“按行业筛选”的意图（该列表本身是科技/科技相关）。
            symbols = list(_FALLBACK_TECH_SYMBOLS)
            meta["fallback_used"] = True
        else:
            meta["fallback_used"] = False

        _UNIVERSE_CACHE[universe_name] = (now, symbols)
        return list(symbols), meta

    async def _build_large_mid_tech_universe(self, seed_symbols: List[str]) -> List[str]:
        """从 seed_symbols 动态筛选出“中大型科技股”列表，并按市值降序排序。"""

        # 市值门槛：>= 10B 美元
        min_market_cap = 10_000_000_000

        # 控制 universe 的规模（避免扫描时间线性爆炸）
        max_universe_size = 30

        async def fetch(sym: str) -> Tuple[str, Dict[str, Any]]:
            async with self._semaphore:
                profile = await self._get_symbol_profile(sym)
                return sym, profile

        tasks = [fetch(s) for s in seed_symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        filtered: List[Tuple[str, int]] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            sym, p = r
            if not p:
                continue

            market_cap = p.get("marketCap") or 0
            sector = (p.get("sector") or "").strip()
            industry = (p.get("industry") or "").strip()

            if not isinstance(market_cap, int):
                try:
                    market_cap = int(market_cap)
                except Exception:
                    market_cap = 0

            if market_cap < min_market_cap:
                continue

            if not self._is_tech_like(sector, industry):
                continue

            filtered.append((sym, market_cap))

        # 市值降序
        filtered.sort(key=lambda x: x[1], reverse=True)
        symbols = [s for s, _ in filtered][:max_universe_size]
        return symbols

    @staticmethod
    def _is_tech_like(sector: str, industry: str) -> bool:
        """行业筛选：尽量覆盖科技股/科技相关赛道。"""
        sector_l = sector.lower()
        industry_l = industry.lower()

        if sector_l == "technology":
            return True

        # 部分互联网平台/媒体/通信服务往往归为 Communication Services
        if sector_l == "communication services":
            if any(k in industry_l for k in ["internet", "software", "platform", "interactive", "data", "cloud"]):
                return True

        # 消费可选中包含电商/互联网零售等
        if sector_l == "consumer cyclical":
            if any(k in industry_l for k in ["internet", "retail", "e-commerce", "auto manufacturers"]):
                return True

        # 行业内关键词兜底
        if any(
            k in industry_l
            for k in [
                "semiconductor",
                "software",
                "information technology",
                "it services",
                "internet",
                "cybersecurity",
                "cloud",
                "data",
            ]
        ):
            return True

        return False

    async def _get_symbol_profile(self, symbol: str) -> Dict[str, Any]:
        """获取 symbol 的 yfinance profile（带进程内缓存）。"""
        now = time.time()
        cached = _PROFILE_CACHE.get(symbol)
        if cached:
            ts, profile = cached
            if now - ts < _PROFILE_CACHE_TTL_SECONDS:
                return profile

        # 1) 先查 DB 缓存（跨进程/重启可复用）
        db_cached = await self._get_profile_from_db(symbol)
        if db_cached:
            _PROFILE_CACHE[symbol] = (now, db_cached)
            return db_cached

        # 2) 再尝试 yfinance.info（阻塞 IO；并发量由 semaphore 控制，避免触发更严重的限流。）
        try:
            ticker = self._market.get_ticker(symbol)
            info = ticker.info or {}
            profile = {
                "marketCap": info.get("marketCap"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }
            await self._upsert_profile_to_db(symbol, profile)
            _PROFILE_CACHE[symbol] = (now, profile)
            return profile
        except Exception:
            profile = {}
            _PROFILE_CACHE[symbol] = (now, profile)
            return profile

    async def _get_profile_from_db(self, symbol: str) -> Dict[str, Any]:
        """从数据库读取 symbol profile 缓存。"""
        # 缓存有效期：14 天（过期也可用，但优先新数据）
        cutoff = datetime.now(tz=BJ_TZ) - timedelta(days=14)
        stmt = select(SymbolProfileCache).where(SymbolProfileCache.symbol == symbol)
        res = await self.session.execute(stmt)
        row = res.scalars().first()
        if not row:
            return {}
        try:
            # updated_at 可能是 naive datetime（sqlite），这里做宽松判断
            if row.updated_at and row.updated_at < cutoff.replace(tzinfo=None):
                # 过期：仍可返回，但不给过度信任
                return {
                    "marketCap": row.market_cap,
                    "sector": row.sector,
                    "industry": row.industry,
                }
        except Exception:
            pass
        return {
            "marketCap": row.market_cap,
            "sector": row.sector,
            "industry": row.industry,
        }

    async def _upsert_profile_to_db(self, symbol: str, profile: Dict[str, Any]) -> None:
        """将 profile 写入数据库缓存（简单 upsert）。"""
        market_cap = profile.get("marketCap")
        sector = profile.get("sector")
        industry = profile.get("industry")

        stmt = select(SymbolProfileCache).where(SymbolProfileCache.symbol == symbol)
        res = await self.session.execute(stmt)
        row = res.scalars().first()
        if row:
            row.market_cap = market_cap if market_cap is not None else row.market_cap
            row.sector = sector if sector is not None else row.sector
            row.industry = industry if industry is not None else row.industry
            return

        self.session.add(
            SymbolProfileCache(
                symbol=symbol,
                market_cap=market_cap,
                sector=sector,
                industry=industry,
            )
        )

    @staticmethod
    def _build_run_key(
        as_of_bj: datetime,
        universe_name: str,
        min_score: int,
        max_results: int,
        force_refresh: bool,
    ) -> str:
        day = as_of_bj.strftime("%Y-%m-%d")
        fr = 1 if force_refresh else 0
        return f"{day}|{universe_name}|min{min_score}|max{max_results}|fr{fr}"

    async def get_latest_success_run(self, universe_name: Optional[str] = None) -> Optional[OpportunityScanRun]:
        stmt = select(OpportunityScanRun).where(OpportunityScanRun.status == "SUCCESS")
        if universe_name:
            stmt = stmt.where(OpportunityScanRun.universe_name == universe_name)
        stmt = stmt.order_by(desc(OpportunityScanRun.created_at)).limit(1)

        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def list_runs(self, limit: int = 20, universe_name: Optional[str] = None) -> List[OpportunityScanRun]:
        stmt = select(OpportunityScanRun)
        if universe_name:
            stmt = stmt.where(OpportunityScanRun.universe_name == universe_name)
        stmt = stmt.order_by(desc(OpportunityScanRun.created_at)).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_run_by_id(self, run_id: int) -> Optional[OpportunityScanRun]:
        stmt = select(OpportunityScanRun).where(OpportunityScanRun.id == run_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def scan_and_persist(
        self,
        universe_name: str = UniverseName.US_LARGE_MID_TECH,
        min_score: int = 75,
        max_results: int = 3,
        force_refresh: bool = False,
    ) -> Tuple[OpportunityScanRun, Dict]:
        """执行一次机会扫描并落库。

        返回： (run, notes)
        notes 用于返回额外信息（例如宏观风险导致的阈值调整原因）。
        """
        start = time.perf_counter()
        notes: Dict = {}

        as_of_bj = datetime.now(tz=BJ_TZ)
        run_key = self._build_run_key(as_of_bj, universe_name, min_score, max_results, force_refresh)

        # 幂等：同一天同一参数只保留一次成功 run
        existing_stmt = select(OpportunityScanRun).where(OpportunityScanRun.run_key == run_key)
        existing = (await self.session.execute(existing_stmt)).scalars().first()
        if existing and existing.status == "SUCCESS":
            notes["idempotent"] = True
            return existing, notes

        # 宏观风险快照（优先走缓存，避免拖慢扫描）
        macro = None
        try:
            macro = await self._macro.calculate_macro_risk_score(use_cache=True)
        except Exception as e:
            notes["macro_risk_error"] = str(e)

        effective_min_score = min_score
        effective_max_results = max_results

        if macro is not None:
            # 需求：HIGH/EXTREME 时提高阈值到 80
            if macro.risk_level in ["HIGH", "EXTREME"]:
                effective_min_score = max(min_score, 80)
                notes["macro_adjustment"] = {
                    "risk_level": macro.risk_level,
                    "overall_score": macro.overall_score,
                    "min_score": {"before": min_score, "after": effective_min_score},
                }

        symbols, universe_meta = await self.get_universe_symbols(universe_name, force_refresh=force_refresh)
        if universe_meta:
            notes["universe"] = universe_meta

        run = OpportunityScanRun(
            run_key=run_key,
            as_of=as_of_bj,
            universe_name=universe_name,
            min_score=min_score,
            max_results=max_results,
            force_refresh=1 if force_refresh else 0,
            status="SUCCESS",
            total_symbols=len(symbols),
            qualified_symbols=0,
        )

        if macro is not None:
            run.macro_overall_score = macro.overall_score
            run.macro_risk_level = macro.risk_level
            run.macro_risk_summary = macro.risk_summary

        items: List[ScoredSymbol] = []
        if effective_max_results > 0:
            items = await self._scan_symbols(symbols, effective_min_score, force_refresh)
            items = sorted(items, key=lambda x: x.overall_score, reverse=True)[:effective_max_results]

        run.qualified_symbols = len(items)

        # 把 items 转成 ORM
        for i, s in enumerate(items, start=1):
            run.items.append(
                OpportunityScanItem(
                    symbol=s.symbol,
                    technical_score=s.technical_score,
                    fundamental_score=s.fundamental_score,
                    sentiment_score=s.sentiment_score,
                    overall_score=s.overall_score,
                    recommendation=s.recommendation,
                    reason=s.reason,
                    current_price=s.current_price,
                )
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        run.elapsed_ms = elapsed_ms

        # 若存在旧 run（失败/跳过），先删除再写新（避免 unique run_key 冲突）
        if existing is not None:
            await self.session.delete(existing)
            await self.session.flush()

        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run, notes

    async def _scan_symbols(self, symbols: List[str], min_score: int, force_refresh: bool) -> List[ScoredSymbol]:
        tasks = [self._score_one_symbol(sym, min_score=min_score, force_refresh=force_refresh) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored: List[ScoredSymbol] = []
        for sym, r in zip(symbols, results):
            if isinstance(r, Exception) or r is None:
                continue
            scored.append(r)
        return scored

    async def _score_one_symbol(self, symbol: str, min_score: int, force_refresh: bool) -> Optional[ScoredSymbol]:
        async with self._semaphore:
            # 技术分析（使用缓存优先）
            tech_service = TechnicalAnalysisService(self.session)
            try:
                tech = await tech_service.get_technical_analysis(
                    symbol=symbol,
                    timeframe="1D",
                    use_cache=not force_refresh,
                )
            except Exception:
                tech = None

            # 当前价：尽量从技术数据的缓存/历史中获取（避免多一次 info 请求）
            current_price: Optional[float] = None
            try:
                if tech is not None:
                    current_price = float(tech.bollinger_bands.current_price)
            except Exception:
                current_price = None

            # 基本面（db cache + yfinance）
            try:
                fundamental = await self._fundamental.get_fundamental_data(symbol, force_refresh=force_refresh)
            except Exception:
                fundamental = None

            technical_score = self._score_technical(tech)
            fundamental_score = self._score_fundamental(fundamental)
            sentiment_score = self._score_sentiment(tech)

            # 单项都要过线
            if technical_score < min_score or fundamental_score < min_score or sentiment_score < min_score:
                return None

            overall = int(round(technical_score * 0.40 + fundamental_score * 0.40 + sentiment_score * 0.20))
            overall = max(0, min(100, overall))
            if overall < min_score:
                return None

            recommendation = "BUY" if overall >= 75 else "HOLD"
            if overall >= 90:
                recommendation = "STRONG_BUY"

            reason = self._build_reason(symbol, tech, fundamental, technical_score, fundamental_score, sentiment_score)

            return ScoredSymbol(
                symbol=symbol,
                current_price=current_price,
                technical_score=technical_score,
                fundamental_score=fundamental_score,
                sentiment_score=sentiment_score,
                overall_score=overall,
                recommendation=recommendation,
                reason=reason,
            )

    @staticmethod
    def _score_technical(tech) -> int:
        if tech is None:
            return 50

        score = 50.0

        # 趋势强度：0-100
        try:
            strength = float(tech.trend_strength)
            score += (strength - 50.0) * 0.6
        except Exception:
            pass

        # RSI
        try:
            rsi_val = float(tech.rsi.value)
            if rsi_val < 30:
                score += 12
            elif rsi_val < 40:
                score += 6
            elif rsi_val > 70:
                score -= 12
            elif rsi_val > 60:
                score -= 6
        except Exception:
            pass

        # MACD 状态
        try:
            macd_status = str(tech.macd.status)
            if "BULLISH" in macd_status:
                score += 8
            elif "BEARISH" in macd_status:
                score -= 8
        except Exception:
            pass

        return int(max(0, min(100, round(score))))

    @staticmethod
    def _score_fundamental(fundamental) -> int:
        if fundamental is None:
            return 50
        try:
            v = float(getattr(fundamental, "overall_score", 50.0))
            return int(max(0, min(100, round(v))))
        except Exception:
            return 50

    @staticmethod
    def _score_sentiment(tech) -> int:
        """情绪评分：先用技术指标派生的“市场情绪”近似值。

        - RSI：反映超买/超卖情绪
        - 趋势强度：反映市场一致性
        """
        if tech is None:
            return 50

        score = 50.0

        try:
            rsi_val = float(tech.rsi.value)
            if 40 <= rsi_val <= 60:
                score += 10
            elif 30 <= rsi_val < 40:
                score += 18
            elif rsi_val < 30:
                score += 22
            elif 60 < rsi_val <= 70:
                score += 4
            else:  # > 70
                score -= 10
        except Exception:
            pass

        try:
            strength = float(tech.trend_strength)
            score += (strength - 50.0) * 0.3
        except Exception:
            pass

        return int(max(0, min(100, round(score))))

    @staticmethod
    def _build_reason(symbol: str, tech, fundamental, ts: int, fs: int, ss: int) -> str:
        parts: List[str] = []
        parts.append(f"三维评分均达标：T{ts}/F{fs}/S{ss}")

        try:
            parts.append(f"趋势 {tech.trend_direction}({tech.trend_strength}%)")
        except Exception:
            pass

        try:
            parts.append(f"RSI {round(float(tech.rsi.value), 1)}")
        except Exception:
            pass

        try:
            pe = getattr(fundamental, "pe_ratio", None)
            roe = getattr(fundamental, "roe", None)
            if pe is not None:
                parts.append(f"PE {round(float(pe), 2)}")
            if roe is not None:
                parts.append(f"ROE {round(float(roe), 2)}%")
        except Exception:
            pass

        # reason 字段允许 JSON，但为了前端兼容性，这里给纯文本。
        return "；".join(parts)
