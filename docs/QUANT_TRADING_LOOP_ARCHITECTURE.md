# 量化交易闭环系统 - 架构设计文档

## 系统概述

本系统实现了一个完整的量化交易闭环,从研究到交易,持续评估反馈,自我进化优化。这是一个从华尔街顶级量化交易团队视角设计的专业级个人量化交易系统。

## 核心架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    量化交易闭环系统                                    │
│                  Quantitative Trading Loop                           │
└─────────────────────────────────────────────────────────────────────┘

         ┌──────────────────────────────────────┐
         │   1. Research & Strategy             │
         │   策略运行 → 研究结果                  │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │   2. Signal Generation                │
         │   信号引擎 → 交易信号                  │
         │   SignalEngine                        │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │   3. Signal Validation                │
         │   风险检查 → 信号验证                  │
         │   Risk Check & Validation             │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │   4. Order Execution                  │
         │   订单执行 → 实际交易                  │
         │   OrderExecutor                       │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │   5. Performance Monitoring           │
         │   持续监控 → 交易表现                  │
         │   Real-time Tracking                  │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │   6. Performance Evaluation           │
         │   性能评估 → 策略效果                  │
         │   PerformanceAnalyzer                 │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │   7. Feedback & Learning              │
         │   识别模式 → 改进机会                  │
         │   Pattern Recognition                 │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │   8. Adaptive Optimization            │
         │   自动优化 → 参数调整                  │
         │   AdaptiveOptimizer                   │
         └──────────┬───────────────────────────┘
                    │
                    └─────► 循环回到 1 (自我进化)
```

## 核心组件

### 1. SignalEngine (信号引擎)
**文件**: `backend/app/engine/signal_engine.py`

**功能**:
- 从策略运行结果生成交易信号
- 统一信号格式和评分体系
- 信号验证和风险过滤
- 信号生命周期管理
- 信号性能统计

**关键方法**:
- `generate_signals_from_strategy_run()` - 从策略结果生成信号
- `validate_signal()` - 验证信号(风险检查)
- `get_pending_signals()` - 获取待执行信号
- `update_signal_execution()` - 更新执行状态
- `evaluate_signal_performance()` - 评估信号表现

### 2. OrderExecutor (订单执行引擎)
**文件**: `backend/app/engine/order_executor.py`

**功能**:
- 自动执行已验证的交易信号
- 批量订单执行管理
- 订单状态监控
- 执行质量跟踪
- 支持干运行模式(DRY_RUN)

**关键方法**:
- `execute_signal_batch()` - 批量执行信号
- `_execute_single_signal()` - 执行单个信号
- `_calculate_order_params()` - 计算订单参数
- `monitor_order_status()` - 监控订单状态
- `cancel_signal()` - 取消信号

### 3. PerformanceAnalyzer (性能分析器)
**文件**: `backend/app/engine/performance_analyzer.py`

**功能**:
- 每日性能评估
- 策略效果分析
- 识别成功/失败模式
- 生成性能报告
- 改进机会识别

**关键方法**:
- `evaluate_daily_performance()` - 每日性能评估
- `generate_strategy_report()` - 生成策略报告
- `identify_improvement_opportunities()` - 识别改进机会
- `_find_extreme_signals()` - 找出极端表现

### 4. AdaptiveOptimizer (自适应优化器)
**文件**: `backend/app/engine/adaptive_optimizer.py`

**功能**:
- 信号阈值优化
- 策略权重动态分配
- 风险参数自适应调整
- 仓位大小优化(Kelly Criterion)
- 参数网格搜索

**关键方法**:
- `run_daily_optimization()` - 每日优化流程
- `_optimize_signal_thresholds()` - 优化信号阈值
- `_optimize_strategy_weights()` - 优化策略权重
- `_optimize_risk_parameters()` - 优化风险参数
- `_optimize_position_sizing()` - 优化仓位大小

### 5. QuantTradingLoop (闭环协调器)
**文件**: `backend/app/engine/quant_trading_loop.py`

**功能**:
- 整合所有组件
- 编排完整闭环流程
- 周期性执行管理
- 系统状态监控

**关键方法**:
- `run_full_cycle()` - 运行完整周期
- `run_strategy_research_cycle()` - 单策略研究周期
- `get_loop_status()` - 获取系统状态

## 数据模型

### TradingSignal (交易信号)
**文件**: `backend/app/models/trading_signal.py`

**核心字段**:
- 信号基本信息: signal_id, signal_type, signal_source, status
- 交易标的: symbol, direction
- 信号质量: signal_strength, confidence, expected_return, risk_score
- 交易参数: suggested_quantity, suggested_price, stop_loss, take_profit
- 执行追踪: order_id, executed_price, execution_slippage
- 评估结果: actual_return, pnl, evaluation_score

**信号状态流转**:
```
GENERATED → VALIDATED → QUEUED → EXECUTING → EXECUTED
            ↓
         REJECTED / EXPIRED / CANCELLED / FAILED
```

### SignalPerformance (信号性能统计)
**功能**: 用于反馈优化的性能统计

**核心指标**:
- 胜率、平均收益、夏普比率
- 执行质量(滑点、执行时间)
- 信号质量(置信度、强度)

## API接口

### 闭环控制
**路由**: `backend/app/routers/quant_loop.py`

**核心端点**:
```
POST /api/v1/quant-loop/run-cycle          - 运行完整周期
GET  /api/v1/quant-loop/status             - 获取系统状态
GET  /api/v1/quant-loop/signals/pending    - 获取待执行信号
POST /api/v1/quant-loop/execute-signals    - 批量执行信号
GET  /api/v1/quant-loop/performance/daily  - 每日性能报告
POST /api/v1/quant-loop/optimization/run   - 运行优化
GET  /api/v1/quant-loop/dashboard/overview - 仪表盘概览
```

## 定时任务

**文件**: `backend/app/jobs/quant_loop_jobs.py`

**任务调度**:
```
08:00 - Daily Trading Cycle (信号生成)
18:00 - Performance Evaluation (性能评估)
22:00 - Adaptive Optimization (自动优化)
```

## 使用流程

### 1. 自动化运行(推荐)
系统通过定时任务自动运行,无需人工干预:
- 每日自动生成信号
- 自动评估性能
- 自动优化参数

### 2. 手动触发
通过API手动控制:
```python
# 运行完整周期
POST /api/v1/quant-loop/run-cycle
{
  "execute_trades": false,  # 是否执行交易
  "optimize": true          # 是否运行优化
}

# 执行信号
POST /api/v1/quant-loop/execute-signals
{
  "max_orders": 5,
  "dry_run": true  # 演练模式
}
```

### 3. 监控仪表盘
```python
# 获取系统概览
GET /api/v1/quant-loop/dashboard/overview

# 查看待执行信号
GET /api/v1/quant-loop/signals/pending

# 查看性能报告
GET /api/v1/quant-loop/performance/daily
```

## 风险控制

### 多层风险保护:
1. **信号验证层** - 风险评分过滤
2. **SafetyGuard检查** - 仓位、风险暴露限制
3. **交易模式控制** - OFF/DRY_RUN/LIVE
4. **人工审核机制** - 优化结果需人工确认(auto_apply=false)

### 默认安全配置:
- 信号自动生成和验证 ✅
- 交易默认不自动执行 ⛔ (execute_trades=false)
- 优化结果需人工审核 ⛔ (auto_apply=false)
- 支持演练模式测试 ✅ (dry_run=true)

## 自我进化机制

### 1. 性能反馈
- 持续评估每个信号的表现
- 记录预期vs实际收益
- 计算评估分数(0-100)

### 2. 模式识别
- 过度自信信号识别
- 高风险失败模式
- 执行质量问题

### 3. 自动优化
- 信号阈值动态调整
- 策略权重重新分配
- 风险参数自适应
- 仓位大小优化(Kelly)

### 4. 持续循环
```
数据 → 学习 → 优化 → 改进 → 更好的数据 → ...
```

## 监控指标

### 系统健康度:
- 信号生成速率
- 验证通过率
- 执行成功率
- 平均滑点

### 策略表现:
- 胜率
- 平均收益
- 夏普比率
- 最大回撤

### 优化效果:
- 参数调整频率
- 性能改进趋势
- 建议采纳率

## 下一步扩展

1. **机器学习集成** - 使用ML模型预测信号质量
2. **多账户支持** - 支持多个交易账户
3. **实时流式处理** - WebSocket实时推送
4. **回测引擎** - 策略历史回测
5. **因子库扩展** - 更多量化因子
6. **风险归因分析** - 详细的风险归因

## 总结

这是一个完整的、自动化的、自我进化的量化交易系统,实现了:

✅ **研究到交易的自动化** - 策略结果自动转化为交易信号
✅ **持续性能评估** - 实时追踪和评估每笔交易
✅ **智能反馈循环** - 识别问题和改进机会
✅ **自适应优化** - 基于表现自动调整参数
✅ **人工监督** - 完整的监控报表和人工审核机制
✅ **风险可控** - 多层风险保护,默认安全配置

系统设计借鉴了华尔街顶级量化交易团队的最佳实践,是一个专业级的个人量化交易解决方案。
