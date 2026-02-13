#!/bin/bash
# AI 评估历史功能数据库迁移脚本

echo "开始创建 AI 评估历史表..."

# 读取数据库配置
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"
DB_NAME="${DB_NAME:-ai_trading}"
DB_USER="${DB_USER:-root}"

# 执行建表SQL
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" << 'EOF'
-- AI 评估历史记录表
CREATE TABLE IF NOT EXISTS ai_evaluation_history (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'ID',
    account_id VARCHAR(64) NOT NULL COMMENT '账户ID',
    batch_id VARCHAR(64) NOT NULL COMMENT '批次ID',
    symbol VARCHAR(32) NOT NULL COMMENT '标的代码',
    current_price DECIMAL(20, 6) DEFAULT NULL COMMENT '评估时价格',
    
    direction VARCHAR(16) DEFAULT NULL COMMENT '方向',
    confidence INT DEFAULT NULL COMMENT '置信度',
    action VARCHAR(16) DEFAULT NULL COMMENT '操作',
    
    entry_price DECIMAL(20, 6) DEFAULT NULL COMMENT '入场价',
    stop_loss DECIMAL(20, 6) DEFAULT NULL COMMENT '止损价',
    take_profit DECIMAL(20, 6) DEFAULT NULL COMMENT '止盈价',
    position_pct DECIMAL(10, 4) DEFAULT NULL COMMENT '仓位比例',
    
    risk_level VARCHAR(16) DEFAULT NULL COMMENT '风险等级',
    reasoning TEXT COMMENT '决策理由',
    key_factors JSON COMMENT '关键因素',
    
    risk_reward_ratio VARCHAR(16) DEFAULT NULL COMMENT '风险收益比',
    scenarios JSON COMMENT '情景分析',
    catalysts JSON COMMENT '催化剂',
    holding_period VARCHAR(64) DEFAULT NULL COMMENT '持有周期',
    
    dimensions JSON COMMENT '多维评分',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    
    INDEX idx_eval_account_batch (account_id, batch_id),
    INDEX idx_eval_symbol (symbol),
    INDEX idx_eval_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI评估历史';
EOF

if [ $? -eq 0 ]; then
    echo "✅ AI 评估历史表创建成功！"
else
    echo "❌ 表创建失败，请检查数据库配置"
    exit 1
fi
