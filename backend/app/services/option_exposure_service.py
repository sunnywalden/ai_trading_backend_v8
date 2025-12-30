from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

from app.broker.option_client_base import OptionBrokerClient
from app.broker.models import OptionPosition, UnderlyingPosition
from app.services.account_service import AccountService


@dataclass
class SymbolOptionExposure:
    symbol: str
    net_delta_shares: float = 0.0
    delta_notional_usd: float = 0.0
    gamma_usd: float = 0.0
    vega_usd: float = 0.0
    theta_usd: float = 0.0
    short_dte_gamma_usd: float = 0.0
    short_dte_vega_usd: float = 0.0
    short_dte_theta_usd: float = 0.0


@dataclass
class AccountOptionExposure:
    equity_usd: float = 0.0

    total_delta_notional_usd: float = 0.0
    total_gamma_usd: float = 0.0
    total_vega_usd: float = 0.0
    total_theta_usd: float = 0.0

    earnings_gamma_usd: float = 0.0
    earnings_vega_usd: float = 0.0
    earnings_theta_usd: float = 0.0

    short_dte_gamma_usd: float = 0.0
    short_dte_vega_usd: float = 0.0
    short_dte_theta_usd: float = 0.0

    per_symbol: Dict[str, SymbolOptionExposure] = field(default_factory=dict)


class OptionExposureService:
    """从券商接口获取真实仓位和 Greeks，并聚合为账户期权敞口。

    - 依赖 OptionBrokerClient（可为 Tiger 或 Dummy）
    - 汇总现货 Delta + 期权 Delta/Gamma/Vega/Theta
    - 将短到期期权（short DTE）额外暴露单独统计，供风控参考
    """

    def __init__(self, session, broker_client: OptionBrokerClient):
        self.session = session
        self.broker = broker_client
        self.account_svc = AccountService(session, broker_client)

    # -------- 对外主接口 --------

    async def get_account_exposure(self, account_id: str) -> AccountOptionExposure:
        equity_usd = await self.account_svc.get_equity_usd(account_id)
        underlyings = await self.broker.list_underlying_positions(account_id)
        options = await self.broker.list_option_positions(account_id)
        return self._aggregate_exposure(equity_usd, underlyings, options)

    async def simulate_apply_actions(
        self, base_exp: AccountOptionExposure, actions: List[Dict]
    ) -> AccountOptionExposure:
        """对冲成本模型使用的“模拟执行后敞口”。

        简化版实现思路：
        - 只修改 Delta 敞口（其他 Greeks 后续可扩展）
        - STOCK：根据 price * qty 估算 Delta notional 变动
        - OPTION：允许外部通过 actions 携带 delta/underlying_price/multiplier 估值
        """
        exp = AccountOptionExposure(
            equity_usd=base_exp.equity_usd,
            total_delta_notional_usd=base_exp.total_delta_notional_usd,
            total_gamma_usd=base_exp.total_gamma_usd,
            total_vega_usd=base_exp.total_vega_usd,
            total_theta_usd=base_exp.total_theta_usd,
            earnings_gamma_usd=base_exp.earnings_gamma_usd,
            earnings_vega_usd=base_exp.earnings_vega_usd,
            earnings_theta_usd=base_exp.earnings_theta_usd,
            short_dte_gamma_usd=base_exp.short_dte_gamma_usd,
            short_dte_vega_usd=base_exp.short_dte_vega_usd,
            short_dte_theta_usd=base_exp.short_dte_theta_usd,
            per_symbol={k: v for k, v in base_exp.per_symbol.items()},
        )

        for act in actions:
            instr = act.get("instrument")
            symbol = act.get("symbol")
            side = act.get("side")
            qty = float(act.get("quantity", 0))
            if qty <= 0 or not symbol:
                continue

            sym_exp = exp.per_symbol.get(symbol)
            if not sym_exp:
                sym_exp = SymbolOptionExposure(symbol=symbol)
                exp.per_symbol[symbol] = sym_exp

            if instr == "STOCK":
                direction = 1.0 if side == "BUY" else -1.0
                price = float(act.get("price", 0.0) or 0.0)
                delta_shares = direction * qty
                delta_notional = delta_shares * price
                sym_exp.net_delta_shares += delta_shares
                sym_exp.delta_notional_usd += delta_notional
                exp.total_delta_notional_usd += delta_notional

            elif instr == "OPTION":
                direction = 1.0 if side == "BUY" else -1.0
                underlying_price = float(act.get("underlying_price", 0.0) or act.get("price", 0.0) or 0.0)
                multiplier = int(act.get("multiplier", 100))
                est_delta = float(act.get("delta", 0.5))  # 若外部未提供，默认按 0.5 估计
                delta_shares = direction * est_delta * qty * multiplier
                delta_notional = delta_shares * underlying_price
                sym_exp.net_delta_shares += delta_shares
                sym_exp.delta_notional_usd += delta_notional
                exp.total_delta_notional_usd += delta_notional

                # TODO: 如有需要，可添加对 gamma/vega/theta 的估算（从 act 中携带参数）

        return exp

    # -------- 内部：聚合逻辑 --------

    def _aggregate_exposure(
        self,
        equity_usd: float,
        underlyings: List[UnderlyingPosition],
        options: List[OptionPosition],
    ) -> AccountOptionExposure:
        exp = AccountOptionExposure(equity_usd=equity_usd)
        now = datetime.now(timezone.utc).date()

        per_symbol: Dict[str, SymbolOptionExposure] = {}

        def get_sym(symbol: str) -> SymbolOptionExposure:
            if symbol not in per_symbol:
                per_symbol[symbol] = SymbolOptionExposure(symbol=symbol)
            return per_symbol[symbol]

        # 1. 现货 Delta
        for p in underlyings:
            sym = get_sym(p.symbol)
            delta_shares = float(p.quantity)
            delta_notional = delta_shares * float(p.last_price)
            sym.net_delta_shares += delta_shares
            sym.delta_notional_usd += delta_notional
            exp.total_delta_notional_usd += delta_notional

        # 2. 期权 Greeks（按标的聚合）
        for pos in options:
            c = pos.contract
            g = pos.greeks
            sym = get_sym(c.underlying)

            direction = 1.0 if pos.quantity > 0 else -1.0  # 多头正，空头负
            abs_contracts = abs(pos.quantity)
            mult = c.multiplier
            S = pos.underlying_price

            # Delta
            delta_shares = g.delta * abs_contracts * mult * direction
            delta_notional = delta_shares * S

            # Gamma/Vega/Theta
            gamma_usd = g.gamma * abs_contracts * mult * S * S  # 常见近似：Gamma * S^2 * 合约数
            vega_usd = g.vega * abs_contracts * mult
            theta_usd = g.theta * abs_contracts * mult

            sym.net_delta_shares += delta_shares
            sym.delta_notional_usd += delta_notional
            sym.gamma_usd += gamma_usd
            sym.vega_usd += vega_usd
            sym.theta_usd += theta_usd

            exp.total_delta_notional_usd += delta_notional
            exp.total_gamma_usd += gamma_usd
            exp.total_vega_usd += vega_usd
            exp.total_theta_usd += theta_usd

            # 短 DTE 暴露
            dte = (c.expiry - now).days
            if dte <= 7:
                sym.short_dte_gamma_usd += gamma_usd
                sym.short_dte_theta_usd += theta_usd
                exp.short_dte_gamma_usd += gamma_usd
                exp.short_dte_theta_usd += theta_usd

        exp.per_symbol = per_symbol
        return exp
