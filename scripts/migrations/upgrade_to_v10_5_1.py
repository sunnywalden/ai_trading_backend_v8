#!/usr/bin/env python3
"""upgrade_to_v10_5_1.py — V10.5.1 数据库迁移脚本

差异对比（v10.4.4 → v10.5.1）：

  V10.5.1（本脚本）—— 机构级研究与交易纪律
  ─────────────────────────────────────────────────────
  新增表（Epic C1）：
  1.  strategy_scorecard_snapshots  策略评分卡定期快照（M1-Alpha Truth Stack）
  2.  factor_registry               因子注册表（M1-Factor Registry）
  3.  shadow_portfolio_entries      影子账本条目（M1-Shadow Portfolio）
  4.  risk_budget_snapshots         组合风险预算快照（M2-Portfolio Construction 2.0）
  5.  execution_policy_snapshots    执行策略快照（M3-Execution Policy Engine）
  6.  pretrade_cost_estimates       预交易成本估算（M3-Pre-Trade Cost Model）
  7.  execution_replay_logs         子订单回放日志（M3-Post-Trade Replay）
  8.  model_degradation_snapshots   模型退化快照（M4-Live Safety Guard）
  9.  promotion_pipeline_runs       策略晋级流水（M5-Research-to-Live Governance）
  10. experiment_ledger_entries     实验总账条目（M5-Experiment Ledger）

用法：
  cd /path/to/ai_trading_backend_v8
  python scripts/migrations/upgrade_to_v10_5_1.py           # 执行迁移
  python scripts/migrations/upgrade_to_v10_5_1.py --check   # 检查现状
  python scripts/migrations/upgrade_to_v10_5_1.py --rollback # 回滚（危险！）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL — M1 Alpha Truth Stack
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP_STRATEGY_SCORECARD_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS strategy_scorecard_snapshots (
    id                              BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    account_id                      VARCHAR(64)     NOT NULL                         COMMENT '账户ID',
    strategy_id                     VARCHAR(64)     NOT NULL                         COMMENT '策略ID',
    strategy_name                   VARCHAR(128)    NULL                             COMMENT '策略显示名称',
    lookback_days                   INT             NOT NULL DEFAULT 90              COMMENT '统计回看窗口（天）',
    sample_size                     INT             NOT NULL DEFAULT 0               COMMENT '信号样本数',
    evaluated_size                  INT             NOT NULL DEFAULT 0               COMMENT '已评估样本数',
    gross_alpha                     FLOAT           NULL                             COMMENT '毛值 Alpha（均值实际收益）',
    net_alpha                       FLOAT           NULL                             COMMENT '净 Alpha（扣除执行成本后）',
    hit_rate                        FLOAT           NULL                             COMMENT '命中率',
    payoff_ratio                    FLOAT           NULL                             COMMENT '盈亏比（平均盈利/平均亏损）',
    turnover                        FLOAT           NULL                             COMMENT '换手率代理（已执行信号比例）',
    avg_holding_period_days         FLOAT           NULL                             COMMENT '平均持仓期（天）',
    implementation_shortfall_drag   FLOAT           NULL                             COMMENT '执行成本拖拽（bps）',
    regime_label                    VARCHAR(32)     NULL                             COMMENT '统计期主要市场体制标签',
    as_of                           DATETIME        NOT NULL                         COMMENT '快照基准时间',
    data_quality                    VARCHAR(16)     NOT NULL DEFAULT 'GOOD'          COMMENT 'GOOD/STALE/PARTIAL',
    calculation_version             VARCHAR(16)     NOT NULL DEFAULT '1.0'           COMMENT '计算逻辑版本号',
    created_at                      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录写入时间',
    PRIMARY KEY (id),
    INDEX idx_scs_account_strategy  (account_id, strategy_id),
    INDEX idx_scs_as_of             (as_of),
    INDEX idx_scs_strategy_as_of    (strategy_id, as_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M1: 策略评分卡定期快照';
"""

MYSQL_UP_FACTOR_REGISTRY = """
CREATE TABLE IF NOT EXISTS factor_registry (
    id                          BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    factor_id                   VARCHAR(64)     NOT NULL                         COMMENT '因子唯一标识（snake_case）',
    name                        VARCHAR(128)    NOT NULL                         COMMENT '因子中文名称',
    category                    VARCHAR(32)     NOT NULL DEFAULT 'UNKNOWN'       COMMENT 'MOMENTUM/QUALITY/VALUE/VOLATILITY/MACRO/EVENT/CUSTOM',
    description                 TEXT            NULL                             COMMENT '因子定义描述',
    version                     VARCHAR(16)     NOT NULL DEFAULT '1.0'           COMMENT '因子版本号',
    definition_json             JSON            NULL                             COMMENT '因子计算规则JSON（公式/参数/依赖）',
    feature_generation_window   VARCHAR(32)     NULL                             COMMENT '特征生成时间窗口（如 D-1/W-1/M-1）',
    label_rule_hash             VARCHAR(64)     NULL                             COMMENT '标签生成规则哈希（防止 leakage 追溯）',
    leakage_guard_status        VARCHAR(16)     NOT NULL DEFAULT 'CLEAN'         COMMENT 'CLEAN/WARNING/FAILED',
    is_active                   TINYINT(1)      NOT NULL DEFAULT 1               COMMENT '是否启用',
    created_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    updated_at                  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uq_factor_id_version (factor_id, version),
    INDEX idx_fr_category          (category),
    INDEX idx_fr_is_active         (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M1: 因子注册表（版本化、防泄漏标记）';
"""

MYSQL_UP_SHADOW_PORTFOLIO_ENTRIES = """
CREATE TABLE IF NOT EXISTS shadow_portfolio_entries (
    id                  BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    symbol              VARCHAR(32)     NOT NULL                         COMMENT '标的代码',
    action              VARCHAR(8)      NOT NULL                         COMMENT 'BUY/SELL',
    rejection_source    VARCHAR(16)     NOT NULL                         COMMENT 'FUNNEL/RISK/EXECUTION/GOVERNANCE',
    rejection_reason    VARCHAR(128)    NULL                             COMMENT '具体拒绝原因标签',
    signal_id           VARCHAR(64)     NULL                             COMMENT '关联信号ID',
    strategy_id         VARCHAR(64)     NULL                             COMMENT '关联策略ID',
    expected_return     FLOAT           NULL                             COMMENT '信号预期收益',
    ghost_pnl_pct       FLOAT           NULL                             COMMENT '影子持仓盈亏百分比（事后追踪）',
    hypothetical_executed TINYINT(1)    NOT NULL DEFAULT 0               COMMENT '假设执行标记（用于错杀测试）',
    regime_label        VARCHAR(32)     NULL                             COMMENT '拒绝时市场体制标签',
    resolved_at         DATETIME        NULL                             COMMENT '影子仓位关闭/结算时间',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录时间',
    PRIMARY KEY (id),
    INDEX idx_spe_symbol            (symbol),
    INDEX idx_spe_rejection_source  (rejection_source),
    INDEX idx_spe_strategy_id       (strategy_id),
    INDEX idx_spe_created_at        (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M1: 影子账本条目（三类拒绝源）';
"""

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL — M2 Portfolio Construction 2.0
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP_RISK_BUDGET_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS risk_budget_snapshots (
    id              BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    account_id      VARCHAR(64)     NOT NULL                         COMMENT '账户ID',
    budget_type     VARCHAR(16)     NOT NULL                         COMMENT 'PORTFOLIO/SECTOR/FACTOR/REGIME/LIQUIDITY',
    budget_key      VARCHAR(64)     NOT NULL                         COMMENT '预算对象键（如 sector=Technology，factor=momentum）',
    allocated_pct   FLOAT           NOT NULL DEFAULT 0.0             COMMENT '已分配预算占比（占总预算）',
    used_pct        FLOAT           NOT NULL DEFAULT 0.0             COMMENT '已使用预算占比',
    remaining_pct   FLOAT           NOT NULL DEFAULT 0.0             COMMENT '剩余预算占比',
    breach_flag     TINYINT(1)      NOT NULL DEFAULT 0               COMMENT '是否超限',
    as_of           DATETIME        NOT NULL                         COMMENT '快照基准时间',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录写入时间',
    PRIMARY KEY (id),
    INDEX idx_rbs_account_type      (account_id, budget_type),
    INDEX idx_rbs_as_of             (as_of),
    INDEX idx_rbs_breach            (breach_flag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M2: 分层风险预算快照';
"""

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL — M3 Execution Policy Engine
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP_EXECUTION_POLICY_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS execution_policy_snapshots (
    id                      BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    intent_id               VARCHAR(64)     NOT NULL                         COMMENT '关联执行意图ID',
    account_id              VARCHAR(64)     NOT NULL                         COMMENT '账户ID',
    symbol                  VARCHAR(32)     NOT NULL                         COMMENT '标的代码',
    action                  VARCHAR(8)      NOT NULL                         COMMENT 'BUY/SELL',
    urgency                 VARCHAR(16)     NOT NULL DEFAULT 'MEDIUM'        COMMENT 'LOW/MEDIUM/HIGH/FORCED',
    algo_type               VARCHAR(16)     NOT NULL DEFAULT 'MARKET'        COMMENT 'MARKET/LIMIT/TWAP/VWAP/POV',
    max_participation_rate  FLOAT           NULL                             COMMENT '最大参与率（0-1）',
    slippage_budget_bps     FLOAT           NULL                             COMMENT '允许滑点预算（bps）',
    child_order_interval_ms INT             NULL                             COMMENT '子订单间隔（毫秒）',
    cancel_replace_policy   VARCHAR(32)     NULL                             COMMENT '撤改单策略',
    policy_version          VARCHAR(16)     NOT NULL DEFAULT '1.0'           COMMENT '策略规则版本号',
    as_of                   DATETIME        NOT NULL                         COMMENT '快照生成时间',
    created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录写入时间',
    PRIMARY KEY (id),
    UNIQUE KEY uq_eps_intent_id     (intent_id),
    INDEX idx_eps_account_symbol    (account_id, symbol),
    INDEX idx_eps_as_of             (as_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M3: 执行策略快照（每笔意图一条）';
"""

MYSQL_UP_PRETRADE_COST_ESTIMATES = """
CREATE TABLE IF NOT EXISTS pretrade_cost_estimates (
    id                  BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    intent_id           VARCHAR(64)     NOT NULL                         COMMENT '关联执行意图ID',
    symbol              VARCHAR(32)     NOT NULL                         COMMENT '标的代码',
    action              VARCHAR(8)      NOT NULL                         COMMENT 'BUY/SELL',
    estimated_size      FLOAT           NULL                             COMMENT '估算下单数量',
    adv_pct             FLOAT           NULL                             COMMENT 'ADV 占比（0-1）',
    spread_cost_bps     FLOAT           NULL                             COMMENT '买卖价差成本（bps）',
    market_impact_bps   FLOAT           NULL                             COMMENT '市场冲击成本（bps）',
    timing_risk_bps     FLOAT           NULL                             COMMENT '时间风险成本（bps）',
    opportunity_cost_bps FLOAT          NULL                             COMMENT '机会成本（bps）',
    total_cost_bps      FLOAT           NULL                             COMMENT '总估算成本（bps）',
    regime_label        VARCHAR(32)     NULL                             COMMENT '估算时市场体制',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录写入时间',
    PRIMARY KEY (id),
    UNIQUE KEY uq_pce_intent_id      (intent_id),
    INDEX idx_pce_symbol             (symbol),
    INDEX idx_pce_created_at         (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M3: 预交易成本估算（下单前生成）';
"""

MYSQL_UP_EXECUTION_REPLAY_LOGS = """
CREATE TABLE IF NOT EXISTS execution_replay_logs (
    id                  BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    parent_intent_id    VARCHAR(64)     NOT NULL                         COMMENT '父意图ID',
    parent_order_id     VARCHAR(64)     NULL                             COMMENT '父订单ID（broker侧）',
    child_seq           INT             NOT NULL DEFAULT 0               COMMENT '子订单序号（0起始）',
    symbol              VARCHAR(32)     NOT NULL                         COMMENT '标的代码',
    child_qty           FLOAT           NULL                             COMMENT '子订单数量',
    child_arrival_price FLOAT           NULL                             COMMENT '子订单到达时价格（arrival price）',
    child_fill_price    FLOAT           NULL                             COMMENT '子订单成交价',
    fill_rate           FLOAT           NULL                             COMMENT '成交率（0-1）',
    t_ms                BIGINT          NULL                             COMMENT '时间偏移（相对父订单提交，毫秒）',
    phase               VARCHAR(16)     NULL                             COMMENT 'PRE_OPEN/OPEN/INTRADAY/CLOSE',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录写入时间',
    PRIMARY KEY (id),
    INDEX idx_erl_parent_intent_id   (parent_intent_id),
    INDEX idx_erl_parent_order_id    (parent_order_id),
    INDEX idx_erl_symbol             (symbol),
    INDEX idx_erl_created_at         (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M3: 子订单回放日志（child-order timeline）';
"""

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL — M4 Live Safety & Model Degradation Guard
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP_MODEL_DEGRADATION_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS model_degradation_snapshots (
    id                  BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    account_id          VARCHAR(64)     NOT NULL                         COMMENT '账户ID',
    strategy_id         VARCHAR(64)     NULL                             COMMENT '策略ID（NULL表示全局）',
    metric_type         VARCHAR(32)     NOT NULL                         COMMENT 'HIT_RATE_DRIFT/ECE_DRIFT/EXEC_COST_DRIFT/BROKER_REJECT_SPIKE/FEATURE_FRESHNESS',
    current_value       FLOAT           NULL                             COMMENT '当前指标值',
    baseline_value      FLOAT           NULL                             COMMENT '基线指标值（历史均值/指定参考）',
    drift_magnitude     FLOAT           NULL                             COMMENT '漂移幅度（abs）',
    drift_direction     VARCHAR(8)      NULL                             COMMENT 'UP/DOWN/NONE',
    severity            VARCHAR(16)     NOT NULL DEFAULT 'OK'            COMMENT 'OK/WARNING/CRITICAL',
    triggered_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '退化检测触发时间',
    resolved_at         DATETIME        NULL                             COMMENT '退化恢复/关闭时间',
    details_json        JSON            NULL                             COMMENT '附加诊断上下文（sample_size/window等）',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录写入时间',
    PRIMARY KEY (id),
    INDEX idx_mds_account_strategy  (account_id, strategy_id),
    INDEX idx_mds_metric_type       (metric_type),
    INDEX idx_mds_severity          (severity),
    INDEX idx_mds_triggered_at      (triggered_at),
    INDEX idx_mds_resolved_at       (resolved_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M4: 模型/数据/执行退化快照';
"""

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL — M5 Research-to-Live Governance
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP_PROMOTION_PIPELINE_RUNS = """
CREATE TABLE IF NOT EXISTS promotion_pipeline_runs (
    id                  BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    strategy_id         VARCHAR(64)     NOT NULL                         COMMENT '策略ID',
    strategy_name       VARCHAR(128)    NULL                             COMMENT '策略名称',
    from_stage          VARCHAR(32)     NOT NULL                         COMMENT '来源阶段（DISCOVERY/PAPER/CHALLENGER/SHADOW_LIVE/LIMITED_LIVE/PRODUCTION）',
    to_stage            VARCHAR(32)     NOT NULL                         COMMENT '目标阶段',
    triggered_by        VARCHAR(64)     NULL                             COMMENT '触发者（user/system/auto）',
    evidence_json       JSON            NULL                             COMMENT '晋级证据（backtest_id/paper_win_rate/shadow_alpha等）',
    approved_by         VARCHAR(64)     NULL                             COMMENT '审批人（NULL为自动晋级）',
    rollback_reason     TEXT            NULL                             COMMENT '回滚原因（NULL表示未回滚）',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录写入时间',
    PRIMARY KEY (id),
    INDEX idx_ppr_strategy_id       (strategy_id),
    INDEX idx_ppr_from_stage        (from_stage),
    INDEX idx_ppr_to_stage          (to_stage),
    INDEX idx_ppr_created_at        (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M5: 策略晋级管道流水（阶段转换审计）';
"""

MYSQL_UP_EXPERIMENT_LEDGER_ENTRIES = """
CREATE TABLE IF NOT EXISTS experiment_ledger_entries (
    id                      BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    experiment_id           VARCHAR(64)     NOT NULL                         COMMENT '实验唯一ID',
    hypothesis              TEXT            NOT NULL                         COMMENT '实验假设',
    variant_definition_json JSON            NULL                             COMMENT '实验variant定义',
    control_outcome_json    JSON            NULL                             COMMENT '对照组结果',
    variant_outcome_json    JSON            NULL                             COMMENT '实验组结果',
    cost_adjusted_delta     FLOAT           NULL                             COMMENT '净成本后alpha差值',
    significance_pct        FLOAT           NULL                             COMMENT '统计显著性（%）',
    status                  VARCHAR(16)     NOT NULL DEFAULT 'RUNNING'       COMMENT 'RUNNING/CONCLUDED/ROLLED_BACK',
    rollout_decision        VARCHAR(16)     NULL                             COMMENT 'DEPLOY/REJECT/EXTEND',
    rollback_reason         TEXT            NULL                             COMMENT '回滚原因（ROLLED_BACK时填充）',
    created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '实验创建时间',
    concluded_at            DATETIME        NULL                             COMMENT '实验结论时间',
    PRIMARY KEY (id),
    UNIQUE KEY uq_ele_experiment_id  (experiment_id),
    INDEX idx_ele_status             (status),
    INDEX idx_ele_created_at         (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.1 M5: 实验总账（AB Test → Experiment Ledger）';
"""

# ─────────────────────────────────────────────────────────────────────────────
# Rollback DDL
# ─────────────────────────────────────────────────────────────────────────────

ROLLBACK_DROP_TABLES = [
    "DROP TABLE IF EXISTS experiment_ledger_entries;",
    "DROP TABLE IF EXISTS promotion_pipeline_runs;",
    "DROP TABLE IF EXISTS model_degradation_snapshots;",
    "DROP TABLE IF EXISTS execution_replay_logs;",
    "DROP TABLE IF EXISTS pretrade_cost_estimates;",
    "DROP TABLE IF EXISTS execution_policy_snapshots;",
    "DROP TABLE IF EXISTS risk_budget_snapshots;",
    "DROP TABLE IF EXISTS shadow_portfolio_entries;",
    "DROP TABLE IF EXISTS factor_registry;",
    "DROP TABLE IF EXISTS strategy_scorecard_snapshots;",
]

# 所有新增表，按创建顺序排列
ALL_NEW_TABLES = [
    ("strategy_scorecard_snapshots", MYSQL_UP_STRATEGY_SCORECARD_SNAPSHOTS),
    ("factor_registry", MYSQL_UP_FACTOR_REGISTRY),
    ("shadow_portfolio_entries", MYSQL_UP_SHADOW_PORTFOLIO_ENTRIES),
    ("risk_budget_snapshots", MYSQL_UP_RISK_BUDGET_SNAPSHOTS),
    ("execution_policy_snapshots", MYSQL_UP_EXECUTION_POLICY_SNAPSHOTS),
    ("pretrade_cost_estimates", MYSQL_UP_PRETRADE_COST_ESTIMATES),
    ("execution_replay_logs", MYSQL_UP_EXECUTION_REPLAY_LOGS),
    ("model_degradation_snapshots", MYSQL_UP_MODEL_DEGRADATION_SNAPSHOTS),
    ("promotion_pipeline_runs", MYSQL_UP_PROMOTION_PIPELINE_RUNS),
    ("experiment_ledger_entries", MYSQL_UP_EXPERIMENT_LEDGER_ENTRIES),
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _get_engine():
    from app.models.db import engine

    return engine


async def _is_mysql(engine) -> bool:
    return "mysql" in str(engine.url).lower()


async def _table_exists(conn, table: str) -> bool:
    from sqlalchemy import text

    row = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema=DATABASE() AND table_name=:t"
        ),
        {"t": table},
    )
    return row.scalar_one() > 0


# ─────────────────────────────────────────────────────────────────────────────
# Check
# ─────────────────────────────────────────────────────────────────────────────


async def check() -> None:
    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    if not is_mysql:
        print(
            "[Check] WARNING — non-MySQL database detected; this script targets MySQL only."
        )
        return
    print("[Check] Database: MySQL")
    async with engine.connect() as conn:
        for tbl, _ in ALL_NEW_TABLES:
            exists = await _table_exists(conn, tbl)
            print(f"  {'✅ EXISTS' if exists else '❌ MISSING'}  table: {tbl}")


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────────────


async def upgrade() -> None:
    from sqlalchemy import text

    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    if not is_mysql:
        print("[Upgrade] ERROR — non-MySQL database. This script only supports MySQL.")
        sys.exit(1)

    print("[Upgrade] Database: MySQL — V10.5.1")

    async with engine.begin() as conn:
        for tbl, ddl in ALL_NEW_TABLES:
            await conn.execute(text(ddl))
            print(f"  ✅ {tbl} — created (or already exists)")

    print("[Upgrade] V10.5.1 migration completed ✓")
    print(
        "[Upgrade] 提示: 新表已建立，请运行 upgrade_to_v10_5_1.py --check 确认所有表存在。"
    )
    print("[Upgrade] 定时任务（Epic C2）与数据回补（backfill）脚本请参见 scripts/by_version/v10_5_1/。")


# ─────────────────────────────────────────────────────────────────────────────
# Rollback
# ─────────────────────────────────────────────────────────────────────────────


async def rollback() -> None:
    from sqlalchemy import text

    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    if not is_mysql:
        print("[Rollback] ERROR — non-MySQL database.")
        sys.exit(1)

    print("[Rollback] WARNING: This will DROP all 10 V10.5.1 tables.")
    print("[Rollback] 这将删除以下表（不可恢复）：")
    for tbl, _ in ALL_NEW_TABLES:
        print(f"  - {tbl}")
    confirm = input("\nType 'yes' to confirm rollback: ").strip()
    if confirm != "yes":
        print("[Rollback] Aborted.")
        return

    async with engine.begin() as conn:
        for stmt in ROLLBACK_DROP_TABLES:
            await conn.execute(text(stmt))
            print(f"  ✅ {stmt.strip()}")

    print("[Rollback] V10.5.1 rollback completed ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V10.5.1 DB Migration — 机构级研究与交易纪律")
    parser.add_argument("--check", action="store_true", help="检查所有新表是否存在")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="回滚（删除所有 V10.5.1 新增表，危险！）",
    )
    args = parser.parse_args()

    if args.check:
        asyncio.run(check())
    elif args.rollback:
        asyncio.run(rollback())
    else:
        asyncio.run(upgrade())
