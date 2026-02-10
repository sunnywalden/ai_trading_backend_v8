# 量化交易闭环引擎

本目录包含量化交易闭环系统的核心引擎组件。

## 核心引擎

### 1. SignalEngine - 信号引擎
`signal_engine.py` - 交易信号的生成、验证和管理

**职责**:
- 从策略运行结果生成交易信号
- 信号验证和风险过滤
- 信号优先级排序
- 执行状态追踪
- 性能统计

**关键方法**:
```python
# 从策略运行生成信号
signals = await signal_engine.generate_signals_from_strategy_run(run_id)

# 验证信号
is_valid = await signal_engine.validate_signal(signal_id)

# 获取待执行信号
pending = await signal_engine.get_pending_signals(account_id)

# 评估信号表现
await signal_engine.evaluate_signal_performance(signal_id, actual_return, pnl, holding_days)
```

### 2. OrderExecutor - 订单执行引擎
`order_executor.py` - 自动交易执行

**职责**:
- 批量信号执行
- 订单参数计算
- 执行质量追踪
- Broker集成
- 干运行模式

**关键方法**:
```python
# 批量执行信号
results = await executor.execute_signal_batch(account_id, max_orders=5)

# 监控订单状态
status = await executor.monitor_order_status(order_id)

# 取消信号
cancelled = await executor.cancel_signal(signal_id)
```

### 3. PerformanceAnalyzer - 性能分析器
`performance_analyzer.py` - 交易表现评估

**职责**:
- 每日性能评估
- 策略效果分析
- 失败模式识别
- 改进机会挖掘

**关键方法**:
```python
# 每日性能评估
metrics = await analyzer.evaluate_daily_performance(account_id)

# 策略报告
report = await analyzer.generate_strategy_report(strategy_id, days=30)

# 改进机会
opportunities = await analyzer.identify_improvement_opportunities(account_id)
```

### 4. AdaptiveOptimizer - 自适应优化器
`adaptive_optimizer.py` - 参数自动优化

**职责**:
- 信号阈值优化
- 策略权重分配
- 风险参数调整
- 仓位大小优化

**关键方法**:
```python
# 每日优化
results = await optimizer.run_daily_optimization(account_id)

# 包含四个优化维度:
# - signal_threshold_opt: 信号阈值优化
# - strategy_weight_opt: 策略权重优化
# - risk_param_opt: 风险参数优化
# - position_size_opt: 仓位大小优化
```

### 5. QuantTradingLoop - 闭环协调器
`quant_trading_loop.py` - 完整闭环编排

**职责**:
- 整合所有组件
- 五阶段闭环流程
- 系统状态监控

**关键方法**:
```python
# 运行完整周期
results = await loop.run_full_cycle(
    account_id=account_id,
    execute_trades=False,  # 安全: 默认不执行
    optimize=True
)

# 单策略研究周期
results = await loop.run_strategy_research_cycle(account_id, strategy_id)

# 系统状态
status = await loop.get_loop_status(account_id)
```

## 数据流

```
Strategy Run → SignalEngine → TradingSignal (GENERATED)
                    ↓
              Validation (risk check)
                    ↓
           TradingSignal (VALIDATED)
                    ↓
            OrderExecutor.execute_signal_batch()
                    ↓
           TradingSignal (EXECUTED)
                    ↓
         PerformanceAnalyzer.evaluate_daily_performance()
                    ↓
            Signal Performance Stats
                    ↓
         AdaptiveOptimizer.run_daily_optimization()
                    ↓
         Parameter Adjustments (feedback loop)
```

## 完整闭环流程

```python
from app.engine.quant_trading_loop import QuantTradingLoop

async def run_quant_loop():
    async with SessionLocal() as session:
        loop = QuantTradingLoop(session)
        
        # 运行完整周期
        results = await loop.run_full_cycle(
            account_id="your_account",
            execute_trades=False,  # 先演练
            optimize=True
        )
        
        print("Phase 1 - Signal Generation:", 
              results['phases']['signal_generation'])
        print("Phase 2 - Signal Validation:", 
              results['phases']['signal_validation'])
        print("Phase 3 - Trade Execution:", 
              results['phases']['trade_execution'])
        print("Phase 4 - Performance Evaluation:", 
              results['phases']['performance_evaluation'])
        print("Phase 5 - Adaptive Optimization:", 
              results['phases']['adaptive_optimization'])
```

## 使用示例

### 示例1: 生成并执行信号

```python
from app.engine.signal_engine import SignalEngine
from app.engine.order_executor import OrderExecutor

async def example_signal_to_execution():
    async with SessionLocal() as session:
        signal_engine = SignalEngine(session)
        executor = OrderExecutor(session)
        
        # 1. 从最近的策略运行生成信号
        signals = await signal_engine.generate_signals_from_strategy_run(
            strategy_run_id="run_123",
            max_signals=5
        )
        print(f"Generated {len(signals)} signals")
        
        # 2. 验证信号
        for signal in signals:
            is_valid = await signal_engine.validate_signal(signal.signal_id)
            print(f"Signal {signal.symbol}: {'✅ Valid' if is_valid else '❌ Rejected'}")
        
        # 3. 执行已验证的信号
        results = await executor.execute_signal_batch(
            account_id="account_123",
            max_orders=3,
            trade_mode=TradeMode.DRY_RUN
        )
        print(f"Executed: {results['executed']}, Failed: {results['failed']}")
```

### 示例2: 性能评估和优化

```python
from app.engine.performance_analyzer import PerformanceAnalyzer
from app.engine.adaptive_optimizer import AdaptiveOptimizer

async def example_evaluation_and_optimization():
    async with SessionLocal() as session:
        analyzer = PerformanceAnalyzer(session)
        optimizer = AdaptiveOptimizer(session)
        
        # 1. 评估每日表现
        daily_perf = await analyzer.evaluate_daily_performance("account_123")
        print(f"Today's PnL: ${daily_perf['daily_pnl']:.2f}")
        print(f"Signals executed: {daily_perf['signals_executed']}")
        
        # 2. 生成策略报告
        report = await analyzer.generate_strategy_report("strategy_456", days=30)
        print(f"Strategy win rate: {report['win_rate']:.1%}")
        print(f"Performance grade: {report['performance_grade']}")
        
        # 3. 识别改进机会
        opportunities = await analyzer.identify_improvement_opportunities(
            "account_123", days=30
        )
        for rec in opportunities['recommendations']:
            print(f"💡 {rec['type']}: {rec['message']}")
        
        # 4. 运行优化
        opt_results = await optimizer.run_daily_optimization("account_123")
        for opt in opt_results['optimizations']:
            if opt['status'] == 'OPTIMIZED':
                print(f"✨ {opt['type']} optimized")
```

## 定时任务集成

系统已集成到定时任务系统,每日自动运行:

```python
# backend/app/jobs/quant_loop_jobs.py

08:00 - run_daily_trading_cycle()        # 信号生成
18:00 - run_performance_evaluation()     # 性能评估
22:00 - run_adaptive_optimization()      # 自动优化
```

## 安全注意事项

### ⚠️ 重要提示

1. **默认不自动执行交易**
   - `execute_trades=False` 是默认值
   - 需要显式设置为 `True` 才会执行

2. **使用演练模式测试**
   - `trade_mode=TradeMode.DRY_RUN`
   - 在充分测试后才切换到 LIVE

3. **优化需人工审核**
   - `auto_apply=False` 是默认值
   - 查看优化建议后再决定是否应用

4. **多层风险保护**
   - SafetyGuard检查
   - 风险限制
   - 仓位控制

## 性能优化建议

### 1. 批量操作
```python
# 批量执行信号而非单个执行
results = await executor.execute_signal_batch(account_id, max_orders=5)
```

### 2. 缓存使用
```python
# 信号性能统计已缓存
await cache.get(f"signal_perf:{strategy_id}")
```

### 3. 并发查询
```python
# 异步并发执行多个独立查询
tasks = [
    signal_engine.get_pending_signals(account_id),
    analyzer.evaluate_daily_performance(account_id),
    optimizer.run_daily_optimization(account_id)
]
results = await asyncio.gather(*tasks)
```

## 调试技巧

### 启用详细日志
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 检查信号状态
```python
# 查看信号pipeline
status = await loop.get_loop_status(account_id)
print(status['signal_pipeline'])
```

### 查看执行结果
```python
# 检查执行详情
for result in execution_results['results']:
    if not result['success']:
        print(f"Failed: {result['message']}")
```

## 扩展开发

### 添加新的信号源

```python
# 在SignalEngine中添加新方法
async def generate_signals_from_ai_advice(
    self,
    advice_id: str,
    max_signals: int = 5
) -> List[TradingSignal]:
    # 实现从AI建议生成信号的逻辑
    pass
```

### 添加新的优化维度

```python
# 在AdaptiveOptimizer中添加新方法
async def _optimize_execution_timing(
    self,
    account_id: str,
    lookback_days: int = 30
) -> Dict[str, Any]:
    # 实现执行时机优化逻辑
    pass
```

## 相关文档

- 架构设计: `/docs/QUANT_TRADING_LOOP_ARCHITECTURE.md`
- 实施指南: `/docs/QUANT_LOOP_IMPLEMENTATION_GUIDE.md`
- 重构总结: `/docs/QUANT_REFACTOR_SUMMARY.md`
- API文档: `http://localhost:8088/docs`

## 支持

如有问题或建议,请参考文档或联系开发团队。

**Happy Quant Trading! 📈🚀**
