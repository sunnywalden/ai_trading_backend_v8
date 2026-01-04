"""
持仓评估和宏观风险分析模块的数据库表结构

运行方式:
cd backend
python create_position_macro_tables.py
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = "sqlite+aiosqlite:///./demo.db"


async def create_tables():
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        # 1. 持仓评分表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS position_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                -- 综合评分
                overall_score INTEGER,
                technical_score INTEGER,
                fundamental_score INTEGER,
                sentiment_score INTEGER,
                
                -- 技术面详情
                trend_direction TEXT,
                trend_strength INTEGER,
                rsi_value REAL,
                rsi_status TEXT,
                macd_signal TEXT,
                
                -- 基本面详情
                pe_ratio REAL,
                peg_ratio REAL,
                roe REAL,
                revenue_growth_yoy REAL,
                valuation_grade TEXT,
                profitability_grade TEXT,
                
                -- AI总结
                technical_summary TEXT,
                fundamental_summary TEXT,
                recommendation TEXT
            )
        """))
        
        # 创建唯一索引（每天每个账户每个标的只保留一条记录）
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_position_scores_daily 
            ON position_scores(account_id, symbol, date(timestamp))
        """))
        
        # 2. 技术分析缓存表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS technical_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                timeframe TEXT DEFAULT '1D',
                
                -- 价格数据
                close_price REAL,
                volume BIGINT,
                
                -- 移动平均线
                ma_5 REAL,
                ma_10 REAL,
                ma_20 REAL,
                ma_50 REAL,
                ma_200 REAL,
                
                -- 动量指标
                rsi_14 REAL,
                macd REAL,
                macd_signal REAL,
                macd_histogram REAL,
                
                -- 波动率
                atr_14 REAL,
                bb_upper REAL,
                bb_middle REAL,
                bb_lower REAL,
                
                -- 成交量
                volume_sma_20 BIGINT,
                obv BIGINT
            )
        """))
        
        # 创建唯一索引（每天每个标的每个时间框架只保留一条记录）
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_technical_indicators_daily 
            ON technical_indicators(symbol, date(timestamp), timeframe)
        """))
        
        # 3. 基本面数据表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fundamental_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                fiscal_date DATE NOT NULL,
                data_type TEXT DEFAULT 'QUARTERLY',
                
                -- 估值
                market_cap BIGINT,
                pe_ratio REAL,
                pb_ratio REAL,
                ps_ratio REAL,
                peg_ratio REAL,
                
                -- 盈利能力
                revenue BIGINT,
                net_income BIGINT,
                eps REAL,
                roe REAL,
                roa REAL,
                gross_margin REAL,
                operating_margin REAL,
                net_margin REAL,
                
                -- 增长
                revenue_growth_yoy REAL,
                eps_growth_yoy REAL,
                
                -- 财务健康
                total_assets BIGINT,
                total_debt BIGINT,
                cash_and_equivalents BIGINT,
                free_cash_flow BIGINT,
                debt_to_equity REAL,
                current_ratio REAL,
                
                UNIQUE(symbol, fiscal_date, data_type)
            )
        """))
        
        # 4. 宏观指标表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS macro_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                indicator_type TEXT NOT NULL,
                
                -- 货币政策
                fed_rate REAL,
                m2_growth_rate REAL,
                fed_balance_sheet BIGINT,
                inflation_rate REAL,
                dxy_index REAL,
                
                -- 经济周期
                gdp_growth REAL,
                unemployment_rate REAL,
                pmi_index REAL,
                yield_curve_2y10y REAL,
                recession_probability REAL,
                
                -- 市场情绪
                vix_index REAL,
                put_call_ratio REAL,
                fear_greed_index INTEGER
            )
        """))
        
        # 创建唯一索引（每天每种指标类型只保留一条记录）
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_macro_indicators_daily 
            ON macro_indicators(date(timestamp), indicator_type)
        """))
        
        # 5. 宏观风险评分表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS macro_risk_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                -- 分项评分 (0-100)
                monetary_policy_score INTEGER,
                geopolitical_score INTEGER,
                sector_bubble_score INTEGER,
                economic_cycle_score INTEGER,
                sentiment_score INTEGER,
                
                -- 综合评分
                overall_score INTEGER,
                risk_level TEXT,
                
                -- AI分析
                risk_summary TEXT,
                key_concerns TEXT,
                recommendations TEXT,
                
                -- 元数据
                data_sources TEXT,
                confidence REAL
            )
        """))
        
        # 创建唯一索引（每天只保留一条综合评分记录）
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_macro_risk_scores_daily 
            ON macro_risk_scores(date(timestamp))
        """))
        
        # 6. 地缘政治事件表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS geopolitical_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date DATETIME NOT NULL,
                event_type TEXT,
                region TEXT,
                title TEXT,
                description TEXT,
                
                -- 影响评估
                severity TEXT,
                affected_sectors TEXT,
                market_impact_score INTEGER,
                
                -- 来源
                news_source TEXT,
                news_url TEXT,
                
                UNIQUE(event_date, title)
            )
        """))
        
        print("✅ All tables created successfully!")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_tables())
