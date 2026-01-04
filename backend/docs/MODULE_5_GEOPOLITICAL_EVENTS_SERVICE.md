# 模块5: 地缘政治事件服务设计

## 1. 服务概述

### 职责
- 从新闻API抓取地缘政治相关新闻
- 事件分类和严重程度评估
- 识别受影响的行业和市场
- 计算市场影响评分
- 存储和管理历史事件

### 数据源
- **News API** - 新闻聚合API
- **可选**: Bloomberg API, Reuters API, Financial Times API

---

## 2. 类设计

### 2.1 服务类结构

```python
# app/services/geopolitical_events_service.py

from typing import Optional, List, Dict
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from newsapi import NewsApiClient
import re

from app.models.macro_risk import GeopoliticalEvent
from app.core.config import settings
from app.schemas.macro_risk import GeopoliticalEventDTO

class GeopoliticalEventsService:
    """地缘政治事件服务"""
    
    # 关键词分类
    EVENT_CATEGORIES = {
        "战争冲突": [
            "war", "conflict", "military", "invasion", "attack", "strike",
            "战争", "冲突", "军事", "入侵", "袭击"
        ],
        "贸易争端": [
            "trade war", "tariff", "sanctions", "embargo", "trade dispute",
            "贸易战", "关税", "制裁", "禁运", "贸易争端"
        ],
        "政治动荡": [
            "coup", "revolution", "protest", "riot", "election crisis",
            "政变", "革命", "抗议", "暴乱", "选举危机"
        ],
        "恐怖袭击": [
            "terrorism", "terrorist attack", "bombing", "恐怖主义", "恐怖袭击", "爆炸"
        ],
        "外交危机": [
            "diplomatic crisis", "relations", "tension", "dispute",
            "外交危机", "关系", "紧张", "争端"
        ],
        "能源危机": [
            "energy crisis", "oil", "gas", "OPEC",
            "能源危机", "石油", "天然气"
        ]
    }
    
    # 严重程度关键词
    SEVERITY_KEYWORDS = {
        "极高": ["war", "nuclear", "invasion", "genocide", "战争", "核", "入侵"],
        "高": ["crisis", "attack", "strike", "危机", "袭击", "打击"],
        "中": ["tension", "dispute", "protest", "紧张", "争端", "抗议"],
        "低": ["concern", "talks", "meeting", "关切", "会谈", "会议"]
    }
    
    # 受影响行业映射
    AFFECTED_SECTORS = {
        "战争冲突": ["defense", "energy", "commodities"],
        "贸易争端": ["manufacturing", "technology", "agriculture"],
        "政治动荡": ["emerging_markets", "commodities"],
        "能源危机": ["energy", "transportation", "chemicals"],
        "恐怖袭击": ["insurance", "travel", "defense"]
    }
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.news_api = NewsApiClient(api_key=settings.NEWS_API_KEY)
    
    async def fetch_recent_events(
        self,
        days: int = 7
    ) -> List[GeopoliticalEvent]:
        """抓取最近N天的地缘政治事件"""
        pass
    
    async def get_recent_events(
        self,
        days: int = 7
    ) -> List[GeopoliticalEvent]:
        """获取最近事件（优先缓存）"""
        pass
    
    def _classify_event(
        self,
        title: str,
        description: str,
        content: str
    ) -> str:
        """事件分类"""
        pass
    
    def _assess_severity(
        self,
        title: str,
        description: str,
        content: str,
        category: str
    ) -> int:
        """评估严重程度 (1-10)"""
        pass
    
    def _identify_affected_regions(
        self,
        title: str,
        content: str
    ) -> List[str]:
        """识别受影响地区"""
        pass
    
    def _identify_affected_industries(
        self,
        category: str,
        title: str,
        content: str
    ) -> List[str]:
        """识别受影响行业"""
        pass
    
    def _calculate_market_impact(
        self,
        severity: int,
        affected_regions: List[str],
        affected_industries: List[str],
        category: str
    ) -> int:
        """计算市场影响评分 (0-100)"""
        pass
    
    async def _save_event(
        self,
        event: GeopoliticalEvent
    ) -> None:
        """保存事件到数据库"""
        pass
    
    async def _get_cached_events(
        self,
        days: int
    ) -> List[GeopoliticalEvent]:
        """从数据库获取缓存事件"""
        pass
    
    def _deduplicate_events(
        self,
        events: List[GeopoliticalEvent]
    ) -> List[GeopoliticalEvent]:
        """去重相似事件"""
        pass
```

---

## 3. 事件抓取设计

### 3.1 News API集成

```python
async def fetch_recent_events(self, days: int = 7) -> List[GeopoliticalEvent]:
    """
    从News API抓取地缘政治新闻
    
    参数:
        days: 回溯天数
    
    返回:
        GeopoliticalEvent对象列表
    """
    
    events = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # 定义搜索关键词（英文）
    keywords = [
        "geopolitical OR war OR conflict OR sanctions",
        "trade war OR tariff OR embargo",
        "political crisis OR coup OR revolution",
        "terrorism OR terrorist attack",
        "diplomatic tension OR relations crisis",
        "energy crisis OR OPEC OR oil embargo"
    ]
    
    try:
        for query in keywords:
            # 调用News API
            response = self.news_api.get_everything(
                q=query,
                from_param=start_date.strftime('%Y-%m-%d'),
                to=end_date.strftime('%Y-%m-%d'),
                language='en',
                sort_by='relevancy',
                page_size=20  # 每个查询最多20条
            )
            
            articles = response.get('articles', [])
            
            for article in articles:
                # 提取信息
                title = article.get('title', '')
                description = article.get('description', '')
                content = article.get('content', '')
                url = article.get('url', '')
                published_at = article.get('publishedAt', '')
                source = article.get('source', {}).get('name', 'Unknown')
                
                # 解析日期
                try:
                    event_date = datetime.strptime(published_at, '%Y-%m-%dT%H:%M:%SZ')
                except:
                    event_date = datetime.utcnow()
                
                # 分类和评估
                category = self._classify_event(title, description, content)
                severity = self._assess_severity(title, description, content, category)
                affected_regions = self._identify_affected_regions(title, content)
                affected_industries = self._identify_affected_industries(category, title, content)
                market_impact = self._calculate_market_impact(
                    severity, affected_regions, affected_industries, category
                )
                
                # 创建事件对象
                event = GeopoliticalEvent(
                    event_date=event_date,
                    event_category=category,
                    event_title=title,
                    event_description=description or title,
                    severity=severity,
                    affected_regions=",".join(affected_regions),
                    affected_industries=",".join(affected_industries),
                    market_impact_score=market_impact,
                    source_url=url,
                    data_source=source,
                    timestamp=datetime.utcnow()
                )
                
                events.append(event)
        
        # 去重
        events = self._deduplicate_events(events)
        
        # 保存到数据库
        for event in events:
            await self._save_event(event)
        
        await self.session.commit()
        
        return events
        
    except Exception as e:
        logger.error(f"Failed to fetch geopolitical events: {e}")
        return []
```

---

## 4. 事件分类算法

### 4.1 基于关键词匹配

```python
def _classify_event(self, title: str, description: str, content: str) -> str:
    """
    事件分类
    
    方法: 关键词匹配 + 权重计分
    
    分类:
    - 战争冲突
    - 贸易争端
    - 政治动荡
    - 恐怖袭击
    - 外交危机
    - 能源危机
    - 其他
    """
    
    # 合并所有文本
    text = f"{title} {description} {content}".lower()
    
    # 计算每个类别的匹配分数
    scores = {}
    for category, keywords in self.EVENT_CATEGORIES.items():
        score = 0
        for keyword in keywords:
            # 标题匹配权重更高
            if keyword.lower() in title.lower():
                score += 3
            # 描述匹配
            if keyword.lower() in description.lower():
                score += 2
            # 内容匹配
            if keyword.lower() in text:
                score += 1
        scores[category] = score
    
    # 返回得分最高的类别
    if scores:
        best_category = max(scores, key=scores.get)
        if scores[best_category] > 0:
            return best_category
    
    return "其他"
```

---

## 5. 严重程度评估

### 5.1 多因素评分

```python
def _assess_severity(
    self,
    title: str,
    description: str,
    content: str,
    category: str
) -> int:
    """
    评估严重程度 (1-10)
    
    评分因素:
    1. 关键词严重程度 (40%)
    2. 事件类别基础分 (30%)
    3. 文本情感强度 (30%)
    
    评分标准:
    - 9-10: 极端严重（核战争、全面战争）
    - 7-8: 非常严重（局部战争、重大危机）
    - 5-6: 严重（贸易战升级、恐怖袭击）
    - 3-4: 中等（外交紧张、小规模冲突）
    - 1-2: 轻微（口头争端、小摩擦）
    """
    
    base_score = 5  # 基础分
    text = f"{title} {description} {content}".lower()
    
    # 1. 关键词严重程度
    keyword_score = 0
    if any(kw in text for kw in self.SEVERITY_KEYWORDS["极高"]):
        keyword_score = 4
    elif any(kw in text for kw in self.SEVERITY_KEYWORDS["高"]):
        keyword_score = 3
    elif any(kw in text for kw in self.SEVERITY_KEYWORDS["中"]):
        keyword_score = 2
    elif any(kw in text for kw in self.SEVERITY_KEYWORDS["低"]):
        keyword_score = 1
    
    # 2. 事件类别基础分
    category_scores = {
        "战争冲突": 8,
        "恐怖袭击": 7,
        "贸易争端": 6,
        "政治动荡": 6,
        "能源危机": 5,
        "外交危机": 4,
        "其他": 3
    }
    category_score = category_scores.get(category, 3)
    
    # 3. 情感强度（简化：检查强烈词汇）
    intensity_words = [
        "catastrophic", "devastating", "massive", "unprecedented",
        "critical", "severe", "major", "灾难性", "毁灭性", "重大", "严重"
    ]
    intensity_score = sum(2 for word in intensity_words if word in text)
    intensity_score = min(intensity_score, 4)  # 最多4分
    
    # 综合评分
    final_score = int(
        category_score * 0.5 +
        keyword_score * 0.3 +
        intensity_score * 0.2
    )
    
    return max(1, min(10, final_score))  # 限制在1-10范围
```

---

## 6. 地区和行业识别

### 6.1 地区识别

```python
def _identify_affected_regions(self, title: str, content: str) -> List[str]:
    """
    识别受影响地区
    
    方法: 地理实体识别（简化版）
    """
    
    text = f"{title} {content}".lower()
    
    regions = {
        "北美": ["us", "usa", "united states", "america", "canada", "mexico", "美国", "加拿大"],
        "欧洲": ["europe", "eu", "uk", "germany", "france", "russia", "欧洲", "俄罗斯"],
        "亚太": ["china", "japan", "korea", "asia", "india", "中国", "日本", "韩国", "印度"],
        "中东": ["middle east", "iran", "iraq", "saudi", "israel", "中东", "伊朗", "以色列"],
        "拉美": ["latin america", "brazil", "argentina", "拉美", "巴西"],
        "非洲": ["africa", "非洲"]
    }
    
    affected = []
    for region, keywords in regions.items():
        if any(keyword in text for keyword in keywords):
            affected.append(region)
    
    return affected if affected else ["全球"]
```

### 6.2 行业识别

```python
def _identify_affected_industries(
    self,
    category: str,
    title: str,
    content: str
) -> List[str]:
    """
    识别受影响行业
    
    方法: 类别映射 + 关键词补充
    """
    
    # 基础行业（根据事件类别）
    industries = self.AFFECTED_SECTORS.get(category, [])
    
    text = f"{title} {content}".lower()
    
    # 补充行业关键词检测
    industry_keywords = {
        "technology": ["tech", "chip", "semiconductor", "software", "科技", "芯片"],
        "finance": ["bank", "financial", "market", "金融", "银行"],
        "healthcare": ["health", "pharma", "medical", "医疗", "制药"],
        "energy": ["oil", "gas", "energy", "石油", "能源"],
        "defense": ["defense", "military", "weapon", "国防", "军事"],
        "transportation": ["airline", "shipping", "transport", "航空", "运输"],
        "manufacturing": ["manufacturing", "factory", "制造", "工厂"]
    }
    
    for industry, keywords in industry_keywords.items():
        if any(keyword in text for keyword in keywords):
            if industry not in industries:
                industries.append(industry)
    
    return industries if industries else ["broad_market"]
```

---

## 7. 市场影响评分

### 7.1 综合评分算法

```python
def _calculate_market_impact(
    self,
    severity: int,
    affected_regions: List[str],
    affected_industries: List[str],
    category: str
) -> int:
    """
    计算市场影响评分 (0-100)
    
    评分因素:
    1. 严重程度 (40%): severity * 10
    2. 地区范围 (30%): 受影响地区数量
    3. 行业范围 (20%): 受影响行业数量
    4. 事件类别 (10%): 不同类别的市场敏感度
    
    评分标准:
    - 80-100: 极高影响（全球性危机）
    - 60-79: 高影响（区域性重大事件）
    - 40-59: 中等影响（局部冲突）
    - 20-39: 低影响（外交摩擦）
    - 0-19: 微弱影响（口头争端）
    """
    
    # 1. 严重程度得分（40%）
    severity_score = severity * 4  # 转换为0-40范围
    
    # 2. 地区范围得分（30%）
    region_count = len(affected_regions)
    if region_count >= 3 or "全球" in affected_regions:
        region_score = 30
    elif region_count == 2:
        region_score = 20
    else:
        region_score = 10
    
    # 3. 行业范围得分（20%）
    industry_count = len(affected_industries)
    if industry_count >= 5:
        industry_score = 20
    elif industry_count >= 3:
        industry_score = 15
    elif industry_count >= 1:
        industry_score = 10
    else:
        industry_score = 5
    
    # 4. 事件类别敏感度（10%）
    category_sensitivity = {
        "战争冲突": 10,
        "能源危机": 9,
        "贸易争端": 8,
        "恐怖袭击": 7,
        "政治动荡": 6,
        "外交危机": 5,
        "其他": 3
    }
    category_score = category_sensitivity.get(category, 3)
    
    # 综合评分
    final_score = severity_score + region_score + industry_score + category_score
    
    return min(100, final_score)  # 限制最大值为100
```

---

## 8. 事件去重

### 8.1 相似度检测

```python
def _deduplicate_events(
    self,
    events: List[GeopoliticalEvent]
) -> List[GeopoliticalEvent]:
    """
    去重相似事件
    
    方法: 标题文本相似度 + 时间窗口
    
    规则:
    - 24小时内，标题相似度 > 70% 认为是同一事件
    - 保留严重程度最高的版本
    """
    
    if not events:
        return events
    
    # 按日期分组
    from collections import defaultdict
    grouped = defaultdict(list)
    
    for event in events:
        date_key = event.event_date.strftime('%Y-%m-%d')
        grouped[date_key].append(event)
    
    # 对每组进行去重
    deduplicated = []
    for date_key, day_events in grouped.items():
        seen_titles = set()
        for event in day_events:
            # 简化的相似度检测：去除标点后比较
            normalized_title = re.sub(r'[^\w\s]', '', event.event_title.lower())
            
            is_duplicate = False
            for seen in seen_titles:
                # 计算简单的词重叠率
                set1 = set(normalized_title.split())
                set2 = set(seen.split())
                if set1 and set2:
                    overlap = len(set1 & set2) / max(len(set1), len(set2))
                    if overlap > 0.7:
                        is_duplicate = True
                        break
            
            if not is_duplicate:
                seen_titles.add(normalized_title)
                deduplicated.append(event)
    
    return deduplicated
```

---

## 9. 缓存机制

### 9.1 数据库交互

```python
async def get_recent_events(self, days: int = 7) -> List[GeopoliticalEvent]:
    """
    获取最近事件（优先缓存）
    
    逻辑:
    1. 查询数据库缓存
    2. 如果最新事件 < 4小时，使用缓存
    3. 否则重新抓取
    """
    
    # 查询缓存
    cached_events = await self._get_cached_events(days)
    
    if cached_events:
        # 检查最新事件时间
        latest_event = max(cached_events, key=lambda e: e.timestamp)
        age = datetime.utcnow() - latest_event.timestamp
        
        if age < timedelta(hours=4):
            return cached_events
    
    # 重新抓取
    new_events = await self.fetch_recent_events(days)
    return new_events

async def _get_cached_events(self, days: int) -> List[GeopoliticalEvent]:
    """从数据库获取缓存事件"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    stmt = select(GeopoliticalEvent).where(
        GeopoliticalEvent.event_date >= cutoff_date
    ).order_by(GeopoliticalEvent.event_date.desc())
    
    result = await self.session.execute(stmt)
    return result.scalars().all()

async def _save_event(self, event: GeopoliticalEvent) -> None:
    """保存事件到数据库"""
    # 检查是否已存在（根据标题和日期）
    stmt = select(GeopoliticalEvent).where(
        and_(
            GeopoliticalEvent.event_title == event.event_title,
            GeopoliticalEvent.event_date == event.event_date
        )
    )
    result = await self.session.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if not existing:
        self.session.add(event)
```

---

## 10. 错误处理

### 10.1 API限流和降级

```python
async def fetch_recent_events_with_fallback(
    self,
    days: int = 7
) -> List[GeopoliticalEvent]:
    """
    带降级策略的事件抓取
    
    降级策略:
    1. News API失败 → 使用数据库缓存
    2. 缓存为空 → 返回空列表，不阻塞主流程
    """
    
    try:
        return await self.fetch_recent_events(days)
    except Exception as e:
        logger.error(f"Failed to fetch events from News API: {e}")
        
        # 降级：使用缓存
        cached = await self._get_cached_events(days * 2)  # 扩大查询范围
        if cached:
            logger.info(f"Using {len(cached)} cached events as fallback")
            return cached
        
        # 最终降级：返回空列表
        logger.warning("No cached events available, returning empty list")
        return []
```

---

## 11. 实现检查清单

- [ ] 创建 `app/services/geopolitical_events_service.py`
- [ ] 集成News API客户端
- [ ] 实现事件抓取逻辑
- [ ] 实现事件分类算法
- [ ] 实现严重程度评估
- [ ] 实现地区识别
- [ ] 实现行业识别
- [ ] 实现市场影响评分
- [ ] 实现去重逻辑
- [ ] 实现缓存机制
- [ ] 添加错误处理和降级策略
- [ ] 配置News API Key
- [ ] 编写单元测试
- [ ] 性能测试（抓取 < 10s）

---

**预计工作量**: 8-10小时
**优先级**: P1 (重要功能)
**外部依赖**: News API Key (需注册)
**月度成本**: $29-$449 (根据调用量)

**替代方案**: 如果成本考虑，可以使用免费的RSS源或网页爬虫
