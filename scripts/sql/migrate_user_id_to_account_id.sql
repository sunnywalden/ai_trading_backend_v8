-- ============================================================
-- Migration: rename user_id → account_id in 5 securities-data tables
-- Version: V10.3.3+
-- Reason: 证券账号与平台账户相互独立，通过 account_id（券商账号）隔离
-- Tables:
--   signal_weight_history
--   portfolio_factor_exposure
--   confidence_calibration_snapshot
--   execution_quality_log
--   decision_post_mortems
-- ============================================================

-- 1. signal_weight_history
--    旧唯一索引：idx_swh_user_date_dim (user_id, record_date, dimension)
--    新唯一索引：idx_swh_account_date_dim (account_id, record_date, dimension)
ALTER TABLE signal_weight_history
    CHANGE COLUMN user_id account_id VARCHAR(64) NOT NULL COMMENT '券商账号';

DROP INDEX idx_swh_user_date_dim ON signal_weight_history;
CREATE UNIQUE INDEX idx_swh_account_date_dim
    ON signal_weight_history (account_id, record_date, dimension);

-- 2. portfolio_factor_exposure
--    旧索引：idx_pfe_user_snap (user_id, snapshot_at)
--    新索引：idx_pfe_account_snap (account_id, snapshot_at)
ALTER TABLE portfolio_factor_exposure
    CHANGE COLUMN user_id account_id VARCHAR(64) NOT NULL COMMENT '券商账号';

DROP INDEX idx_pfe_user_snap ON portfolio_factor_exposure;
CREATE INDEX idx_pfe_account_snap
    ON portfolio_factor_exposure (account_id, snapshot_at);

-- 3. confidence_calibration_snapshot
--    旧唯一索引：idx_ccs_user_date (user_id, snapshot_date)
--    新唯一索引：idx_ccs_account_date (account_id, snapshot_date)
ALTER TABLE confidence_calibration_snapshot
    CHANGE COLUMN user_id account_id VARCHAR(64) NOT NULL COMMENT '券商账号';

DROP INDEX idx_ccs_user_date ON confidence_calibration_snapshot;
CREATE UNIQUE INDEX idx_ccs_account_date
    ON confidence_calibration_snapshot (account_id, snapshot_date);

-- 4. execution_quality_log
--    旧索引：idx_eql_user_symbol (user_id, symbol)
--    新索引：idx_eql_account_symbol (account_id, symbol)
ALTER TABLE execution_quality_log
    CHANGE COLUMN user_id account_id VARCHAR(64) NOT NULL COMMENT '券商账号';

DROP INDEX idx_eql_user_symbol ON execution_quality_log;
CREATE INDEX idx_eql_account_symbol
    ON execution_quality_log (account_id, symbol);

-- 5. decision_post_mortems
--    旧索引：idx_dpm_user_symbol (user_id, symbol)
--    新索引：idx_dpm_account_symbol (account_id, symbol)
ALTER TABLE decision_post_mortems
    CHANGE COLUMN user_id account_id VARCHAR(64) NOT NULL COMMENT '券商账号';

DROP INDEX idx_dpm_user_symbol ON decision_post_mortems;
CREATE INDEX idx_dpm_account_symbol
    ON decision_post_mortems (account_id, symbol);
