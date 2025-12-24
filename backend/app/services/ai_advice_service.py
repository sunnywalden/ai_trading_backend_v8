from typing import List
import json

from app.core.config import settings
from app.schemas.ai_advice import (
    AiAdviceRequest,
    AiAdviceResponse,
    AdviceOrderSuggestion,
)
from app.schemas.ai_state import AiStateView
from app.services.option_exposure_service import OptionExposureService
from app.services.risk_config_service import RiskConfigService
from app.services.symbol_risk_profile_service import SymbolRiskProfileService
from app.broker.factory import make_option_broker_client


class AiAdviceService:
    """AI 决策助手服务。

    职责：
    - 聚合当前账户状态（RiskState + Exposure + 行为画像）
    - 构建一个结构化的 prompt，交给 GPT-5.1
    - 将模型返回的 JSON 解析为 AiAdviceResponse
    """

    def __init__(self, session):
        self.session = session

    async def build_state_snapshot(self, account_id: str) -> AiStateView:
        """复用 /ai/state 的逻辑，内部构建出 AiStateView。"""
        from app.schemas.ai_state import AiStateView, LimitsView, SymbolBehaviorView, ExposureView

        risk = RiskConfigService(self.session)
        eff = await risk.get_effective_state(account_id)

        broker_client = make_option_broker_client()
        expo_svc = OptionExposureService(self.session, broker_client)
        expo = await expo_svc.get_account_exposure(account_id)
        eq = expo.equity_usd or 1.0
        delta_pct = expo.total_delta_notional_usd / eq
        gamma_pct = expo.total_gamma_usd / eq
        vega_pct = expo.total_vega_usd / eq
        theta_pct = expo.total_theta_usd / eq
        short_gamma_pct = expo.short_dte_gamma_usd / eq
        short_theta_pct = expo.short_dte_theta_usd / eq

        exposure_view = ExposureView(
            equity_usd=expo.equity_usd,
            total_delta_notional_usd=expo.total_delta_notional_usd,
            total_gamma_usd=expo.total_gamma_usd,
            total_vega_usd=expo.total_vega_usd,
            total_theta_usd=expo.total_theta_usd,
            short_dte_gamma_usd=expo.short_dte_gamma_usd,
            short_dte_vega_usd=expo.short_dte_vega_usd,
            short_dte_theta_usd=expo.short_dte_theta_usd,
            delta_pct=delta_pct,
            gamma_pct=gamma_pct,
            vega_pct=vega_pct,
            theta_pct=theta_pct,
            short_dte_gamma_pct=short_gamma_pct,
            short_dte_theta_pct=short_theta_pct,
        )

        symbols = list(eff.symbol_behavior_tiers.keys())
        prof_svc = SymbolRiskProfileService(self.session)
        behavior_stats = await prof_svc.get_behavior_stats(account_id, symbols)

        limits_view = LimitsView(
            max_order_notional_usd=eff.limits.max_order_notional_usd,
            max_total_gamma_pct=eff.limits.max_total_gamma_pct,
            max_total_vega_pct=eff.limits.max_total_vega_pct,
            max_total_theta_pct=eff.limits.max_total_theta_pct,
        )

        symbol_views = {}
        for sym in symbols:
            stats = behavior_stats.get(sym)
            if stats is None:
                bv = SymbolBehaviorView(
                    symbol=sym,
                    tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                    behavior_score=60,
                    sell_fly_score=50,
                    overtrade_score=50,
                    revenge_score=40,
                )
            else:
                bv = SymbolBehaviorView(
                    symbol=sym,
                    tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                    behavior_score=stats.behavior_score,
                    sell_fly_score=stats.sell_fly_score,
                    overtrade_score=stats.overtrade_score,
                    revenge_score=stats.revenge_trade_score,
                )
            symbol_views[sym] = bv

        return AiStateView(
            trade_mode=eff.effective_trade_mode.value,
            limits=limits_view,
            exposure=exposure_view,
            symbols=symbol_views,
        )

    async def get_advice(self, req: AiAdviceRequest) -> AiAdviceResponse:
        account_id = req.account_id or settings.TIGER_ACCOUNT

        # 1. 汇总当前状态快照
        snapshot = await self.build_state_snapshot(account_id)

        # 2. 构建结构化 prompt
        system_prompt = (
            "你是一名严谨的量化交易与风险管理助手，"
            "需要在既有风险限额和行为约束下，给出稳健的美股/港股交易建议。"
        )

        state_block = {
            "trade_mode": snapshot.trade_mode,
            "limits": snapshot.limits.dict(),
            "exposure": snapshot.exposure.dict(),
            "behavior": {k: v.dict() for k, v in snapshot.symbols.items()},
        }

        user_block = {
            "goal": req.goal,
            "time_horizon": req.time_horizon,
            "risk_preference": req.risk_preference.dict(),
            "notes": req.notes or "",
        }

        llm_input = {
            "system": system_prompt,
            "state": state_block,
            "user": user_block,
            "output_format": {
                "summary": "string",
                "reasoning": "string",
                "suggested_orders": [
                    {
                        "symbol": "string",
                        "instrument": "STOCK|OPTION",
                        "side": "BUY|SELL",
                        "quantity": "number",
                        "note": "string",
                        "intent": "ENTRY|TAKE_PROFIT|STOP_LOSS|HEDGE|REBALANCE",
                    }
                ],
            },
        }

        # 3. 调用 LLM（若未配置 OPENAI_API_KEY，则返回占位建议）
        if not settings.OPENAI_API_KEY:
            # 占位逻辑：根据当前 exposure 简单生成一条“示范建议”
            summary = "占位建议：当前为 DRY_RUN 模式，未配置 OPENAI_API_KEY，仅返回示例。"
            reasoning = (
                "真实环境下，这里会调用 GPT-5.1 模型，"
                "综合风险限额、Greeks 暴露和行为评分，生成结构化的交易建议。"
            )
            demo_order = AdviceOrderSuggestion(
                symbol="META",
                instrument="STOCK",
                side="BUY",
                quantity=0,
                note="示例：请在配置 OPENAI_API_KEY 之后获取真实建议。",
                intent="HEDGE",
            )
            return AiAdviceResponse(
                summary=summary,
                reasoning=reasoning,
                suggested_orders=[demo_order],
            )

        # 真实项目中，你可以使用 openai 官方 SDK：
        #
        #   from openai import OpenAI
        #   client = OpenAI(api_key=settings.OPENAI_API_KEY)
        #   completion = client.responses.create(
        #       model=settings.OPENAI_MODEL,
        #       input=[
        #           {"role": "system", "content": system_prompt},
        #           {"role": "user", "content": json.dumps(llm_input, ensure_ascii=False)},
        #       ],
        #       ...
        #   )
        #   content = completion.output[0].content[0].text
        #   raw = json.loads(content)
        #
        # 这里为了可运行，我们仍然返回占位数据。

        summary = "占位：已检测到 OPENAI_API_KEY 配置，但示例代码未真正调用外部 API。"
        reasoning = "你可以在 AiAdviceService.get_advice 中补充 openai 调用逻辑并解析 JSON。"
        return AiAdviceResponse(summary=summary, reasoning=reasoning, suggested_orders=[])
