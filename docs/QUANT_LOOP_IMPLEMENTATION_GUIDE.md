# 量化交易闭环系统 - 实施指南

## 快速开始

### 1. 数据库准备

系统需要新的数据表,运行以下SQL或使用ORM自动创建:

```bash
# 使用init_db脚本创建表
cd /Users/admin/IdeaProjects/ai_trading_backend_v8/backend
python init_db.py
```

核心表:
- `trading_signals` - 交易信号表
- `signal_performance` - 信号性能统计表

### 2. 启动系统

```bash
# 激活虚拟环境
source /Users/admin/IdeaProjects/ai_trading_backend_v8/.venv/bin/activate

# 启动后端服务
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

系统启动时会自动:
- ✅ 加载量化交易闭环模块
- ✅ 注册定时任务(08:00, 18:00, 22:00)
- ✅ 初始化所有引擎

### 3. 验证安装

访问 API 文档:
```
http://localhost:8088/docs
```

查找 "Quantitative Trading Loop" 标签,应该看到以下端点:
- `POST /api/v1/quant-loop/run-cycle`
- `GET /api/v1/quant-loop/status`
- `GET /api/v1/quant-loop/dashboard/overview`
- 等等...

### 4. 首次运行

#### 方式1: 通过API手动触发

```bash
# 运行完整周期(不执行交易,仅生成信号和优化)
curl -X POST "http://localhost:8088/api/v1/quant-loop/run-cycle" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "execute_trades": false,
    "optimize": true
  }'
```

#### 方式2: 通过Python脚本

```python
import asyncio
from app.models.db import SessionLocal
from app.engine.quant_trading_loop import QuantTradingLoop
from app.core.config import settings

async def test_run():
    async with SessionLocal() as session:
        loop = QuantTradingLoop(session)
        
        results = await loop.run_full_cycle(
            account_id=settings.TIGER_ACCOUNT,
            execute_trades=False,
            optimize=True
        )
        
        print("Cycle Results:", results)

asyncio.run(test_run())
```

## 使用场景

### 场景1: 每日自动化运行(推荐)

系统已配置定时任务,每日自动运行:
- **08:00** - 生成交易信号
- **18:00** - 评估当日表现  
- **22:00** - 自动优化参数

无需人工干预,系统自动完成研究→信号→评估→优化的完整循环。

### 场景2: 手动触发策略研究

当你有新策略或想测试特定策略时:

```bash
curl -X POST "http://localhost:8088/api/v1/quant-loop/strategy/{strategy_id}/research-cycle" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

这会:
1. 运行策略
2. 生成信号
3. 验证信号
4. 返回top signals

### 场景3: 监控和审核

查看待执行的信号:
```bash
curl "http://localhost:8088/api/v1/quant-loop/signals/pending" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

查看仪表盘:
```bash
curl "http://localhost:8088/api/v1/quant-loop/dashboard/overview" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 场景4: 手动执行优质信号

当你审核后确认要执行某些信号:

```bash
# 执行前3个最优信号(演练模式)
curl -X POST "http://localhost:8088/api/v1/quant-loop/execute-signals" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "max_orders": 3,
    "dry_run": true
  }'
```

### 场景5: 查看优化建议

```bash
curl "http://localhost:8088/api/v1/quant-loop/optimization/opportunities" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

运行优化:
```bash
curl -X POST "http://localhost:8088/api/v1/quant-loop/optimization/run" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "auto_apply": false
  }'
```

## 配置选项

### .env 配置

```bash
# 交易模式
TRADE_MODE=DRY_RUN  # OFF/DRY_RUN/LIVE

# 启用调度器
ENABLE_SCHEDULER=true

# Tiger账户
TIGER_ACCOUNT=your_account_id
```

### 风险参数

在代码中调整:
- 信号强度阈值 (默认60)
- 置信度阈值 (默认0.6)
- 最大单笔仓位 (默认30%)
- Kelly倍数 (默认0.5x)

## 监控指标

### 系统健康度

```bash
GET /api/v1/quant-loop/status
```

返回:
- 信号pipeline状态
- 各阶段信号数量
- 系统运行状态

### 每日性能

```bash
GET /api/v1/quant-loop/performance/daily
```

返回:
- 当日执行信号数
- 每日PnL
- 最佳/最差信号
- 信号质量分析

### 策略表现

```bash
GET /api/v1/quant-loop/performance/strategy/{strategy_id}?days=30
```

返回:
- 胜率、平均收益
- 信号质量
- 性能等级(A+到F)

## 故障排除

### 问题1: 定时任务未运行

检查:
```bash
# 确认ENABLE_SCHEDULER=true
# 查看日志确认任务注册
# 检查时区设置
```

### 问题2: 信号未生成

原因:
- 没有完成的策略运行
- 策略运行结果为空
- 信号阈值过高

解决:
```bash
# 手动触发策略运行
POST /api/v1/strategy/runs

# 降低信号阈值
# 检查策略配置
```

### 问题3: 信号被拒绝

原因:
- 风险检查未通过
- 交易模式为OFF
- 超过风险限制

解决:
```bash
# 检查风险配置
GET /api/v1/ai/state

# 调整交易模式
# 修改风险限制
```

### 问题4: 优化建议为空

原因:
- 历史数据不足(需要至少10个已评估的信号)
- 评估周期过短

解决:
```bash
# 增加lookback天数
GET /api/v1/quant-loop/optimization/opportunities?days=60

# 等待累积更多数据
```

## 安全注意事项

### ⚠️ 默认安全配置

系统默认采用保守配置:
- ✅ 信号自动生成
- ⛔ **交易不自动执行** (execute_trades=false)
- ⛔ **优化需人工审核** (auto_apply=false)
- ✅ 支持演练模式 (dry_run=true)

### 🔒 启用自动交易前必读

如果要启用自动交易执行,需要:

1. **充分测试**: 在DRY_RUN模式运行至少1个月
2. **风险评估**: 确认所有风险参数合理
3. **资金管理**: 设置合理的仓位限制
4. **应急预案**: 准备紧急停止机制
5. **持续监控**: 每日检查执行结果

启用方式:
```python
# 修改定时任务配置
execute_trades=True  # 谨慎!
```

或手动触发:
```bash
POST /api/v1/quant-loop/run-cycle
{
  "execute_trades": true  # 需要非常谨慎!
}
```

### 🛡️ 多层保护

即使启用自动执行,系统仍有多层保护:
1. SafetyGuard风险检查
2. 交易模式控制(OFF/DRY_RUN/LIVE)
3. 仓位和风险限制
4. 信号验证和过滤
5. 审计日志完整记录

## 性能调优

### 信号质量优化

如果发现信号质量不佳:
```bash
# 查看改进机会
GET /api/v1/quant-loop/optimization/opportunities

# 运行优化
POST /api/v1/quant-loop/optimization/run

# 审核优化建议,手动调整参数
```

### 策略权重调整

系统会自动计算最优策略权重:
```bash
GET /api/v1/quant-loop/optimization/run
```

查看 strategy_weight_opt 部分,根据建议调整策略使用频率。

### 仓位大小优化

系统基于Kelly Criterion计算最优仓位:
```bash
# 查看position_size_opt建议
# 考虑采用建议的base_position_size
```

## 下一步

1. **运行首个完整周期** - 熟悉系统流程
2. **监控几天** - 观察信号质量和表现
3. **审核优化建议** - 理解系统学习过程
4. **逐步增加自动化** - 在演练模式充分测试后考虑
5. **持续改进** - 根据反馈调整参数

## 技术支持

系统架构文档: `docs/QUANT_TRADING_LOOP_ARCHITECTURE.md`

核心组件:
- `backend/app/engine/signal_engine.py` - 信号引擎
- `backend/app/engine/order_executor.py` - 执行引擎
- `backend/app/engine/performance_analyzer.py` - 性能分析
- `backend/app/engine/adaptive_optimizer.py` - 自适应优化
- `backend/app/engine/quant_trading_loop.py` - 闭环协调

API路由: `backend/app/routers/quant_loop.py`
定时任务: `backend/app/jobs/quant_loop_jobs.py`

---

**Good Luck Trading! 📈🚀**
