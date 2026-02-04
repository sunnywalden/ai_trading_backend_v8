"""
地缘政治事件服务

根据 MODULE_5 设计实现：
- News API集成获取地缘政治新闻
- 事件分类（战争、贸易、政治动荡、恐怖主义、外交危机、能源危机）
- 严重程度评分（1-10）
- 市场影响评估（0-100）
- 事件去重
- 4小时数据缓存
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
import re
import time

from newsapi import NewsApiClient
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
import yfinance as yf

from app.models.macro_risk import GeopoliticalEvent
from app.core.config import settings
from app.core.cache import cache
from app.services.api_monitoring_service import api_monitor, APIProvider


# 延迟导入避免循环依赖
def _get_session():
    from app.models.db import SessionLocal
    return SessionLocal()


class EventCategory(str, Enum):
    """事件类别"""
    WAR = "WAR"                           # 战争/军事冲突
    TRADE_DISPUTE = "TRADE_DISPUTE"       # 贸易争端
    POLITICAL_UNREST = "POLITICAL_UNREST" # 政治动荡
    TERRORISM = "TERRORISM"               # 恐怖主义
    DIPLOMATIC_CRISIS = "DIPLOMATIC_CRISIS" # 外交危机
    ENERGY_CRISIS = "ENERGY_CRISIS"       # 能源危机
    OTHER = "OTHER"                       # 其他


class SeverityLevel(str, Enum):
    """严重程度等级"""
    LOW = "LOW"           # 1-3分
    MEDIUM = "MEDIUM"     # 4-6分
    HIGH = "HIGH"         # 7-8分
    CRITICAL = "CRITICAL" # 9-10分


class GeopoliticalEventsService:
    """地缘政治事件服务"""
    
    # 事件分类关键词
    CATEGORY_KEYWORDS = {
        EventCategory.WAR: [
            "war", "military", "invasion", "attack", "conflict", "missile", "warfare",
            "战争", "军事", "入侵", "攻击", "导弹", "冲突"
        ],
        EventCategory.TRADE_DISPUTE: [
            "tariff", "trade war", "sanctions", "embargo", "export ban", 
            "关税", "贸易战", "制裁", "禁运", "出口禁令"
        ],
        EventCategory.POLITICAL_UNREST: [
            "protest", "riot", "revolution", "coup", "regime change", "election crisis",
            "抗议", "暴乱", "革命", "政变", "选举危机"
        ],
        EventCategory.TERRORISM: [
            "terror", "terrorist", "bombing", "assassination", "extremist",
            "恐怖", "恐怖主义", "爆炸", "暗杀", "极端"
        ],
        EventCategory.DIPLOMATIC_CRISIS: [
            "diplomatic", "embassy", "ambassador", "expulsion", "relations break",
            "外交", "大使馆", "大使", "驱逐", "断交"
        ],
        EventCategory.ENERGY_CRISIS: [
            "oil crisis", "energy shortage", "gas shortage", "opec", "pipeline",
            "石油危机", "能源短缺", "天然气", "管道"
        ]
    }
    
    # 严重程度关键词（权重）
    SEVERITY_KEYWORDS = {
        10: ["nuclear", "world war", "pandemic", "核战", "世界大战"],
        9: ["major war", "invasion", "coup", "重大战争", "政变"],
        8: ["military strike", "sanctions", "embargo", "军事打击", "全面制裁"],
        7: ["crisis", "conflict", "tension", "危机", "严重冲突"],
        5: ["dispute", "protest", "unrest", "争端", "抗议"],
        3: ["negotiation", "talks", "meeting", "谈判", "会谈"]
    }
    
    # 市场影响关键词（权重）
    MARKET_IMPACT_KEYWORDS = {
        "global": 30,      # 全球影响
        "major economy": 25,  # 主要经济体
        "oil": 20,         # 石油相关
        "trade": 15,       # 贸易相关
        "financial": 15,   # 金融相关
        "currency": 10,    # 货币相关
        "regional": 5      # 区域影响
    }
    
    def __init__(self):
        self.news_api = NewsApiClient(api_key=settings.NEWS_API_KEY) if settings.NEWS_API_KEY else None
        self.cache_ttl_hours = settings.CACHE_TTL_GEOPOLITICAL_HOURS

    async def fetch_recent_events(
        self, 
        days: int = 7, 
        force_refresh: bool = False
    ) -> List[GeopoliticalEvent]:
        """
        获取最近的地缘政治事件
        
        Args:
            days: 获取最近N天的事件
            force_refresh: 是否强制刷新
            
        Returns:
            地缘政治事件列表
        """
        async with _get_session() as session:
            if not force_refresh:
                # 尝试从缓存获取
                cached_events = await self._get_cached_events(session, days)
                if cached_events:
                    return cached_events
            
            # 从News API获取新事件
            if not self.news_api:
                print("News API key not configured, using fallback")
                return await self._get_cached_events(session, days) or []
            
            new_events = await self._fetch_from_news_api(days)
            
            # 去重和保存
            if new_events:
                deduplicated = await self._deduplicate_events(session, new_events)
                for event in deduplicated:
                    session.add(event)
                await session.commit()
                
                # 返回所有事件（包括新旧）
                return await self._get_cached_events(session, days)
            
            return []

    async def get_high_impact_events(self, days: int = 30) -> List[GeopoliticalEvent]:
        """
        获取高影响力事件（市场影响评分 >= 60）
        
        Args:
            days: 查询最近N天
            
        Returns:
            高影响力事件列表
        """
        async with _get_session() as session:
            cutoff_date = datetime.now() - timedelta(days=days)
            stmt = select(GeopoliticalEvent).where(
                and_(
                    GeopoliticalEvent.event_date >= cutoff_date,
                    GeopoliticalEvent.market_impact_score >= 60
                )
            ).order_by(GeopoliticalEvent.market_impact_score.desc())
            
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_events_by_category(
        self, 
        category: EventCategory, 
        days: int = 30
    ) -> List[GeopoliticalEvent]:
        """
        按类别获取事件
        
        Args:
            category: 事件类别
            days: 查询最近N天
            
        Returns:
            指定类别的事件列表
        """
        async with _get_session() as session:
            cutoff_date = datetime.now() - timedelta(days=days)
            stmt = select(GeopoliticalEvent).where(
                and_(
                    GeopoliticalEvent.category == category.value,
                    GeopoliticalEvent.event_date >= cutoff_date
                )
            ).order_by(GeopoliticalEvent.event_date.desc())
            
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def calculate_geopolitical_risk_score(self, days: int = 30) -> Dict[str, Any]:
        """
        计算地缘政治风险评分
        
        Args:
            days: 考虑最近N天的事件
            
        Returns:
            包含评分和统计信息的字典
        """
        events = await self.fetch_recent_events(days)
        
        if not events:
            return {
                "score": 90.0,  # 无事件=低风险
                "event_count": 0,
                "avg_severity": 0.0,
                "avg_market_impact": 0.0,
                "risk_level": "LOW"
            }
        
        # 计算各项指标
        event_count = len(events)
        severities = [self._severity_to_number(e.severity) for e in events]
        avg_severity = sum(severities) / len(severities)
        impacts = [e.market_impact_score for e in events]
        avg_impact = sum(impacts) / len(impacts)
        
        # 评分逻辑（分数越高风险越低）
        score = 100.0
        
        # 根据事件数量扣分
        if event_count > 10:
            score -= 30
        elif event_count > 5:
            score -= 20
        elif event_count > 2:
            score -= 10
        
        # 根据严重程度扣分
        if avg_severity > 7:
            score -= 30
        elif avg_severity > 5:
            score -= 20
        elif avg_severity > 3:
            score -= 10
        
        # 根据市场影响扣分
        if avg_impact > 70:
            score -= 20
        elif avg_impact > 50:
            score -= 10
        
        score = max(0, min(100, score))
        
        # 判定风险等级
        if score >= 80:
            risk_level = "LOW"
        elif score >= 60:
            risk_level = "MEDIUM"
        elif score >= 40:
            risk_level = "HIGH"
        else:
            risk_level = "EXTREME"
        
        return {
            "score": round(score, 2),
            "event_count": event_count,
            "avg_severity": round(avg_severity, 2),
            "avg_market_impact": round(avg_impact, 2),
            "risk_level": risk_level
        }

    # ============= 私有方法：数据获取 =============

    async def fetch_external_events(self, query: str, days: int = 7) -> List[GeopoliticalEvent]:
        """公开发布的获取外部事件方法，支持自定义查询词"""
        if not self.news_api:
            return []
            
        gate = await api_monitor.can_call_provider(APIProvider.NEWS_API)
        if not gate.get("can_call", True):
            return []

        try:
            from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            articles = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.news_api.get_everything(
                    q=query,
                    from_param=from_date,
                    language='en',
                    sort_by='relevancy',
                    page_size=30
                )
            )
            
            events = []
            for article in articles.get('articles', []):
                event = self._article_to_event(article)
                if event:
                    events.append(event)
            return events
        except Exception as e:
            logger.error(f"Error in fetch_external_events: {e}")
            return []

    async def _fetch_from_news_api(self, days: int) -> List[GeopoliticalEvent]:
        """
        从News API获取地缘政治新闻（带Redis缓存和监控）
        
        Args:
            days: 获取最近N天的新闻
            
        Returns:
            GeopoliticalEvent对象列表
        """
        # 1. 尝试从Redis缓存获取
        redis_key = f"news_api:geopolitical_events:{days}d"
        cached_events = await cache.get(redis_key)
        if cached_events:
            print(f"[NewsAPI] Using Redis cache for {days} days events")
            # 将缓存的字典转换回对象
            return [self._dict_to_event(event_dict) for event_dict in cached_events]
        
        # 2. 检查API调用限制/冷却
        gate = await api_monitor.can_call_provider(APIProvider.NEWS_API)
        if not gate.get("can_call", True):
            print(f"[NewsAPI] Skip fetch due to cooldown/limit: {gate.get('reason')}")
            return []
        
        # 3. 调用API
        start_time = time.time()
        success = False
        error_msg = None
        events = []
        
        try:
            from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # 搜索关键词
            keywords = "war OR conflict OR sanctions OR crisis OR terror OR coup OR trade dispute"
            
            # 调用News API
            articles = self.news_api.get_everything(
                q=keywords,
                from_param=from_date,
                language='en',
                sort_by='relevancy',
                page_size=50
            )
            
            for article in articles.get('articles', []):
                event = self._article_to_event(article)
                if event:
                    events.append(event)
            
            # 缓存到Redis（4小时TTL）
            events_dict = [self._event_to_dict(e) for e in events]
            await cache.set(redis_key, events_dict, expire=self.cache_ttl_hours * 3600)
            success = True
            print(f"[NewsAPI] Successfully fetched {len(events)} events")
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error fetching from News API: {e}")
        
        # 4. 记录API调用
        response_time = (time.time() - start_time) * 1000
        await api_monitor.record_api_call(
            provider=APIProvider.NEWS_API,
            endpoint="get_everything",
            success=success,
            response_time_ms=response_time,
            error_message=error_msg
        )
        
        return events

    def _article_to_event(self, article: Dict) -> Optional[GeopoliticalEvent]:
        """
        将新闻文章转换为GeopoliticalEvent对象
        
        Args:
            article: News API返回的文章字典
            
        Returns:
            GeopoliticalEvent对象或None
        """
        try:
            title = article.get('title', '')
            description = article.get('description', '') or ''
            content = article.get('content', '') or ''
            
            # 合并文本用于分析
            full_text = f"{title} {description} {content}".lower()
            
            # 分类
            category = self._classify_event(full_text)
            
            # 评估严重程度
            severity_score = self._assess_severity(full_text)
            severity_level = self._severity_number_to_level(severity_score)
            
            # 评估市场影响
            market_impact = self._assess_market_impact(full_text, category, severity_score)
            
            # 提取受影响地区和行业
            affected_regions = self._extract_regions(full_text)
            affected_industries = self._extract_industries(full_text)
            
            # 创建事件对象
            event = GeopoliticalEvent(
                event_type="NEWS",
                title=title[:200],  # 限制长度
                description=description[:500] if description else None,
                event_date=datetime.strptime(article['publishedAt'][:10], '%Y-%m-%d'),
                news_source=article.get('source', {}).get('name', 'Unknown'),
                category=category.value,
                severity=severity_level.value,
                affected_regions=affected_regions,
                affected_industries=affected_industries,
                market_impact_score=market_impact,
                news_url=article.get('url'),
                created_at=datetime.now()
            )
            
            return event
            
        except Exception as e:
            print(f"Error converting article to event: {e}")
            return None

    async def _get_cached_events(
        self, 
        session: AsyncSession, 
        days: int
    ) -> Optional[List[GeopoliticalEvent]]:
        """获取缓存的事件"""
        cutoff_date = datetime.now() - timedelta(days=days)
        stmt = select(GeopoliticalEvent).where(
            GeopoliticalEvent.event_date >= cutoff_date
        ).order_by(GeopoliticalEvent.event_date.desc())
        
        result = await session.execute(stmt)
        events = list(result.scalars().all())
        return events if events else None

    async def _deduplicate_events(
        self, 
        session: AsyncSession, 
        new_events: List[GeopoliticalEvent]
    ) -> List[GeopoliticalEvent]:
        """
        事件去重
        
        逻辑：24小时内标题相似度>80%视为重复
        """
        # 获取最近24小时的事件
        one_day_ago = datetime.now() - timedelta(hours=24)
        stmt = select(GeopoliticalEvent).where(
            GeopoliticalEvent.created_at >= one_day_ago
        )
        result = await session.execute(stmt)
        existing_events = list(result.scalars().all())
        
        deduplicated = []
        for new_event in new_events:
            is_duplicate = False
            for existing in existing_events:
                similarity = self._calculate_title_similarity(
                    new_event.title, 
                    existing.title
                )
                if similarity > 0.8:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                deduplicated.append(new_event)
        
        return deduplicated

    # ============= 私有方法：分析和评估 =============

    def _classify_event(self, text: str) -> EventCategory:
        """根据关键词分类事件"""
        category_scores = {}
        
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword.lower() in text)
            category_scores[category] = score
        
        if max(category_scores.values()) == 0:
            return EventCategory.OTHER
        
        return max(category_scores, key=category_scores.get)

    def _assess_severity(self, text: str) -> int:
        """
        评估严重程度（1-10）
        
        基于关键词匹配
        """
        max_severity = 1
        
        for severity_level, keywords in self.SEVERITY_KEYWORDS.items():
            if any(keyword.lower() in text for keyword in keywords):
                max_severity = max(max_severity, severity_level)
        
        return min(10, max_severity)

    def _assess_market_impact(
        self, 
        text: str, 
        category: EventCategory, 
        severity: int
    ) -> int:
        """
        评估市场影响（0-100）
        
        综合考虑事件类别、严重程度和影响范围
        """
        base_impact = severity * 5  # 1-10分 -> 5-50分
        
        # 类别影响系数
        category_multiplier = {
            EventCategory.WAR: 2.0,
            EventCategory.TRADE_DISPUTE: 1.5,
            EventCategory.ENERGY_CRISIS: 1.8,
            EventCategory.TERRORISM: 1.3,
            EventCategory.POLITICAL_UNREST: 1.2,
            EventCategory.DIPLOMATIC_CRISIS: 1.0,
            EventCategory.OTHER: 0.8
        }
        
        base_impact *= category_multiplier.get(category, 1.0)
        
        # 根据影响范围加分
        for keyword, score_add in self.MARKET_IMPACT_KEYWORDS.items():
            if keyword in text:
                base_impact += score_add
        
        return min(100, int(base_impact))

    def _extract_regions(self, text: str) -> str:
        """提取受影响地区（简化）"""
        regions = []
        region_keywords = {
            "Global": ["global", "world", "worldwide"],
            "US": ["united states", "america", "us "],
            "China": ["china", "chinese"],
            "Europe": ["europe", "european", "eu "],
            "Middle East": ["middle east", "gulf"],
            "Asia": ["asia", "asian"]
        }
        
        for region, keywords in region_keywords.items():
            if any(kw in text for kw in keywords):
                regions.append(region)
        
        return ", ".join(regions) if regions else "Unspecified"

    def _extract_industries(self, text: str) -> str:
        """提取受影响行业（简化）"""
        industries = []
        industry_keywords = {
            "Energy": ["oil", "gas", "energy"],
            "Finance": ["bank", "financial", "market"],
            "Technology": ["tech", "semiconductor", "chip"],
            "Defense": ["military", "defense", "weapon"],
            "Agriculture": ["food", "agriculture", "grain"]
        }
        
        for industry, keywords in industry_keywords.items():
            if any(kw in text for kw in keywords):
                industries.append(industry)
        
        return ", ".join(industries) if industries else "General"

    # ============= 私有方法：辅助函数 =============

    def _severity_to_number(self, severity: str) -> int:
        """严重程度等级转数字"""
        mapping = {
            "LOW": 2,
            "MEDIUM": 5,
            "HIGH": 7.5,
            "CRITICAL": 9
        }
        return mapping.get(severity, 5)

    def _severity_number_to_level(self, score: int) -> SeverityLevel:
        """数字转严重程度等级"""
        if score >= 9:
            return SeverityLevel.CRITICAL
        elif score >= 7:
            return SeverityLevel.HIGH
        elif score >= 4:
            return SeverityLevel.MEDIUM
        else:
            return SeverityLevel.LOW

    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """
        计算标题相似度（简化版）
        
        基于共同单词比例
        """
        words1 = set(re.findall(r'\w+', title1.lower()))
        words2 = set(re.findall(r'\w+', title2.lower()))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0
    
    def _event_to_dict(self, event: GeopoliticalEvent) -> Dict[str, Any]:
        """将GeopoliticalEvent对象转换为字典（用于Redis缓存）"""
        return {
            "event_type": event.event_type,
            "title": event.title,
            "description": event.description,
            "event_date": event.event_date.isoformat() if event.event_date else None,
            "news_source": event.news_source,
            "category": event.category,
            "severity": event.severity,
            "affected_regions": event.affected_regions,
            "affected_industries": event.affected_industries,
            "market_impact_score": event.market_impact_score,
            "news_url": event.news_url
        }
    
    def _dict_to_event(self, data: Dict[str, Any]) -> GeopoliticalEvent:
        """将字典转换回GeopoliticalEvent对象（从Redis缓存恢复）"""
        return GeopoliticalEvent(
            event_type=data.get("event_type"),
            title=data.get("title"),
            description=data.get("description"),
            event_date=datetime.fromisoformat(data["event_date"]) if data.get("event_date") else None,
            news_source=data.get("news_source"),
            category=data.get("category"),
            severity=data.get("severity"),
            affected_regions=data.get("affected_regions"),
            affected_industries=data.get("affected_industries"),
            market_impact_score=data.get("market_impact_score"),
            news_url=data.get("news_url"),
            created_at=datetime.now()
        )
