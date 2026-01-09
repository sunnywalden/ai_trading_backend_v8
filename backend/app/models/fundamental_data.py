"""基本面数据模型"""
from sqlalchemy import Column, Integer, String, Float, Date, BigInteger
from app.models.db import Base


class FundamentalData(Base):
    __tablename__ = "fundamental_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), nullable=False, index=True)
    fiscal_date = Column(Date, nullable=False)
    data_type = Column(String(16), default='QUARTERLY')

    # 估值
    market_cap = Column(BigInteger)
    pe_ratio = Column(Float)
    pb_ratio = Column(Float)
    ps_ratio = Column(Float)
    peg_ratio = Column(Float)

    # 盈利能力
    revenue = Column(BigInteger)
    net_income = Column(BigInteger)
    eps = Column(Float)
    roe = Column(Float)
    roa = Column(Float)
    gross_margin = Column(Float)
    operating_margin = Column(Float)
    net_margin = Column(Float)

    # 增长
    revenue_growth_yoy = Column(Float)
    eps_growth_yoy = Column(Float)

    # 财务健康
    total_assets = Column(BigInteger)
    total_debt = Column(BigInteger)
    cash_and_equivalents = Column(BigInteger)
    free_cash_flow = Column(BigInteger)
    debt_to_equity = Column(Float)
    current_ratio = Column(Float)
