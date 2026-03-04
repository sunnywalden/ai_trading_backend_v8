#!/usr/bin/env python3
"""upgrade_to_v10_3_3.py — V10.3.3 数据库迁移脚本

新增 6 张表：
  1. execution_quality_log        - IS 四分解执行质量日志
  2. portfolio_factor_exposure    - 五因子敞口快照
  3. agent_communication_log      - 多智能体通信日志
  4. confidence_calibration_snapshot - 置信度校准快照
  5. decision_post_mortems        - 决策事后剖析
  6. signal_weight_history        - Kalman 信号权重演化历史

用法：
  cd /path/to/ai_trading_backend_v8
  python scripts/migrations/upgrade_to_v10_3_3.py
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import text
from app.models.db import engine


CREATE_STATEMENTS = [
    # ─── 1. execution_quality_log ────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS execution_quality_log (
        id                   BIGINT          NOT NULL AUTO_INCREMENT,
        intent_id            BIGINT          NOT NULL COMMENT '关联 autonomous_execution_intent.id',
        symbol               VARCHAR(20)     NOT NULL,
        user_id              VARCHAR(64)     NOT NULL,
        delay_cost_bps       DOUBLE          NOT NULL DEFAULT 0,
        market_impact_bps    DOUBLE          NOT NULL DEFAULT 0,
        opportunity_cost_bps DOUBLE          NOT NULL DEFAULT 0,
        timing_cost_bps      DOUBLE          NOT NULL DEFAULT 0,
        total_is_bps         DOUBLE          NOT NULL DEFAULT 0,
        arrival_price        DOUBLE          NULL,
        fill_price           DOUBLE          NULL,
        mid_price_at_order   DOUBLE          NULL,
        vwap_reference       DOUBLE          NULL,
        quantity_ordered     DOUBLE          NULL,
        quantity_filled      DOUBLE          NULL,
        fill_rate            DOUBLE          NULL,
        time_to_fill_ms      INT             NULL,
        algo_type            VARCHAR(32)     NULL,
        quality_score        DOUBLE          NULL,
        grade                VARCHAR(4)      NULL,
        created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        INDEX idx_eql_intent (intent_id),
        INDEX idx_eql_user_symbol (user_id, symbol),
        INDEX idx_eql_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IS 执行质量四分解日志 V10.3.3';
    """,

    # ─── 2. portfolio_factor_exposure ─────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS portfolio_factor_exposure (
        id                   BIGINT          NOT NULL AUTO_INCREMENT,
        user_id              VARCHAR(64)     NOT NULL,
        snapshot_at          DATETIME        NOT NULL,
        beta_market          DOUBLE          NOT NULL DEFAULT 0,
        beta_hml             DOUBLE          NOT NULL DEFAULT 0,
        beta_smb             DOUBLE          NOT NULL DEFAULT 0,
        beta_mom             DOUBLE          NOT NULL DEFAULT 0,
        beta_qmj             DOUBLE          NOT NULL DEFAULT 0,
        var_99               DOUBLE          NULL,
        es_97_5              DOUBLE          NULL,
        volatility_annualized DOUBLE         NULL,
        avg_pairwise_corr    DOUBLE          NULL,
        max_pairwise_corr    DOUBLE          NULL,
        correlation_spike    TINYINT(1)      NOT NULL DEFAULT 0,
        top_corr_pair        VARCHAR(40)     NULL,
        positions_count      INT             NOT NULL DEFAULT 0,
        gross_exposure       DOUBLE          NULL,
        net_exposure         DOUBLE          NULL,
        portfolio_beta       DOUBLE          NULL,
        weights_snapshot     JSON            NULL,
        created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        INDEX idx_pfe_user_snap (user_id, snapshot_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='五因子敞口快照 V10.3.3';
    """,

    # ─── 3. agent_communication_log ───────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS agent_communication_log (
        id                   BIGINT          NOT NULL AUTO_INCREMENT,
        run_id               VARCHAR(64)     NOT NULL,
        user_id              VARCHAR(64)     NOT NULL,
        agent_id             VARCHAR(64)     NOT NULL,
        agent_role           VARCHAR(32)     NOT NULL,
        sequence             BIGINT          NOT NULL DEFAULT 0,
        message_type         VARCHAR(32)     NOT NULL,
        content              LONGTEXT        NOT NULL,
        confidence           DOUBLE          NULL,
        structured_output    JSON            NULL,
        tool_calls           JSON            NULL,
        symbol               VARCHAR(20)     NULL,
        `trigger`            VARCHAR(64)     NULL,
        model_used           VARCHAR(64)     NULL,
        tokens_used          BIGINT          NULL,
        latency_ms           BIGINT          NULL,
        created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        INDEX idx_acl_run_seq (run_id, sequence),
        INDEX idx_acl_user_created (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='多智能体通信日志 V10.3.3';
    """,

    # ─── 4. confidence_calibration_snapshot ───────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS confidence_calibration_snapshot (
        id                   BIGINT          NOT NULL AUTO_INCREMENT,
        user_id              VARCHAR(64)     NOT NULL,
        snapshot_date        DATE            NOT NULL,
        brier_score          DOUBLE          NULL,
        ece                  DOUBLE          NULL,
        overconfidence_bias  DOUBLE          NULL,
        calibration_buckets  JSON            NULL,
        lookback_days        INT             NOT NULL DEFAULT 90,
        total_samples        BIGINT          NULL,
        valid_bucket_count   BIGINT          NULL,
        needs_adjustment     TINYINT(1)      NOT NULL DEFAULT 0,
        adjustment_factor    DOUBLE          NULL,
        adjustment_applied_at DATETIME       NULL,
        created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE INDEX idx_ccs_user_date (user_id, snapshot_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='置信度校准快照 V10.3.3';
    """,

    # ─── 5. decision_post_mortems ─────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS decision_post_mortems (
        id                   BIGINT          NOT NULL AUTO_INCREMENT,
        user_id              VARCHAR(64)     NOT NULL,
        trade_id             VARCHAR(64)     NOT NULL,
        symbol               VARCHAR(20)     NOT NULL,
        direction            VARCHAR(8)      NULL,
        entry_price          DOUBLE          NULL,
        exit_price           DOUBLE          NULL,
        realized_pnl         DOUBLE          NULL,
        hold_days            BIGINT          NULL,
        factual_summary      LONGTEXT        NULL,
        counterfactual_buy   LONGTEXT        NULL,
        counterfactual_hold  LONGTEXT        NULL,
        counterfactual_sell  LONGTEXT        NULL,
        key_lessons          LONGTEXT        NULL,
        improvement_suggestions LONGTEXT     NULL,
        pattern_tags         JSON            NULL,
        error_category       VARCHAR(64)     NULL,
        cognitive_bias       VARCHAR(64)     NULL,
        insight_id           BIGINT          NULL,
        model_used           VARCHAR(64)     NULL DEFAULT 'deepseek-reasoner',
        reasoning_tokens     BIGINT          NULL,
        generation_latency_ms BIGINT         NULL,
        status               VARCHAR(16)     NOT NULL DEFAULT 'pending',
        created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE INDEX idx_dpm_trade (trade_id),
        INDEX idx_dpm_user_symbol (user_id, symbol)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='决策事后剖析报告 V10.3.3';
    """,

    # ─── 6. signal_weight_history ─────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS signal_weight_history (
        id                         BIGINT      NOT NULL AUTO_INCREMENT,
        user_id                    VARCHAR(64) NOT NULL,
        record_date                DATE        NOT NULL,
        dimension                  VARCHAR(64) NOT NULL,
        weight_before              DOUBLE      NOT NULL,
        weight_after               DOUBLE      NOT NULL,
        weight_momentum_adjusted   DOUBLE      NULL,
        kalman_gain                DOUBLE      NULL,
        process_noise              DOUBLE      NOT NULL DEFAULT 0.001,
        measurement_noise          DOUBLE      NOT NULL DEFAULT 0.01,
        posterior_variance         DOUBLE      NULL,
        ic_5d                      DOUBLE      NULL,
        ic_20d                     DOUBLE      NULL,
        ic_60d                     DOUBLE      NULL,
        ic_rank                    BIGINT      NULL,
        momentum_adjustment        DOUBLE      NULL,
        adjustment_reason          VARCHAR(128) NULL,
        global_weights_snapshot    JSON        NULL,
        created_at                 DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE INDEX idx_swh_user_date_dim (user_id, record_date, dimension),
        INDEX idx_swh_date (record_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Kalman 信号权重演化历史 V10.3.3';
    """,
]


async def upgrade() -> None:
    print("=" * 60)
    print("V10.3.3 数据库迁移")
    print("=" * 60)
    async with engine.begin() as conn:
        for i, stmt in enumerate(CREATE_STATEMENTS, 1):
            clean = stmt.strip()
            # 提取表名用于日志
            table_name = "unknown"
            for line in clean.splitlines():
                if "CREATE TABLE" in line:
                    parts = line.split()
                    for j, p in enumerate(parts):
                        if p.upper() in ("TABLE", "EXISTS"):
                            if j + 1 < len(parts):
                                table_name = parts[j + 1].strip("(")
                    break
            try:
                await conn.execute(text(clean))
                print(f"  [{i}/{len(CREATE_STATEMENTS)}] ✅ {table_name}")
            except Exception as e:
                print(f"  [{i}/{len(CREATE_STATEMENTS)}] ❌ {table_name}: {e}")
    print("\n✅ V10.3.3 迁移完成！")


if __name__ == "__main__":
    asyncio.run(upgrade())
