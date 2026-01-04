# 模块6: AI分析服务设计

## 1. 服务概述

### 职责
- 使用GPT-4生成AI分析摘要
- 技术面分析解读
- 基本面分析解读
- 宏观风险分析解读
- 投资建议生成
- Prompt工程和优化

### 依赖
- **OpenAI API** (GPT-4)
- 技术/基本面/宏观数据

---

## 2. 类设计

### 2.1 服务类结构

```python
# app/services/ai_analysis_service.py

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import openai
from openai import AsyncOpenAI
import json

from app.core.config import settings

class AIAnalysisService:
    """AI分析服务"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4-turbo-preview"  # 或 "gpt-4"
        self.max_tokens = 500
        self.temperature = 0.7
    
    async def generate_technical_summary(
        self,
        symbol: str,
        technical_data: Dict[str, Any]
    ) -> str:
        """生成技术面分析摘要"""
        pass
    
    async def generate_fundamental_summary(
        self,
        symbol: str,
        fundamental_data: Dict[str, Any]
    ) -> str:
        """生成基本面分析摘要"""
        pass
    
    async def generate_position_recommendation(
        self,
        symbol: str,
        technical_score: float,
        fundamental_score: float,
        sentiment_score: float,
        overall_score: float
    ) -> str:
        """生成持仓建议"""
        pass
    
    async def generate_macro_risk_summary(
        self,
        overall_risk_score: float,
        dimension_scores: Dict[str, float],
        key_events: list
    ) -> str:
        """生成宏观风险分析摘要"""
        pass
    
    def _build_technical_prompt(
        self,
        symbol: str,
        technical_data: Dict[str, Any]
    ) -> str:
        """构建技术分析Prompt"""
        pass
    
    def _build_fundamental_prompt(
        self,
        symbol: str,
        fundamental_data: Dict[str, Any]
    ) -> str:
        """构建基本面分析Prompt"""
        pass
    
    def _build_position_prompt(
        self,
        symbol: str,
        technical_score: float,
        fundamental_score: float,
        sentiment_score: float,
        overall_score: float
    ) -> str:
        """构建持仓建议Prompt"""
        pass
    
    def _build_macro_prompt(
        self,
        overall_risk_score: float,
        dimension_scores: Dict[str, float],
        key_events: list
    ) -> str:
        """构建宏观风险Prompt"""
        pass
    
    async def _call_gpt4(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """调用GPT-4 API（带重试）"""
        pass
    
    def _extract_json_from_response(
        self,
        response: str
    ) -> Optional[Dict]:
        """从响应中提取JSON（如果需要结构化输出）"""
        pass
```

---

## 3. Prompt工程设计

### 3.1 技术面分析Prompt

```python
def _build_technical_prompt(self, symbol: str, technical_data: Dict[str, Any]) -> str:
    """
    技术面分析Prompt模板
    
    要求:
    - 专业的华尔街分析师口吻
    - 突出关键信号
    - 100字以内
    - 中文输出
    """
    
    prompt = f"""你是一位专业的量化分析师，请基于以下技术指标对 {symbol} 进行简要分析：

技术指标:
- 趋势: {technical_data.get('trend', 'N/A')}
- RSI: {technical_data.get('rsi', 'N/A')} ({technical_data.get('rsi_status', 'N/A')})
- MACD信号: {technical_data.get('macd_signal', 'N/A')}
- 布林带位置: {technical_data.get('bb_position', 'N/A')}
- 支撑位: ${technical_data.get('support', 'N/A')}
- 阻力位: ${technical_data.get('resistance', 'N/A')}
- 成交量状态: {technical_data.get('volume_status', 'N/A')}

请用1-2句话总结技术面状况，并给出短期操作建议（100字以内）。要求：
1. 突出最关键的1-2个信号
2. 明确看多/看空/中性
3. 给出具体的支撑/阻力位参考
4. 专业、简洁、可执行

输出格式：[技术面评价] + [操作建议]
"""
    return prompt
```

### 3.2 基本面分析Prompt

```python
def _build_fundamental_prompt(self, symbol: str, fundamental_data: Dict[str, Any]) -> str:
    """
    基本面分析Prompt模板
    
    要求:
    - 价值投资视角
    - 对比行业平均
    - 120字以内
    - 中文输出
    """
    
    valuation = fundamental_data.get('valuation', {})
    profitability = fundamental_data.get('profitability', {})
    growth = fundamental_data.get('growth', {})
    health = fundamental_data.get('financial_health', {})
    
    prompt = f"""你是一位资深的价值投资分析师，请基于以下基本面数据对 {symbol} 进行评估：

估值指标:
- PE: {valuation.get('pe_ratio', 'N/A')}
- PB: {valuation.get('pb_ratio', 'N/A')}
- PEG: {valuation.get('peg_ratio', 'N/A')}
- 估值评分: {valuation.get('score', 'N/A')}/100

盈利能力:
- ROE: {profitability.get('roe', 'N/A')}%
- 净利率: {profitability.get('net_margin', 'N/A')}%
- 盈利评分: {profitability.get('score', 'N/A')}/100

成长性:
- 营收增长: {growth.get('revenue_growth', 'N/A')}%
- 盈利增长: {growth.get('earnings_growth', 'N/A')}%
- 成长评分: {growth.get('score', 'N/A')}/100

财务健康:
- 流动比率: {health.get('current_ratio', 'N/A')}
- 资产负债率: {health.get('debt_to_equity', 'N/A')}
- 健康评分: {health.get('score', 'N/A')}/100

请用2-3句话评估公司的投资价值（120字以内）。要求：
1. 判断估值是否合理（低估/合理/高估）
2. 评价盈利质量和成长性
3. 指出关键风险（如有）
4. 给出长期持有价值判断

输出格式：[估值判断] + [经营评价] + [投资建议]
"""
    return prompt
```

### 3.3 持仓建议Prompt

```python
def _build_position_prompt(
    self,
    symbol: str,
    technical_score: float,
    fundamental_score: float,
    sentiment_score: float,
    overall_score: float
) -> str:
    """
    持仓建议Prompt模板
    
    要求:
    - 综合三维度分析
    - 明确操作建议
    - 80字以内
    """
    
    prompt = f"""你是一位专业的投资顾问，请基于以下三维度评分对 {symbol} 给出持仓建议：

评分概况:
- 技术面: {technical_score}/100
- 基本面: {fundamental_score}/100
- 情绪面: {sentiment_score}/100
- 综合评分: {overall_score}/100

评分解读:
- 80-100: 优秀（强烈推荐）
- 60-79: 良好（建议持有）
- 40-59: 中等（谨慎观望）
- 0-39: 较差（建议减仓）

请给出明确的操作建议（80字以内）。要求：
1. 明确建议：买入/持有/减仓/清仓
2. 给出建议仓位比例（如适用）
3. 说明核心理由（1-2个要点）
4. 果断、清晰、可执行

输出格式：[操作建议] + [仓位比例] + [核心理由]
"""
    return prompt
```

### 3.4 宏观风险Prompt

```python
def _build_macro_prompt(
    self,
    overall_risk_score: float,
    dimension_scores: Dict[str, float],
    key_events: list
) -> str:
    """
    宏观风险分析Prompt模板
    
    要求:
    - 华尔街机构视角
    - 突出系统性风险
    - 150字以内
    """
    
    # 提取关键事件摘要
    events_summary = ""
    if key_events:
        events_summary = "\n".join([
            f"- {event.get('title', '')} (严重度: {event.get('severity', 0)}/10)"
            for event in key_events[:3]  # 最多3个
        ])
    
    prompt = f"""你是一位宏观策略分析师，请基于当前宏观风险状况给出市场展望：

宏观风险评分:
- 综合风险评分: {overall_risk_score}/100 (分数越高风险越低)
- 货币政策风险: {dimension_scores.get('monetary_policy', 0)}/100
- 地缘政治风险: {dimension_scores.get('geopolitical', 0)}/100
- 行业泡沫风险: {dimension_scores.get('sector_bubble', 0)}/100
- 经济周期风险: {dimension_scores.get('economic_cycle', 0)}/100
- 市场情绪风险: {dimension_scores.get('market_sentiment', 0)}/100

近期关键事件:
{events_summary if events_summary else "暂无重大事件"}

风险等级:
- 80-100: 低风险（宏观环境良好）
- 60-79: 中等风险（保持关注）
- 40-59: 高风险（控制仓位）
- 0-39: 极端风险（防御为主）

请用2-3句话分析当前宏观环境（150字以内）。要求：
1. 判断整体风险水平和趋势
2. 指出最大的风险因素（1-2个）
3. 给出资产配置建议（进攻/平衡/防御）
4. 专业、宏观、前瞻性

输出格式：[风险判断] + [关键因素] + [配置建议]
"""
    return prompt
```

---

## 4. GPT-4调用实现

### 4.1 异步调用

```python
async def _call_gpt4(
    self,
    prompt: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None
) -> str:
    """
    调用GPT-4 API
    
    参数:
        prompt: 输入提示
        max_tokens: 最大token数
        temperature: 生成随机性 (0-1)
    
    返回:
        生成的文本
    """
    
    try:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一位经验丰富的投资分析师，擅长用简洁专业的语言分析市场。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"GPT-4 API call failed: {e}")
        raise
```

### 4.2 带重试和降级

```python
async def _call_gpt4_with_retry(
    self,
    prompt: str,
    max_retries: int = 3
) -> str:
    """
    带重试和降级的GPT-4调用
    
    降级策略:
    1. GPT-4失败 → 使用GPT-3.5-turbo
    2. API完全不可用 → 使用规则引擎生成
    """
    
    import asyncio
    
    # 尝试GPT-4
    for attempt in range(max_retries):
        try:
            return await self._call_gpt4(prompt)
        except openai.RateLimitError:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2  # 指数退避
                logger.warning(f"Rate limit hit, waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("Rate limit exceeded, falling back to GPT-3.5")
                break
        except Exception as e:
            logger.error(f"GPT-4 attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                break
    
    # 降级到GPT-3.5
    try:
        original_model = self.model
        self.model = "gpt-3.5-turbo"
        result = await self._call_gpt4(prompt)
        self.model = original_model
        return result
    except Exception as e:
        logger.error(f"GPT-3.5 fallback failed: {e}")
    
    # 最终降级：规则引擎
    return self._generate_rule_based_summary(prompt)

def _generate_rule_based_summary(self, prompt: str) -> str:
    """
    规则引擎生成（最终降级）
    
    简单的模板填充
    """
    return "AI分析服务暂时不可用，请参考各项评分指标进行判断。"
```

---

## 5. 主入口实现

### 5.1 技术面摘要生成

```python
async def generate_technical_summary(
    self,
    symbol: str,
    technical_data: Dict[str, Any]
) -> str:
    """
    生成技术面分析摘要
    
    参数:
        symbol: 股票代码
        technical_data: 技术指标数据
    
    返回:
        AI生成的分析摘要
    """
    
    prompt = self._build_technical_prompt(symbol, technical_data)
    
    try:
        summary = await self._call_gpt4_with_retry(prompt)
        return summary
    except Exception as e:
        logger.error(f"Failed to generate technical summary for {symbol}: {e}")
        return f"{symbol}技术面分析暂时不可用"
```

### 5.2 基本面摘要生成

```python
async def generate_fundamental_summary(
    self,
    symbol: str,
    fundamental_data: Dict[str, Any]
) -> str:
    """生成基本面分析摘要"""
    
    prompt = self._build_fundamental_prompt(symbol, fundamental_data)
    
    try:
        summary = await self._call_gpt4_with_retry(prompt)
        return summary
    except Exception as e:
        logger.error(f"Failed to generate fundamental summary for {symbol}: {e}")
        return f"{symbol}基本面分析暂时不可用"
```

### 5.3 持仓建议生成

```python
async def generate_position_recommendation(
    self,
    symbol: str,
    technical_score: float,
    fundamental_score: float,
    sentiment_score: float,
    overall_score: float
) -> str:
    """生成持仓建议"""
    
    prompt = self._build_position_prompt(
        symbol, technical_score, fundamental_score, sentiment_score, overall_score
    )
    
    try:
        recommendation = await self._call_gpt4_with_retry(prompt)
        return recommendation
    except Exception as e:
        logger.error(f"Failed to generate recommendation for {symbol}: {e}")
        return f"{symbol}投资建议生成失败"
```

### 5.4 宏观风险摘要生成

```python
async def generate_macro_risk_summary(
    self,
    overall_risk_score: float,
    dimension_scores: Dict[str, float],
    key_events: list
) -> str:
    """生成宏观风险分析摘要"""
    
    prompt = self._build_macro_prompt(overall_risk_score, dimension_scores, key_events)
    
    try:
        summary = await self._call_gpt4_with_retry(prompt)
        return summary
    except Exception as e:
        logger.error(f"Failed to generate macro risk summary: {e}")
        return "宏观风险分析暂时不可用"
```

---

## 6. 成本控制

### 6.1 Token使用优化

```python
class AIAnalysisService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        # 根据使用场景选择模型
        self.models = {
            "high_precision": "gpt-4-turbo-preview",  # $10/$30 per 1M tokens
            "balanced": "gpt-3.5-turbo",              # $0.5/$1.5 per 1M tokens
            "fast": "gpt-3.5-turbo-1106"              # 最快
        }
        
        # 默认使用平衡模式
        self.model = self.models["balanced"]
        
    def _truncate_prompt(self, prompt: str, max_length: int = 2000) -> str:
        """截断过长的prompt"""
        if len(prompt) > max_length:
            return prompt[:max_length] + "..."
        return prompt
```

### 6.2 缓存策略

```python
from functools import lru_cache
from typing import Tuple

class AIAnalysisService:
    def __init__(self):
        # ... existing code ...
        self._cache = {}
        self.cache_ttl = timedelta(hours=1)
    
    def _get_cache_key(self, prompt: str) -> str:
        """生成缓存键"""
        import hashlib
        return hashlib.md5(prompt.encode()).hexdigest()
    
    async def _call_gpt4_with_cache(self, prompt: str) -> str:
        """带缓存的GPT-4调用"""
        cache_key = self._get_cache_key(prompt)
        
        # 检查缓存
        if cache_key in self._cache:
            cached_value, timestamp = self._cache[cache_key]
            if datetime.utcnow() - timestamp < self.cache_ttl:
                logger.info("Using cached AI response")
                return cached_value
        
        # 调用API
        result = await self._call_gpt4_with_retry(prompt)
        
        # 保存缓存
        self._cache[cache_key] = (result, datetime.utcnow())
        
        return result
```

---

## 7. 实现检查清单

- [ ] 创建 `app/services/ai_analysis_service.py`
- [ ] 集成OpenAI API客户端
- [ ] 实现4种Prompt模板
- [ ] 实现GPT-4异步调用
- [ ] 实现重试和降级策略
- [ ] 实现规则引擎降级
- [ ] 实现缓存机制
- [ ] 实现Token使用优化
- [ ] 配置OpenAI API Key
- [ ] 编写单元测试
- [ ] 成本监控（每次调用 < $0.01）

---

**预计工作量**: 6-8小时
**优先级**: P1 (增值功能，可选)
**外部依赖**: OpenAI API Key
**月度成本**: 
- GPT-4: ~$50-100 (1000次调用/天)
- GPT-3.5: ~$5-10 (1000次调用/天)

**节约建议**:
1. 优先使用GPT-3.5-turbo（成本低10倍）
2. 实现积极的缓存策略
3. 考虑批处理请求
4. 可选：初期使用规则引擎，后续逐步引入AI
