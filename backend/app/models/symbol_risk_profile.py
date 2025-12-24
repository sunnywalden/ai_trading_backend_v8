from sqlalchemy import Column, BigInteger, String, Boolean, JSON, DateTime, text
from .db import Base


class SymbolRiskProfile(Base):
    __tablename__ = "symbol_risk_profile"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    market = Column(String(16), nullable=False)
    vol_level = Column(String(16), nullable=False, default="MEDIUM")
    liquidity_level = Column(String(16), nullable=False, default="HIGH")

    use_custom_shock = Column(Boolean, nullable=False, default=False)
    use_custom_earnings = Column(Boolean, nullable=False, default=False)

    shock_policy_json = Column(JSON, nullable=True)
    earnings_policy_json = Column(JSON, nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
