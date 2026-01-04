"""
AI分析服务 - 使用GPT生成持仓和宏观分析摘要

功能:
1. 技术分析AI摘要
2. 基本面分析AI摘要
3. 持仓综合评估AI建议
4. 宏观风险AI解读

回退策略: GPT-4 → GPT-3.5-turbo → 规则生成
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import json

from app.core.config import settings

logger = logging.getLogger(__name__)

# OpenAI客户端（延迟初始化）
_openai_client = None


def _get_openai_client():
    """获取OpenAI客户端（懒加载）"""
    global _openai_client
    
    if _openai_client is None:
        if not settings.OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not configured, AI analysis will use rule-based fallback")
            return None
        
        try:
            from openai import AsyncOpenAI
            _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("OpenAI client initialized successfully")
        except ImportError:
            logger.error("openai package not installed, run: pip install openai")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            return None
    
    return _openai_client


class AIAnalysisService:
    """AI分析服务 - 基于GPT生成智能摘要和建议"""
    
    def __init__(self):
        self.client = _get_openai_client()
        self.models = ["gpt-4", "gpt-3.5-turbo"]  # 回退顺序
        self.max_retries = 2
    
    async def generate_technical_summary(
        self,
        symbol: str,
        technical_data: Dict[str, Any]
    ) -> str:
        """生成技术分析AI摘要
        
        Args:
            symbol: 股票代码
            technical_data: 技术指标数据（趋势、动量、波动率、支撑阻力等）
        
        Returns:
            AI生成的技术分析摘要（中文）
        """
        prompt = self._build_technical_prompt(symbol, technical_data)
        
        summary = await self._call_gpt(prompt, max_tokens=300)
        
        if not summary:
            # 回退到规则生成
            summary = self._rule_based_technical_summary(symbol, technical_data)
        
        return summary
    
    async def generate_fundamental_summary(
        self,
        symbol: str,
        fundamental_data: Dict[str, Any]
    ) -> str:
        """生成基本面分析AI摘要
        
        Args:
            symbol: 股票代码
            fundamental_data: 基本面数据（估值、盈利能力、成长性、财务健康度）
        
        Returns:
            AI生成的基本面分析摘要（中文）
        """
        prompt = self._build_fundamental_prompt(symbol, fundamental_data)
        
        summary = await self._call_gpt(prompt, max_tokens=300)
        
        if not summary:
            # 回退到规则生成
            summary = self._rule_based_fundamental_summary(symbol, fundamental_data)
        
        return summary
    
    async def generate_position_advice(
        self,
        symbol: str,
        position_data: Dict[str, Any],
        technical_score: float,
        fundamental_score: float,
        overall_score: float
    ) -> str:
        """生成持仓综合评估AI建议
        
        Args:
            symbol: 股票代码
            position_data: 持仓数据（成本、收益、风险等）
            technical_score: 技术面评分 (0-100)
            fundamental_score: 基本面评分 (0-100)
            overall_score: 综合评分 (0-100)
        
        Returns:
            AI生成的持仓建议（中文）
        """
        prompt = self._build_position_advice_prompt(
            symbol, position_data, technical_score, fundamental_score, overall_score
        )
        
        advice = await self._call_gpt(prompt, max_tokens=400)
        
        if not advice:
            # 回退到规则生成
            advice = self._rule_based_position_advice(
                symbol, overall_score, technical_score, fundamental_score
            )
        
        return advice
    
    async def generate_macro_analysis(
        self,
        macro_data: Dict[str, Any]
    ) -> str:
        """生成宏观风险AI解读
        
        Args:
            macro_data: 宏观数据（5维度风险评分、警报、地缘事件等）
        
        Returns:
            AI生成的宏观风险解读（中文）
        """
        prompt = self._build_macro_analysis_prompt(macro_data)
        
        analysis = await self._call_gpt(prompt, max_tokens=500)
        
        if not analysis:
            # 回退到规则生成
            analysis = self._rule_based_macro_analysis(macro_data)
        
        return analysis
    
    async def _call_gpt(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7
    ) -> Optional[str]:
        """调用GPT API（带回退策略）
        
        Args:
            prompt: 提示词
            max_tokens: 最大token数
            temperature: 温度参数（0-1，越高越随机）
        
        Returns:
            GPT生成的文本，失败返回None
        """
        if not self.client:
            return None
        
        # 尝试不同的模型
        for model in self.models:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一位专业的投资分析师，擅长提供简洁、准确、实用的投资建议。请用中文回答。"
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                content = response.choices[0].message.content.strip()
                logger.info(f"GPT response generated using {model}")
                return content
                
            except Exception as e:
                logger.warning(f"Failed to call {model}: {str(e)}")
                continue
        
        logger.error("All GPT models failed, falling back to rule-based generation")
        return None
    
    def _build_technical_prompt(self, symbol: str, data: Dict[str, Any]) -> str:
        """构建技术分析提示词"""
        return f"""
请分析 {symbol} 的技术指标，给出简洁的投资建议（200字以内）：

趋势分析:
- SMA20: {data.get('trend', {}).get('sma_20')}
- SMA50: {data.get('trend', {}).get('sma_50')}
- 趋势强度: {data.get('trend', {}).get('trend_strength', 'N/A')}

动量指标:
- RSI: {data.get('momentum', {}).get('rsi')}
- MACD: {data.get('momentum', {}).get('macd')}
- 随机指标: {data.get('momentum', {}).get('stoch_k')}

波动率: {data.get('volatility', {})}

支撑/阻力: {data.get('support_resistance', {})}

请用一段话总结技术面状况，并给出明确的操作建议（持有/买入/减仓/观望）。
"""
    
    def _build_fundamental_prompt(self, symbol: str, data: Dict[str, Any]) -> str:
        """构建基本面分析提示词"""
        valuation = data.get('valuation', {})
        profitability = data.get('profitability', {})
        growth = data.get('growth', {})
        health = data.get('financial_health', {})
        
        return f"""
请分析 {symbol} 的基本面，给出简洁的投资价值评估（200字以内）：

估值指标:
- PE比率: {valuation.get('pe_ratio')}
- PB比率: {valuation.get('pb_ratio')}
- PEG比率: {valuation.get('peg_ratio')}
- 估值评分: {valuation.get('score', 'N/A')}/100

盈利能力:
- ROE: {profitability.get('roe')}
- ROA: {profitability.get('roa')}
- 利润率: {profitability.get('profit_margin')}
- 盈利评分: {profitability.get('score', 'N/A')}/100

成长性:
- 营收增长: {growth.get('revenue_growth')}
- EPS增长: {growth.get('eps_growth')}
- 成长评分: {growth.get('score', 'N/A')}/100

财务健康度:
- 速动比率: {health.get('quick_ratio')}
- 负债率: {health.get('debt_to_equity')}
- 健康评分: {health.get('score', 'N/A')}/100

请用一段话总结基本面状况，并评估是否值得长期投资。
"""
    
    def _build_position_advice_prompt(
        self,
        symbol: str,
        position_data: Dict[str, Any],
        technical_score: float,
        fundamental_score: float,
        overall_score: float
    ) -> str:
        """构建持仓建议提示词"""
        return f"""
请为 {symbol} 持仓提供综合建议（300字以内）：

综合评分: {overall_score:.1f}/100
- 技术面评分: {technical_score:.1f}/100
- 基本面评分: {fundamental_score:.1f}/100

持仓信息:
- 当前价格: {position_data.get('current_price', 'N/A')}
- 成本价: {position_data.get('avg_cost', 'N/A')}
- 收益率: {position_data.get('return_pct', 'N/A')}%
- 持仓数量: {position_data.get('quantity', 'N/A')}

请根据以上信息：
1. 评估当前持仓的风险收益比
2. 给出明确的操作建议（加仓/持有/减仓/清仓）
3. 提示需要关注的风险点
"""
    
    def _build_macro_analysis_prompt(self, data: Dict[str, Any]) -> str:
        """构建宏观分析提示词"""
        overall = data.get('overall_risk', {})
        breakdown = data.get('risk_breakdown', {})
        alerts = data.get('alerts', [])
        events = data.get('recent_events', [])
        
        return f"""
请解读当前宏观风险状况（300字以内）：

综合风险评分: {overall.get('overall_score', 'N/A')}/100
风险等级: {overall.get('risk_level', 'N/A')}

5维度风险分解:
- 货币政策风险: {breakdown.get('monetary_policy', {}).get('score', 'N/A')}/100
- 地缘政治风险: {breakdown.get('geopolitical', {}).get('score', 'N/A')}/100
- 板块泡沫风险: {breakdown.get('sector_bubble', {}).get('score', 'N/A')}/100
- 经济周期风险: {breakdown.get('economic_cycle', {}).get('score', 'N/A')}/100
- 市场情绪风险: {breakdown.get('market_sentiment', {}).get('score', 'N/A')}/100

风险警报: {len(alerts)}个
近期地缘事件: {len(events)}个

请：
1. 分析当前宏观环境的主要风险点
2. 评估对股市的整体影响（正面/中性/负面）
3. 给出应对建议（防御/均衡/进取）
"""
    
    def _rule_based_technical_summary(self, symbol: str, data: Dict[str, Any]) -> str:
        """规则生成技术分析摘要（回退方案）"""
        trend = data.get('trend', {})
        momentum = data.get('momentum', {})
        
        rsi = momentum.get('rsi')
        trend_strength = trend.get('trend_strength', '未知')
        
        if rsi:
            if rsi > 70:
                signal = "超买，建议观望或适当减仓"
            elif rsi < 30:
                signal = "超卖，可考虑逢低买入"
            else:
                signal = "震荡区间，建议持有观察"
        else:
            signal = "数据不足，建议谨慎操作"
        
        return f"{symbol} 技术面分析：趋势{trend_strength}，RSI指标显示{signal}。综合技术指标来看，当前{self._get_action_by_score(data.get('overall_score', 50))}。"
    
    def _rule_based_fundamental_summary(self, symbol: str, data: Dict[str, Any]) -> str:
        """规则生成基本面摘要（回退方案）"""
        valuation = data.get('valuation', {})
        profitability = data.get('profitability', {})
        
        val_score = valuation.get('score', 50)
        prof_score = profitability.get('score', 50)
        
        if val_score > 70 and prof_score > 70:
            assessment = "估值合理且盈利能力强，基本面优秀"
        elif val_score < 40 or prof_score < 40:
            assessment = "基本面存在明显风险，需谨慎对待"
        else:
            assessment = "基本面中等，建议持续关注"
        
        return f"{symbol} 基本面分析：{assessment}。整体来看，适合{self._get_investment_style_by_score((val_score + prof_score) / 2)}。"
    
    def _rule_based_position_advice(
        self,
        symbol: str,
        overall_score: float,
        technical_score: float,
        fundamental_score: float
    ) -> str:
        """规则生成持仓建议（回退方案）"""
        action = self._get_action_by_score(overall_score)
        
        score_diff = abs(technical_score - fundamental_score)
        if score_diff > 30:
            divergence = "但技术面与基本面出现较大分歧，需密切关注"
        else:
            divergence = "技术面与基本面相对一致"
        
        return f"{symbol} 综合评分{overall_score:.1f}分，建议{action}。{divergence}。风险提示：市场波动加剧时注意及时调整仓位。"
    
    def _rule_based_macro_analysis(self, data: Dict[str, Any]) -> str:
        """规则生成宏观分析（回退方案）"""
        overall = data.get('overall_risk', {})
        score = overall.get('overall_score', 50)
        level = overall.get('risk_level', 'MEDIUM')
        
        if score > 70:
            assessment = "宏观环境整体向好，市场风险可控"
            strategy = "可采取进取策略"
        elif score < 40:
            assessment = "宏观风险较高，需保持警惕"
            strategy = "建议采取防御策略"
        else:
            assessment = "宏观环境中性，存在不确定性"
            strategy = "建议均衡配置"
        
        return f"当前宏观风险等级：{level}。{assessment}，{strategy}。投资者应关注货币政策变化和地缘政治动态，及时调整投资组合。"
    
    def _get_action_by_score(self, score: float) -> str:
        """根据评分获取操作建议"""
        if score >= 75:
            return "持有或加仓"
        elif score >= 60:
            return "持有观望"
        elif score >= 40:
            return "谨慎持有，考虑减仓"
        else:
            return "建议减仓或清仓"
    
    def _get_investment_style_by_score(self, score: float) -> str:
        """根据评分获取投资风格"""
        if score >= 75:
            return "长期价值投资"
        elif score >= 60:
            return "中长期持有"
        elif score >= 40:
            return "短期波段操作"
        else:
            return "暂不建议投资"
