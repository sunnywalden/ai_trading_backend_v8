"""
AI分析服务 - 使用GPT生成持仓和宏观分析摘要

功能:
1. 技术分析AI摘要
2. 基本面分析AI摘要
3. 持仓综合评估AI建议
4. 宏观风险AI解读

回退策略: 配置模型 → 智能回退 → 规则生成
模型验证: 自动获取可用模型列表并验证配置
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import json
import time

from app.core.config import settings
from app.core.proxy import apply_proxy_env, ProxyConfig
from app.services.api_monitoring_service import api_monitor, APIProvider

logger = logging.getLogger(__name__)

# OpenAI 客户端（延迟初始化）
_openai_client = None
# 可用模型列表缓存（24小时）
_available_models_cache = None
_models_cache_time = None

# 模型熔断器：记录暂时不可用的模型及其恢复时间
# 当模型返回 429 (Rate Limit) 或 401 (Auth Error) 时，暂时熔断 5-10 分钟
_model_skip_list: Dict[str, float] = {}


def _get_openai_client():
    """获取OpenAI客户端（懒加载）"""
    global _openai_client
    
    if _openai_client is None:
        # 让代理配置在“脚本模式”下也生效（不依赖 FastAPI lifespan）
        apply_proxy_env(
            ProxyConfig(
                enabled=settings.PROXY_ENABLED,
                http_proxy=settings.HTTP_PROXY,
                https_proxy=settings.HTTPS_PROXY,
                no_proxy=settings.NO_PROXY,
            )
        )

        if not settings.OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not configured, AI analysis will use rule-based fallback")
            return None
        
        try:
            from openai import AsyncOpenAI
            # 代理：统一由应用启动时设置的 HTTP(S)_PROXY/NO_PROXY 环境变量接管（httpx 默认 trust_env=True）
            # Base URL：支持通过代理/镜像站点转发 OpenAI API
            if settings.OPENAI_API_BASE:
                _openai_client = AsyncOpenAI(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_API_BASE,
                )
            else:
                _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("OpenAI client initialized successfully")
        except ImportError:
            logger.error("openai package not installed, run: pip install openai")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            return None
    
    return _openai_client


async def _get_available_models() -> List[str]:
    """
    获取OpenAI可用模型列表（带24小时缓存）
    
    Returns:
        可用的聊天模型列表
    """
    global _available_models_cache, _models_cache_time
    
    # 检查缓存
    if _available_models_cache and _models_cache_time:
        if datetime.now() - _models_cache_time < timedelta(hours=24):
            return _available_models_cache
    
    client = _get_openai_client()
    if not client:
        # 客户端未初始化，返回默认模型列表（基于实际API返回）
        return ["gpt-5", "gpt-4-turbo", "gpt-4"]
    
    try:
        # 获取所有模型
        models_response = await client.models.list()
        
        # 过滤出聊天模型（gpt-5*, gpt-4*）
        # 注意：OpenAI 的模型列表里可能包含同前缀但不支持 chat.completions 的模型（例如部分 *-pro-*）。
        # 这里做一个保守过滤，避免把明显非 chat 模型加入候选。
        chat_models = []
        for model in models_response.data:
            model_id = model.id
            if (model_id.startswith("gpt-5") or model_id.startswith("gpt-4")):
                # 经验规则：跳过明显不是 chat 的“pro”变体，避免走 /v1/chat/completions 报错
                if "-pro-" in model_id:
                    continue
                chat_models.append(model_id)
        
        # 按优先级排序（gpt-5 > gpt-4-turbo > gpt-4）
        priority_order = []
        
        # 1. GPT-5系列（最新一代，最高优先级）
        gpt5 = [m for m in chat_models if m.startswith("gpt-5")]
        priority_order.extend(sorted(gpt5, reverse=True))
        
        # 2. GPT-4 Turbo系列
        gpt4_turbo = [m for m in chat_models if "gpt-4-turbo" in m or "gpt-4-1106" in m or "gpt-4-0125" in m]
        priority_order.extend(sorted(gpt4_turbo, reverse=True))
        
        # 3. GPT-4系列
        gpt4 = [m for m in chat_models if m.startswith("gpt-4") and m not in priority_order]
        priority_order.extend(sorted(gpt4, reverse=True))
        
        if priority_order:
            _available_models_cache = priority_order
            _models_cache_time = datetime.now()
            logger.info(f"Fetched {len(priority_order)} available chat models from OpenAI")
            return priority_order
        else:
            # 如果没有获取到模型，返回默认列表
            logger.warning("No chat models found, using default list")
            return ["gpt-5", "gpt-4-turbo", "gpt-4"]
            
    except Exception as e:
        logger.warning(f"Failed to fetch available models: {str(e)}, using default list")
        # 返回默认模型列表
        return ["gpt-5", "gpt-4-turbo", "gpt-4"]


def _select_best_models(configured_model: str, available_models: List[str]) -> List[str]:
    """
    选择最佳模型列表
    
    Args:
        configured_model: 配置的模型
        available_models: 可用模型列表
    
    Returns:
        按优先级排序的模型列表
    """
    selected_models = []
    
    # 1. 如果配置的模型可用，优先使用
    if configured_model in available_models:
        selected_models.append(configured_model)
        logger.info(f"Using configured model: {configured_model}")
    else:
        logger.warning(
            f"Configured model '{configured_model}' not available. "
            f"Available models: {', '.join(available_models[:3])}"
        )
    
    # 2. 添加智能回退模型（基于实际可用模型）
    fallback_preferences = [
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5",
        "gpt-4o",
        "gpt-4-turbo",
        "gpt-4-turbo-preview", 
        "gpt-4-0125-preview",
        "gpt-4-1106-preview",
        "gpt-4",
        "gpt-4o-mini",  # 低成本回退模型
        "gpt-3.5-turbo"
    ]
    
    for fallback in fallback_preferences:
        if fallback in available_models and fallback not in selected_models:
            selected_models.append(fallback)
            # 最多添加3个回退模型
            if len(selected_models) >= 3:
                break
    
    # 3. 如果还不够3个，从可用模型中补充
    for model in available_models:
        if model not in selected_models:
            selected_models.append(model)
            if len(selected_models) >= 3:
                break
    
    # 4. 确保至少有一个模型
    if not selected_models:
        selected_models = ["gpt-4"]
        logger.warning("No models selected, using default: gpt-4")
    
    logger.info(f"Selected models (fallback order): {' → '.join(selected_models)}")
    return selected_models


class AIAnalysisService:
    """AI分析服务 - 基于GPT生成智能摘要和建议"""
    
    def __init__(self):
        self.client = _get_openai_client()
        self.max_retries = 2
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.timeout = settings.OPENAI_TIMEOUT_SECONDS
        self._models = None  # 延迟初始化
    
    async def _get_models(self, prefer_cheap: bool = False) -> List[str]:
        """获取模型列表（延迟初始化）"""
        if self._models is None:
            available_models = await _get_available_models()
            configured_model = settings.OPENAI_MODEL
            self._models = _select_best_models(configured_model, available_models)
        
        # 如果优先使用廉价模型，将 gpt-4o-mini 等提到前面
        models = list(self._models)
        if prefer_cheap:
            cheap_keywords = ["mini", "3.5", "4o-mini"]
            cheap_models = [m for m in models if any(k in m for k in cheap_keywords)]
            # 把廉价模型放到列表最前面
            return cheap_models + [m for m in models if m not in cheap_models]
            
        return models
    
    @property
    async def models(self) -> List[str]:
        """模型列表属性"""
        return await self._get_models()
    
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
        # 默认使用最新模型
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
        # 默认使用最新模型
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
        
        # 默认使用最新模型
        advice = await self._call_gpt(prompt, max_tokens=400)
        
        if not advice:
            # 回退到规则生成
            advice = self._rule_based_position_advice(
                symbol, overall_score, technical_score, fundamental_score
            )
        
        return advice

    async def generate_portfolio_assessment(
        self,
        avg_score: float,
        total_beta: float,
        sector_distribution: Dict[str, float],
        position_count: int
    ) -> Dict[str, Any]:
        """生成组合层面的 AI 评估与建议"""
        prompt = f"""
        你是一位资深的投资组合经理。请分析以下个人持仓组合数据并给出专业建议：
        1. 组合加权评分: {avg_score:.2f} (满分100)
        2. 组合整体 Beta: {total_beta:.2f} (相对于 SPY)
        3. 持仓标的数量: {position_count}
        4. 行业分布 (Sector): {json.dumps(sector_distribution, ensure_ascii=False)}

        请提供：
        1. 组合现状总结 (200字以内)
        2. 具体优化建议 (3-4条)，包括：
           - 是否需要调仓（基于评分）
           - 是否需要增加防御（基于 Beta）
           - 行业集中度风险提示
        
        回复格式必须为 JSON:
        {{
          "summary": "...",
          "recommendations": [
            {{ "type": "REBALANCE/HEDGE/DIVERSIFY/RISK", "action": "...", "reason": "..." }}
          ]
        }}
        """
        
        # 默认使用最新模型
        response_text = await self._call_gpt(prompt, max_tokens=600)
        
        if response_text:
            try:
                # 尝试解析 JSON
                # 有时 GPT 会返回带 ```json 的格式，需要清理
                clean_text = response_text.strip()
                if clean_text.startswith("```json"):
                    clean_text = clean_text[7:-3].strip()
                elif clean_text.startswith("```"):
                    clean_text = clean_text[3:-3].strip()
                
                return json.loads(clean_text)
            except Exception as e:
                print(f"Failed to parse AI portfolio assessment JSON: {e}")
        
        # 规则回退
        return self._rule_based_portfolio_assessment(avg_score, total_beta, sector_distribution)

    def _rule_based_portfolio_assessment(self, avg_score, total_beta, sector_distribution) -> Dict[str, Any]:
        """规则导向的组合评估回退"""
        recommendations = []
        
        # 评分判断
        if avg_score < 60:
            summary = "当前组合整体评分较低，存在较多弱势头寸。"
            recommendations.append({
                "type": "REBALANCE",
                "action": "清理低评分头寸",
                "reason": "组合平均分低于及格线，说明持仓标的基本面或技术面显著走弱。"
            })
        else:
            summary = "组合整体质量良好，核心持仓表现稳健。"

        # Beta 判断
        if total_beta > 1.3:
            recommendations.append({
                "type": "HEDGE",
                "action": "考虑买入 SPY 保护性看跌期权",
                "reason": f"组合 Beta 达到 {total_beta:.2f}，对市场波动高度敏感，建议增加防御。"
            })
        elif total_beta < 0.7:
             recommendations.append({
                "type": "RISK",
                "action": "检查进攻性不足",
                "reason": f"组合 Beta 仅为 {total_beta:.2f}，表现可能大幅滞大盘，适宜在大盘走强时补仓高 Beta 龙头。"
            })

        # 集中度判断
        for sector, ratio in sector_distribution.items():
            if ratio > 0.4:
                recommendations.append({
                    "type": "DIVERSIFY",
                    "action": f"减持 {sector} 行业",
                    "reason": f"{sector} 占比达到 {ratio*100:.1f}%，行业集中度过高，易受单一板块风险冲击。"
                })

        return {
            "summary": summary,
            "recommendations": recommendations
        }
    
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
        
        # 默认使用最新模型
        analysis = await self._call_gpt(prompt, max_tokens=500)
        
        if not analysis:
            # 回退到规则生成
            analysis = self._rule_based_macro_analysis(macro_data)
        
        return analysis

    async def generate_daily_trend_conclusion(
        self,
        symbol: str,
        daily_payload: Dict[str, Any]
    ) -> str:
        """基于日线行情数据生成走势分析结论（华尔街交易员视角）

        约束：不输出任何“趋势信心/可信度”数值。
        """
        prompt = self._build_daily_trend_prompt(symbol, daily_payload)
        # GPT-5 系列在部分账号/路由下可能不支持自定义 temperature（仅支持默认值 1）。
        # 为了兼容性，这里不主动降低 temperature。
        text = await self._call_gpt(prompt, max_tokens=350, temperature=1.0)
        if text:
            return text

        # 回退：复用技术面规则摘要
        return self._rule_based_technical_summary(symbol, daily_payload)
    
    async def generate_signal_summary(self, signal_data: Dict[str, Any]) -> str:
        """为交易信号生成自然语言概要/依据（中文）"""
        prompt = self._build_signal_summary_prompt(signal_data)
        # 信号详情摘要使用高性能模型
        summary = await self._call_gpt(prompt, max_tokens=300)
        
        if not summary:
            # 回退到基础规则概要
            summary = self._rule_based_signal_summary(signal_data)
            
        return summary

    def _build_signal_summary_prompt(self, signal: Dict[str, Any]) -> str:
        symbol = signal.get('symbol', 'N/A')
        direction = "看多 (LONG)" if signal.get('direction') == 'LONG' else "看空 (SHORT)"
        signal_type = signal.get('signal_type', 'ENTRY')
        strength = signal.get('signal_strength', 0)
        confidence = signal.get('confidence', 0)
        factor_scores = signal.get('factor_scores', {})
        extra = signal.get('extra_metadata', {})
        
        return f"""
你是一位资深的华尔街交易员。请为以下交易信号生成一个简洁、专业的中文概要，说明触发该信号的主要依据和逻辑：

标的: {symbol}
信号类型: {signal_type} ({direction})
信号强度: {strength}/100
置信度: {confidence*100:.1f}%
策略来源: {extra.get('strategy_name', '未指定策略')}

因子得分详情:
- 技术面评分: {factor_scores.get('technical_score', 'N/A')}
- 基本面评分: {factor_scores.get('fundamental_score', 'N/A')}
- 动量评分: {factor_scores.get('momentum_score', 'N/A')}
- 情绪评分: {factor_scores.get('sentiment_score', 'N/A')}

请基于以上数据，用两三句话总结该信号的触发理由。格式要求：直接输出总结内容，不要带“信号概要：”等前缀。
"""

    def _rule_based_signal_summary(self, signal: Dict[str, Any]) -> str:
        symbol = signal.get('symbol', 'N/A')
        direction = "看多" if signal.get('direction') == 'LONG' else "看空"
        strength = signal.get('signal_strength', 0)
        strategy = signal.get('extra_metadata', {}).get('strategy_name', '量化策略')
        
        return f"信号基于 {strategy} 策略触发。当前对 {symbol}持{direction}观点，信号强度为 {strength:.1f}，综合技术面与动量指标评估后生成的自动化交易指令。"

    async def _call_gpt(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.5,
        prefer_cheap: bool = False
    ) -> Optional[str]:
        """调用GPT API（带回退策略与成本优化）
        
        Args:
            prompt: 提示词
            max_tokens: 最大token数
            temperature: 温度系数
            prefer_cheap: 是否优先使用低成本模型
        
        Returns:
            GPT生成的文本
        """
        if not self.client:
            return None

        gate = await api_monitor.can_call_provider(APIProvider.OPENAI)
        if not gate.get("can_call", True):
            logger.warning(f"OpenAI in cooldown/limit: {gate.get('reason')}")
            return None
        
        # 使用配置的max_tokens
        if max_tokens is None:
            max_tokens = self.max_tokens
        
        # 获取模型列表
        models = await self._get_models(prefer_cheap=prefer_cheap)
        now = time.time()
        
        # 尝试不同的模型
        for model in models:
            # 检查模型是否在熔断期
            if model in _model_skip_list:
                if now < _model_skip_list[model]:
                    logger.debug(f"Skipping model {model} (cooling down)")
                    continue
                else:
                    del _model_skip_list[model]

            start_time = time.time()
            success = False
            error_msg = None
            try:
                # GPT-5 系列在 chat.completions 上不支持 max_tokens，需要改用 max_completion_tokens。
                # 为了兼容 GPT-4 等老模型，这里按模型前缀做参数分流。
                request_kwargs = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一位专业的投资分析师，擅长提供简洁、准确、实用的投资建议。请用中文回答。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "timeout": self.timeout,
                }

                if model.startswith("gpt-5"):
                    request_kwargs["max_completion_tokens"] = max_tokens
                    # GPT-5：某些路由只支持默认 temperature=1；非 1 的值会直接 400。
                    # 为兼容性：temperature 不是 1 时不传该参数（让服务端使用默认值）。
                    if temperature in (None, 1, 1.0):
                        request_kwargs["temperature"] = 1
                else:
                    request_kwargs["max_tokens"] = max_tokens
                    request_kwargs["temperature"] = temperature

                response = await self.client.chat.completions.create(**request_kwargs)
                
                content = response.choices[0].message.content.strip()
                logger.info(f"GPT response generated using {model} (max_tokens={max_tokens}, timeout={self.timeout}s)")
                success = True
                return content
                
            except Exception as e:
                error_msg = str(e)
                # 区分连接错误和API错误
                if "429" in error_msg or "insufficient_quota" in error_msg.lower() or "rate_limit" in error_msg.lower():
                    logger.warning(f"Model {model} hit rate limit/quota. Cooling down for 10 min.")
                    _model_skip_list[model] = now + 600 # 冷却10分钟
                elif "Connection" in error_msg or "timeout" in error_msg.lower():
                    logger.warning(f"Failed to call {model}: Connection error. Check network or API endpoint.")
                elif "API key" in error_msg or "authentication" in error_msg.lower():
                    logger.warning(f"Failed to call {model}: Authentication error. Check OPENAI_API_KEY.")
                else:
                    logger.warning(f"Failed to call {model}: {error_msg}")
                continue
            finally:
                response_time = (time.time() - start_time) * 1000
                await api_monitor.record_api_call(
                    provider=APIProvider.OPENAI,
                    endpoint=f"chat.completions:{model}",
                    success=success,
                    response_time_ms=response_time,
                    error_message=error_msg,
                )
        
        logger.info("All GPT models unavailable, using rule-based generation as fallback")
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

    def _build_daily_trend_prompt(self, symbol: str, data: Dict[str, Any]) -> str:
        """构建日线走势分析提示词（强调交易员视角与可执行结论）"""
        trend = data.get("trend", {})
        mom = data.get("momentum", {})
        levels = data.get("levels", {})
        stats = data.get("stats", {})
        recent = data.get("recent_ohlcv", [])

        # 只取最近10根用于展示，减少token
        recent_tail = recent[-10:] if isinstance(recent, list) else []

        return f"""
你是顶级华尔街交易员（偏实战、控风险、讲条件触发），请基于【日线】数据给出 {symbol} 的短/中期走势结论。

严格约束：
1) 不要输出任何“趋势信心/可信度”数值或百分比。
2) 用中文输出，尽量短句，像交易台晨会。

输入（摘要）：
- 时间框架: {data.get('timeframe')}
- 趋势: direction={trend.get('trend_direction')} strength={trend.get('trend_strength')} bollinger={trend.get('bollinger_position')} volume_ratio={trend.get('volume_ratio')}
- 动量: RSI={mom.get('rsi_value')}({mom.get('rsi_status')}) MACD_status={mom.get('macd_status')}
- 关键位: support={levels.get('support')} resistance={levels.get('resistance')}
- 统计: 5D回报={stats.get('return_5d')} 20D回报={stats.get('return_20d')} 20D波动={stats.get('vol_20d')}
- 最近10根日线OHLCV(从旧到新): {json.dumps(recent_tail, ensure_ascii=False)}

请输出固定结构：
【一句话结论】
【短期(1-2周)】方向/节奏/触发条件
【中期(1-3个月)】核心路径与关键破位/站稳条件
【关键价位】上方/下方最重要的2-3个价位（来自支撑阻力）
【交易计划】如果做多/做空分别怎么做（入场条件、止损逻辑、加减仓规则）
【风险点】2-3条（例如波动扩张、假突破、量能背离）
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
