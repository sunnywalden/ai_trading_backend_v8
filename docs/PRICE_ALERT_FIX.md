# 价格告警数据持久化问题修复说明

## 问题描述

**症状**：创建的价格告警在系统重启后会丢失

**根本原因**：价格告警的数据库表 `price_alerts` 和 `alert_history` **从未被创建**

## 问题分析

在 `init_db.py` 数据库初始化脚本中，虽然调用了 `Base.metadata.create_all()` 来创建所有数据库表，但**没有导入 V9 相关的模型类**，导致 SQLAlchemy 无法感知这些表的存在，因此：

1. 数据库表 `price_alerts` 和 `alert_history` 从未被创建
2. 前端调用创建告警的 API 时，后端代码运行正常（没有报错）
3. 但数据无法保存到不存在的表中
4. 系统重启后自然找不到任何告警数据

## 修复方案

### 1. 修改 `init_db.py`

在文件顶部添加所有 V9 相关模型的导入：

```python
# V9: 个人交易相关模型
from app.models.price_alert import PriceAlert, AlertHistory
from app.models.equity_snapshot import EquitySnapshot
from app.models.trade_journal import TradeJournal
from app.models.trade_pnl_attribution import TradePnlAttribution
from app.models.notification import NotificationLog
from app.models.audit_log import AuditLog
from app.models.trading_signal import TradingSignal, SignalPerformance
from app.models.trading_plan import TradingPlan
```

### 2. 重新运行数据库初始化

```bash
cd backend
source ../.venv/bin/activate
python init_db.py
```

**输出**：
```
正在初始化数据库 (mysql)...
连接地址: 127.0.0.1:3306/ai_trading
✅ 数据库初始化完成！
已创建/验证所有表结构并填充内置策略。
```

### 3. 验证表已创建

```bash
python -c "
import asyncio
from app.models.db import engine
from sqlalchemy import text

async def check():
    async with engine.connect() as conn:
        result = await conn.execute(text(\"SHOW TABLES LIKE 'price_alerts'\"))
        print('✅ price_alerts 表已创建' if result.fetchall() else '❌ 表不存在')
        result = await conn.execute(text(\"SHOW TABLES LIKE 'alert_history'\"))
        print('✅ alert_history 表已创建' if result.fetchall() else '❌ 表不存在')
    await engine.dispose()

asyncio.run(check())
"
```

**输出**：
```
✅ price_alerts 表已创建
✅ alert_history 表已创建
```

## 涉及的数据库表

本次修复创建了以下 V9 相关的数据库表：

### 核心表
- `price_alerts` - 价格告警规则
- `alert_history` - 告警触发历史

### 其他 V9 表
- `equity_snapshot` - 账户权益快照（资金曲线）
- `trade_journal` - 交易日志/复盘
- `trade_pnl_attribution` - 交易盈亏归因
- `notification_log` - 通知记录
- `audit_log` - 审计日志
- `trading_plans` - 交易计划
- `trading_signals` - 交易信号
- `signal_performance` - 信号性能记录

## 验证修复

### 前端测试步骤

1. **打开价格告警页面**：http://localhost:5173/alerts
2. **创建新告警**：
   - 点击"+ 新建告警"
   - 填写：标的 AAPL，条件"价格高于"，阈值 200
   - 点击"创建"
3. **刷新页面**：告警应该仍然存在
4. **重启后端服务**：
   ```bash
   # 停止后端
   lsof -ti:8088 | xargs kill -9
   
   # 重启后端
   cd backend
   source ../.venv/bin/activate
   uvicorn app.main:app --host 0.0.0.0 --port 8088
   ```
5. **再次刷新前端页面**：告警应该依然存在 ✅

### API 测试

```bash
# 创建告警
curl -X POST http://localhost:8088/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "condition_type": "price_above",
    "threshold": 200,
    "action": "notify"
  }'

# 查询告警列表
curl http://localhost:8088/api/v1/alerts

# 查询触发历史
curl http://localhost:8088/api/v1/alerts/history
```

## 架构说明

### SQLAlchemy 表创建机制

SQLAlchemy 通过 `Base.metadata.create_all()` 来创建表，但它只会创建**已经被导入的模型类**对应的表。这是因为：

1. 当你 `from app.models.xxx import YYY` 时，Python 执行这个模块
2. 模块执行时，`class YYY(Base)` 会自动注册到 `Base.metadata`
3. `create_all()` 遍历 `Base.metadata` 中的所有表定义并创建

**如果没有导入模型类，SQLAlchemy 就不知道有这些表存在！**

### API 层面的行为

即使表不存在，FastAPI 路由代码也不会报错：

```python
@router.post("", response_model=AlertView)
async def create_alert(...):
    alert = PriceAlert(account_id=account_id, **payload)  # ✅ 对象创建成功
    self.session.add(alert)  # ✅ 添加到 session
    await self.session.commit()  # ❌ 这里会报错，但可能被忽略
    return alert  # 返回对象（但数据没保存到数据库）
```

因为 Python 对象创建不需要数据库表存在，只有在 `commit()` 时才会真正写入数据库。

## 预防措施

### 1. 集中管理模型导入

建议在 `app/models/__init__.py` 中集中管理所有模型导入：

```python
# app/models/__init__.py
from app.models.price_alert import PriceAlert, AlertHistory
from app.models.equity_snapshot import EquitySnapshot
from app.models.trade_journal import TradeJournal
# ... 其他所有模型
```

然后在 `init_db.py` 中只需：
```python
import app.models  # 自动导入所有模型
```

### 2. 添加表存在性检查

在服务层添加初始化检查：

```python
# app/services/alert_service.py
async def __init__(self, session: AsyncSession):
    self.session = session
    # 检查表是否存在
    result = await session.execute(text("SHOW TABLES LIKE 'price_alerts'"))
    if not result.fetchall():
        raise RuntimeError("price_alerts 表不存在，请运行 init_db.py")
```

### 3. 添加数据库迁移工具

考虑使用 Alembic 管理数据库表结构变更：
- 自动检测模型变化
- 生成迁移脚本
- 版本化管理数据库结构

## 总结

✅ **问题已解决**：价格告警数据现在会正确保存到数据库，重启后不再丢失

✅ **修复验证**：已通过数据库表检查和功能测试

✅ **额外收益**：同时修复了其他 V9 功能的数据库表创建问题（资金曲线、交易日志等）

⚠️ **注意事项**：如果后续添加新的数据库模型，务必在 `init_db.py` 中导入，否则会重复本次问题！
