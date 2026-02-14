#!/bin/bash
# 数据库迁移测试脚本
# 用于验证迁移脚本的正确性

set -e  # 遇到错误立即退出

echo "=================================="
echo "数据库迁移测试脚本"
echo "=================================="

# 配置
VERSION="v3.1.1"
BACKUP_FILE="test_backup_$(date +%Y%m%d_%H%M%S).sql"
UPGRADE_SCRIPT="scripts/migrations/upgrade_to_${VERSION}.py"
VERIFY_SCRIPT="scripts/migrations/verify_${VERSION}.py"
ROLLBACK_SCRIPT="scripts/migrations/rollback_from_${VERSION}.py"

# 颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 检查脚本是否存在
check_scripts() {
    log_info "检查迁移脚本..."
    
    if [ ! -f "$UPGRADE_SCRIPT" ]; then
        log_error "升级脚本不存在: $UPGRADE_SCRIPT"
        exit 1
    fi
    
    if [ ! -f "$VERIFY_SCRIPT" ]; then
        log_error "验证脚本不存在: $VERIFY_SCRIPT"
        exit 1
    fi
    
    if [ ! -f "$ROLLBACK_SCRIPT" ]; then
        log_error "回滚脚本不存在: $ROLLBACK_SCRIPT"
        exit 1
    fi
    
    log_info "✅ 所有脚本存在"
}

# 备份数据库
backup_database() {
    log_info "备份数据库..."
    
    # 检查是否使用 SQLite
    if [ -f "ai_trading.db" ]; then
        cp ai_trading.db "${BACKUP_FILE}.db"
        log_info "✅ SQLite 备份完成: ${BACKUP_FILE}.db"
    else
        log_warning "未找到 SQLite 数据库，跳过备份"
    fi
}

# 测试升级
test_upgrade() {
    log_info "测试升级到 ${VERSION}..."
    
    python "$UPGRADE_SCRIPT"
    
    if [ $? -eq 0 ]; then
        log_info "✅ 升级成功"
    else
        log_error "❌ 升级失败"
        exit 1
    fi
}

# 测试验证
test_verify() {
    log_info "验证数据库结构..."
    
    python "$VERIFY_SCRIPT"
    
    if [ $? -eq 0 ]; then
        log_info "✅ 验证通过"
    else
        log_error "❌ 验证失败"
        exit 1
    fi
}

# 测试回滚
test_rollback() {
    log_info "测试回滚..."
    
    # 自动确认回滚
    echo "ROLLBACK" | python "$ROLLBACK_SCRIPT" --confirm
    
    if [ $? -eq 0 ]; then
        log_info "✅ 回滚成功"
    else
        log_error "❌ 回滚失败"
        exit 1
    fi
}

# 再次升级（验证幂等性）
test_upgrade_again() {
    log_info "再次升级（测试幂等性）..."
    
    python "$UPGRADE_SCRIPT"
    
    if [ $? -eq 0 ]; then
        log_info "✅ 再次升级成功"
    else
        log_error "❌ 再次升级失败"
        exit 1
    fi
    
    # 再次验证
    python "$VERIFY_SCRIPT"
    
    if [ $? -eq 0 ]; then
        log_info "✅ 再次验证通过"
    else
        log_error "❌ 再次验证失败"
        exit 1
    fi
}

# 恢复数据库
restore_database() {
    log_info "恢复数据库..."
    
    if [ -f "${BACKUP_FILE}.db" ]; then
        cp "${BACKUP_FILE}.db" ai_trading.db
        log_info "✅ 数据库恢复完成"
    else
        log_warning "未找到备份文件，跳过恢复"
    fi
}

# 清理测试文件
cleanup() {
    log_info "清理测试文件..."
    
    if [ -f "${BACKUP_FILE}.db" ]; then
        rm "${BACKUP_FILE}.db"
        log_info "✅ 清理完成"
    fi
}

# 主流程
main() {
    echo ""
    log_info "开始测试迁移脚本"
    echo ""
    
    # 1. 检查脚本
    check_scripts
    echo ""
    
    # 2. 备份
    backup_database
    echo ""
    
    # 3. 测试升级
    test_upgrade
    echo ""
    
    # 4. 验证
    test_verify
    echo ""
    
    # 5. 测试回滚
    test_rollback
    echo ""
    
    # 6. 再次升级（幂等性）
    test_upgrade_again
    echo ""
    
    # 7. 恢复数据库
    restore_database
    echo ""
    
    # 8. 清理
    cleanup
    echo ""
    
    echo "=================================="
    log_info "🎉 所有测试通过！"
    echo "=================================="
    echo ""
    echo "测试覆盖："
    echo "  ✅ 升级脚本执行"
    echo "  ✅ 数据库结构验证"
    echo "  ✅ 回滚脚本执行"
    echo "  ✅ 幂等性验证"
    echo "  ✅ 数据库恢复"
    echo ""
    echo "下一步："
    echo "  1. 在生产环境备份数据库"
    echo "  2. 执行升级: python $UPGRADE_SCRIPT --production"
    echo "  3. 验证结果: python $VERIFY_SCRIPT"
    echo "  4. 记录版本: python scripts/migrations/version_manager.py --record $VERSION"
    echo ""
}

# 捕获退出信号
trap 'log_error "测试被中断"; restore_database; exit 1' INT TERM

# 执行主流程
main
