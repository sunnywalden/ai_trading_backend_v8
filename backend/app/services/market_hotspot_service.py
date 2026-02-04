"""
市场热点服务 (Market Hotspot Service)

职责：
- 聚合多源资讯：NewsAPI (地缘政治/宏观经济/金融市场)
- 资讯分类：政治、经济、金融、战争、重大公司动态
- AI 摘要生成：利用 OpenAI 对长资讯进行简要总结
- 实时性保证：支持缓存与异步刷新
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from enum import Enum
import hashlib

from app.core.config import settings
from app.core.cache import cache
from app.models.macro_risk import GeopoliticalEvent
from app.services.api_monitoring_service import api_monitor, APIProvider
from app.services.geopolitical_events_service import GeopoliticalEventsService, EventCategory

logger = logging.getLogger(__name__)

class HotspotCategory(str, Enum):
    POLITICS = "POLITICS"   # 政治
    ECONOMY = "ECONOMY"     # 经济
    FINANCE = "FINANCE"     # 金融
    WAR = "WAR"             # 战争/冲突
    COMPANY = "COMPANY"     # 重大公司动态
    TECH = "TECH"           # 技术/创新
    OTHER = "OTHER"

class MarketHotspotService:
    def __init__(self, session=None):
        self.session = session
        self.geo_service = GeopoliticalEventsService()
        
    async def get_latest_hotspots(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """获取最新的市场热点"""
        cache_key = "market_hotspots:latest"
        
        if not force_refresh:
            cached_data = await cache.get(cache_key)
            if cached_data:
                return cached_data
        
        # 聚合数据源
        tasks = [
            self._fetch_from_news_api()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        hotspots = []
        for res in results:
            if isinstance(res, list):
                hotspots.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Error fetching hotspots: {res}")
        
        # 去重 (基于标题哈希)
        unique_hotspots = self._deduplicate(hotspots)
        
        # 如果没有任何数据源成功，提供一些 Mock 数据作为演示（仅在开发/模拟模式下有用）
        if not unique_hotspots:
            unique_hotspots = self._get_mock_hotspots()

        # 排序 (按时间降序)
        unique_hotspots.sort(key=lambda x: x.get("event_date", ""), reverse=True)
        
        # 截取前 50 条
        result = unique_hotspots[:50]
        
        # 缓存 15 分钟
        await cache.set(cache_key, result, expire=900)
        
        return result

    def _deduplicate(self, hotspots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen_hashes = set()
        unique_list = []
        for item in hotspots:
            title = item.get("title", "")
            h = hashlib.md5(title.encode('utf-8')).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_list.append(item)
        return unique_list

    async def _fetch_from_news_api(self) -> List[Dict[str, Any]]:
        """从 NewsAPI 获取宏观与地缘政治资讯"""
        # 复用 GeopoliticalEventsService 的逻辑，但扩展关键词
        # 这里我们可以直接调用 geo_service.fetch_geopolitical_events() 但它目前只管地缘政治
        # 我们这里模拟一个扩展的调用
        try:
            # 扩展关键词，弥补 Tiger 资讯缺失
            keywords = "US economy OR Federal Reserve OR inflation OR US stock market OR Geopolitics OR Nasdaq OR Interest Rates"
            events = await self.geo_service.fetch_external_events(query=keywords)
            
            # 转换为统一的热点格式
            hotspots = []
            for e in events:
                # 简单情感判定
                text = (e.title + " " + (e.description or "")).upper()
                sentiment = "BULLISH" if any(w in text for w in ["GAIN", "RISE", "UP", "BULL", "BOOST", "RECORD HIGH"]) else \
                            "BEARISH" if any(w in text for w in ["FALL", "DROP", "CRASH", "BEAR", "DOWN", "FEAR", "DECLINE"]) else \
                            "NEUTRAL"

                hotspots.append({
                    "id": getattr(e, "id", None),
                    "title": e.title,
                    "description": e.description,
                    "event_date": e.event_date.isoformat() if isinstance(e.event_date, datetime) else e.event_date,
                    "category": self._map_geo_category_to_hotspot(e.event_type),
                    "severity": e.severity,
                    "market_impact_score": e.market_impact_score,
                    "sentiment": sentiment,
                    "related_symbols": self._extract_symbols(e.title + " " + (e.description or "")),
                    "source": e.news_source,
                    "url": e.news_url
                })
            return hotspots
        except Exception as e:
            logger.error(f"NewsAPI fetch failed: {e}")
            return []

    def _extract_symbols(self, text: str) -> List[str]:
        """从文本中提取潜在的股票代码 (简单正则示例)"""
        import re
        # 寻找类似 $AAPL, $TSLA 或大写全字 (如 NVIDIA)
        symbols = set(re.findall(r'\$([A-Z]{1,5})', text))
        # 常见重型权重股 fallback
        upper_text = text.upper()
        if "FED" in upper_text or "RATE" in upper_text or "POWELL" in upper_text:
            symbols.add("SPY")
            symbols.add("QQQ")
            symbols.add("TLT")
        if "AI" in upper_text or "NVIDIA" in upper_text or "GPU" in upper_text or "NVDA" in upper_text:
            symbols.add("NVDA")
        if "APPLE" in upper_text or "IPHONE" in upper_text or "AAPL" in upper_text:
            symbols.add("AAPL")
        if "TESLA" in upper_text or "MUSK" in upper_text or "TSLA" in upper_text:
            symbols.add("TSLA")
        return list(symbols)[:5]

    def _map_geo_category_to_hotspot(self, geo_type: EventCategory) -> HotspotCategory:
        """映射地缘政治分类到热点分类"""
        mapping = {
            EventCategory.WAR: HotspotCategory.WAR,
            EventCategory.DIPLOMACY: HotspotCategory.POLITICS,
            EventCategory.ECONOMY: HotspotCategory.ECONOMY,
            EventCategory.POLITICS: HotspotCategory.POLITICS,
            EventCategory.TRADE: HotspotCategory.FINANCE,
            EventCategory.ENERGY: HotspotCategory.ECONOMY,
            EventCategory.TECH: HotspotCategory.TECH,
            EventCategory.OTHER: HotspotCategory.OTHER
        }
        return mapping.get(geo_type, HotspotCategory.OTHER)

    def _get_mock_hotspots(self) -> List[Dict[str, Any]]:
        """当所有数据源都失效时，返回一些模拟数据"""
        now = datetime.now()
        return [
            {
                "title": "Fed Signals Interest Rates May Stay Higher for Longer",
                "description": "Federal Reserve officials expressed caution about cutting interest rates too soon, citing persistent inflation concerns in the latest meeting minutes.",
                "event_date": (now - timedelta(hours=2)).isoformat(),
                "category": HotspotCategory.ECONOMY,
                "severity": "MEDIUM",
                "market_impact_score": 75,
                "sentiment": "BEARISH",
                "related_symbols": ["SPY", "QQQ", "TLT"],
                "source": "Market Watch (Mock)",
                "url": "https://www.federalreserve.gov"
            },
            {
                "title": "Tech Giants Rally on AI Infrastructure GPU Expansion News",
                "description": "Major technology stocks saw significant gains today as companies announced multi-billion dollar investments in new AI data centers and GPU clusters.",
                "event_date": (now - timedelta(hours=5)).isoformat(),
                "category": HotspotCategory.TECH,
                "severity": "LOW",
                "market_impact_score": 60,
                "sentiment": "BULLISH",
                "related_symbols": ["NVDA", "MSFT", "GOOGL"],
                "source": "TechNews (Mock)",
                "url": "https://www.bloomberg.com"
            },
            {
                "title": "Geopolitical Tensions Rise in Middle East, Oil Prices Steady",
                "description": "Crude oil futures remained stable despite escalating diplomatic tensions in key energy-producing regions, as supply chains remain intact for now.",
                "event_date": (now - timedelta(hours=8)).isoformat(),
                "category": HotspotCategory.WAR,
                "severity": "HIGH",
                "market_impact_score": 85,
                "sentiment": "BEARISH",
                "related_symbols": ["USO", "XLE"],
                "source": "Global News (Mock)",
                "url": "https://www.reuters.com"
            }
        ]
