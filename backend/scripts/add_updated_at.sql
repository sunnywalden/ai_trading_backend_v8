-- 检查并添加 updated_at 列到 ai_evaluation_history 表

-- 添加 updated_at 列
ALTER TABLE ai_evaluation_history 
ADD COLUMN IF NOT EXISTS updated_at DATETIME 
DEFAULT CURRENT_TIMESTAMP 
ON UPDATE CURRENT_TIMESTAMP 
COMMENT '更新时间' 
AFTER created_at;

-- 验证列已添加
SELECT COLUMN_NAME, DATA_TYPE, COLUMN_DEFAULT, COLUMN_COMMENT
FROM information_schema.COLUMNS 
WHERE TABLE_SCHEMA = DATABASE()
AND TABLE_NAME = 'ai_evaluation_history' 
AND COLUMN_NAME IN ('created_at', 'updated_at');
