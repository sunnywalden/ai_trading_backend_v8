# 交易信号与持仓联动优化方案

## 📋 需求分析

### 1. 信号类型标识优化

**当前状态**：
- ✅ `SignalType` 枚举已定义：ENTRY（开仓）、EXIT（平仓）、ADD（加仓）、REDUCE（减仓）、HEDGE（对冲）
- ✅ `direction` 字段：LONG（做多）、SHORT（做空）
- ❌ 信号生成时全部默认为 `ENTRY` 类型

**优化方案**：
```python
# 信号类型 + 方向 = 明确的交易意图
ENTRY + LONG   → 买入开多仓
ENTRY + SHORT  → 卖出开空仓
EXIT + LONG    → 卖出平多仓
EXIT + SHORT   → 买入平空仓
ADD + LONG     → 加仓（增加多头）
REDUCE + LONG  → 减仓（减少多头）
```

---

## 🔍 2. 信号与持仓联动过滤

### 2.1 过滤规则设计

#### 规则1：开仓类信号（ENTRY）过滤
```python
if signal.signal_type == SignalType.ENTRY:
    current_position = get_position(signal.symbol)
    
    if current_position:
        # 已有持仓，检查是否超量
        if signal.direction == "LONG" and current_position.qty >= signal.suggested_quantity:
            # 持仓数量已满足或超过建议，过滤掉
            filter_reason = f"已有多头持仓 {current_position.qty}，无需再买入"
            signal.status = SignalStatus.EXPIRED
            continue
        
        if signal.direction == "SHORT" and current_position.qty <= -signal.suggested_quantity:
            # 空头持仓已满足，过滤掉
            filter_reason = f"已有空头持仓 {abs(current_position.qty)}，无需再做空"
            signal.status = SignalStatus.EXPIRED
            continue
```

#### 规则2：平仓类信号（EXIT）过滤
```python
if signal.signal_type == SignalType.EXIT:
    current_position = get_position(signal.symbol)
    
    if not current_position or current_position.qty == 0:
        # 没有持仓，无法平仓
        filter_reason = f"当前无 {signal.symbol} 持仓，无需平仓"
        signal.status = SignalStatus.EXPIRED
        continue
    
    if signal.direction == "LONG" and current_position.qty <= 0:
        # 想平多仓但实际是空仓
        filter_reason = "当前持有空仓，无法平多仓"
        signal.status = SignalStatus.EXPIRED
        continue
    
    if signal.direction == "SHORT" and current_position.qty >= 0:
        # 想平空仓但实际是多仓
        filter_reason = "当前持有多仓，无法平空仓"
        signal.status = SignalStatus.EXPIRED
        continue
```

#### 规则3：加仓/减仓信号（ADD/REDUCE）过滤
```python
if signal.signal_type == SignalType.ADD:
    current_position = get_position(signal.symbol)
    
    if not current_position:
        # 没有基础仓位，无法加仓 → 转换为开仓信号
        signal.signal_type = SignalType.ENTRY
        logger.info(f"无持仓，ADD信号转为ENTRY: {signal.symbol}")
    
    # 检查是否加仓后超过风险限额
    if position_risk_check(current_position, signal.suggested_quantity):
        filter_reason = "加仓后将超过单标的持仓上限"
        signal.status = SignalStatus.REJECTED
        continue

if signal.signal_type == SignalType.REDUCE:
    current_position = get_position(signal.symbol)
    
    if not current_position:
        filter_reason = "无持仓，无法减仓"
        signal.status = SignalStatus.EXPIRED
        continue
    
    if abs(current_position.qty) < signal.suggested_quantity:
        # 减仓数量超过当前持仓，调整为全部平仓
        signal.signal_type = SignalType.EXIT
        signal.suggested_quantity = abs(current_position.qty)
        logger.info(f"减仓数量超过持仓，转为EXIT: {signal.symbol}")
```

---

## 🏗️ 3. 架构设计

### 3.1 新增服务：SignalPositionFilter

```python
# backend/app/engine/signal_position_filter.py

class SignalPositionFilter:
    """信号与持仓联动过滤器"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.broker = make_option_broker_client()
        self.account_svc = AccountService(session)
    
    async def filter_signals_with_positions(
        self,
        signals: List[TradingSignal],
        account_id: str
    ) -> List[TradingSignal]:
        """
        根据当前持仓过滤信号
        
        Returns:
            - filtered_signals: 过滤后的有效信号列表
            - filter_summary: 过滤统计
        """
        # 1. 获取当前所有持仓
        positions = await self._get_current_positions(account_id)
        position_map = {p.symbol: p for p in positions}
        
        # 2. 逐个过滤信号
        filtered_signals = []
        filter_stats = {
            "total": len(signals),
            "filtered_out": 0,
            "passed": 0,
            "reasons": defaultdict(int)
        }
        
        for signal in signals:
            filter_result = await self._filter_single_signal(signal, position_map)
            
            if filter_result.passed:
                filtered_signals.append(signal)
                filter_stats["passed"] += 1
            else:
                filter_stats["filtered_out"] += 1
                filter_stats["reasons"][filter_result.reason] += 1
                
                # 更新信号状态
                signal.status = SignalStatus.EXPIRED
                if not signal.extra_metadata:
                    signal.extra_metadata = {}
                signal.extra_metadata["filter_reason"] = filter_result.reason
                signal.extra_metadata["filtered_at"] = datetime.utcnow().isoformat()
        
        await self.session.commit()
        
        return filtered_signals, filter_stats
    
    async def _filter_single_signal(
        self, 
        signal: TradingSignal, 
        position_map: Dict[str, Position]
    ) -> FilterResult:
        """单个信号过滤逻辑"""
        
        current_position = position_map.get(signal.symbol)
        
        # 开仓信号过滤
        if signal.signal_type == SignalType.ENTRY:
            return self._filter_entry_signal(signal, current_position)
        
        # 平仓信号过滤
        elif signal.signal_type == SignalType.EXIT:
            return self._filter_exit_signal(signal, current_position)
        
        # 加仓信号过滤
        elif signal.signal_type == SignalType.ADD:
            return self._filter_add_signal(signal, current_position)
        
        # 减仓信号过滤
        elif signal.signal_type == SignalType.REDUCE:
            return self._filter_reduce_signal(signal, current_position)
        
        # 默认通过
        return FilterResult(passed=True)
    
    def _filter_entry_signal(
        self, 
        signal: TradingSignal, 
        current_position: Optional[Position]
    ) -> FilterResult:
        """开仓信号过滤"""
        
        if not current_position:
            return FilterResult(passed=True)
        
        # 多头开仓：检查是否已有足够多头
        if signal.direction == "LONG":
            if current_position.qty >= signal.suggested_quantity:
                return FilterResult(
                    passed=False,
                    reason=f"已有多头持仓 {current_position.qty}，大于建议数量 {signal.suggested_quantity}"
                )
        
        # 空头开仓：检查是否已有足够空头
        elif signal.direction == "SHORT":
            if current_position.qty <= -signal.suggested_quantity:
                return FilterResult(
                    passed=False,
                    reason=f"已有空头持仓 {abs(current_position.qty)}，大于建议数量 {signal.suggested_quantity}"
                )
        
        return FilterResult(passed=True)
    
    def _filter_exit_signal(
        self, 
        signal: TradingSignal, 
        current_position: Optional[Position]
    ) -> FilterResult:
        """平仓信号过滤"""
        
        # 无持仓，无法平仓
        if not current_position or current_position.qty == 0:
            return FilterResult(
                passed=False,
                reason=f"当前无 {signal.symbol} 持仓，无需平仓"
            )
        
        # 检查持仓方向与平仓方向是否匹配
        if signal.direction == "LONG" and current_position.qty <= 0:
            return FilterResult(
                passed=False,
                reason="当前持有空仓，无法平多仓"
            )
        
        if signal.direction == "SHORT" and current_position.qty >= 0:
            return FilterResult(
                passed=False,
                reason="当前持有多仓，无法平空仓"
            )
        
        return FilterResult(passed=True)
```

### 3.2 集成到 Quant Loop API

```python
# backend/app/routers/quant_loop.py

@router.get("/signals/pending")
async def get_pending_signals(
    account_id: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    filter_by_position: bool = Query(True, description="是否根据持仓过滤信号"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """获取待执行的信号列表（支持持仓过滤）"""
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    signal_engine = SignalEngine(session)
    signals = await signal_engine.get_pending_signals(
        account_id=account_id,
        limit=limit
    )
    
    # 🔍 新增：根据持仓过滤信号
    if filter_by_position and signals:
        signal_filter = SignalPositionFilter(session)
        signals, filter_stats = await signal_filter.filter_signals_with_positions(
            signals, 
            account_id
        )
        
        # 在响应中添加过滤统计
        response_data = {
            "success": True,
            "data": [signal_to_dict(s) for s in signals],
            "total": len(signals),
            "filter_stats": filter_stats if filter_by_position else None
        }
        return response_data
    
    # 原逻辑保持不变
    return {
        "success": True,
        "data": [signal_to_dict(s) for s in signals],
        "total": len(signals)
    }
```

---

## 🎯 4. 其他优化方向

### 4.1 信号智能类型推断

**场景**：策略生成信号时自动判断信号类型

```python
def infer_signal_type(
    symbol: str, 
    direction: str, 
    current_position: Optional[Position]
) -> SignalType:
    """根据当前持仓智能推断信号类型"""
    
    if not current_position or current_position.qty == 0:
        # 无持仓 → 开仓信号
        return SignalType.ENTRY
    
    if direction == "LONG" and current_position.qty > 0:
        # 已有多头，继续做多 → 加仓
        return SignalType.ADD
    
    if direction == "SHORT" and current_position.qty < 0:
        # 已有空头，继续做空 → 加仓
        return SignalType.ADD
    
    if direction == "LONG" and current_position.qty < 0:
        # 有空头，要做多 → 平空仓
        return SignalType.EXIT
    
    if direction == "SHORT" and current_position.qty > 0:
        # 有多头，要做空 → 平多仓
        return SignalType.EXIT
    
    return SignalType.ENTRY
```

### 4.2 仓位管理规则增强

```python
class PositionManagerRules:
    """仓位管理规则"""
    
    MAX_POSITION_PER_SYMBOL = 0.15  # 单标的最大仓位：总资金的15%
    MAX_SECTOR_EXPOSURE = 0.30      # 单行业最大敞口：30%
    MAX_TOTAL_LEVERAGE = 2.0        # 最大杠杆：2倍
    
    @staticmethod
    def check_position_limit(
        symbol: str,
        suggested_qty: float,
        current_qty: float,
        account_equity: float
    ) -> Tuple[bool, str]:
        """检查仓位限制"""
        
        new_qty = current_qty + suggested_qty
        position_value = new_qty * get_market_price(symbol)
        position_ratio = position_value / account_equity
        
        if position_ratio > MAX_POSITION_PER_SYMBOL:
            return False, f"超过单标的仓位限制 {MAX_POSITION_PER_SYMBOL*100}%"
        
        return True, ""
    
    @staticmethod
    def check_sector_exposure(
        symbol: str,
        suggested_qty: float,
        current_positions: List[Position],
        account_equity: float
    ) -> Tuple[bool, str]:
        """检查行业敞口"""
        
        sector = get_symbol_sector(symbol)
        sector_positions = [p for p in current_positions if get_symbol_sector(p.symbol) == sector]
        
        sector_value = sum(p.market_value for p in sector_positions)
        new_value = suggested_qty * get_market_price(symbol)
        total_sector_value = sector_value + new_value
        
        sector_ratio = total_sector_value / account_equity
        
        if sector_ratio > MAX_SECTOR_EXPOSURE:
            return False, f"超过{sector}行业敞口限制 {MAX_SECTOR_EXPOSURE*100}%"
        
        return True, ""
```

### 4.3 信号优先级动态调整

```python
def adjust_signal_priority_by_position(
    signal: TradingSignal, 
    current_position: Optional[Position]
) -> TradingSignal:
    """根据持仓情况调整信号优先级"""
    
    original_priority = signal.priority
    
    # 平仓信号优先级提升（止损止盈）
    if signal.signal_type == SignalType.EXIT:
        if current_position and is_stop_loss_triggered(current_position):
            signal.priority = min(100, original_priority + 30)
            signal.extra_metadata["priority_boost"] = "止损触发"
        
        elif current_position and is_take_profit_triggered(current_position):
            signal.priority = min(100, original_priority + 20)
            signal.extra_metadata["priority_boost"] = "止盈触发"
    
    # 加仓信号：如果当前仓位盈利，降低优先级
    if signal.signal_type == SignalType.ADD:
        if current_position and current_position.unrealized_pnl > 0:
            signal.priority = max(0, original_priority - 10)
            signal.extra_metadata["priority_adjust"] = "已有盈利持仓"
    
    # 开仓信号：如果同行业已有大量持仓，降低优先级
    if signal.signal_type == SignalType.ENTRY:
        sector_exposure = get_sector_exposure(signal.symbol)
        if sector_exposure > 0.20:
            signal.priority = max(0, original_priority - 15)
            signal.extra_metadata["priority_adjust"] = f"{get_symbol_sector(signal.symbol)}行业敞口过高"
    
    return signal
```

### 4.4 信号聚合优化

```python
def aggregate_conflicting_signals(
    signals: List[TradingSignal]
) -> List[TradingSignal]:
    """聚合冲突信号"""
    
    # 按标的分组
    symbol_signals = defaultdict(list)
    for signal in signals:
        symbol_signals[signal.symbol].append(signal)
    
    aggregated_signals = []
    
    for symbol, symbol_signal_list in symbol_signals.items():
        # 如果同一标的有多个信号，取最强的
        if len(symbol_signal_list) > 1:
            # 优先级：EXIT > REDUCE > ADD > ENTRY
            priority_order = {
                SignalType.EXIT: 1,
                SignalType.REDUCE: 2,
                SignalType.ADD: 3,
                SignalType.ENTRY: 4
            }
            
            sorted_signals = sorted(
                symbol_signal_list,
                key=lambda s: (priority_order.get(s.signal_type, 99), -s.signal_strength)
            )
            
            best_signal = sorted_signals[0]
            best_signal.extra_metadata["aggregated_count"] = len(symbol_signal_list)
            aggregated_signals.append(best_signal)
        else:
            aggregated_signals.append(symbol_signal_list[0])
    
    return aggregated_signals
```

### 4.5 前端展示优化

**在PendingSignalsTable中添加信号类型和持仓状态**：

```vue
<td>
  <span :class="['signal-type-badge', getSignalTypeClass(signal.signal_type)]">
    {{ formatSignalType(signal.signal_type) }}
  </span>
</td>

<td>
  <div class="position-status">
    <span v-if="signal.current_position" class="has-position">
      当前持仓: {{ signal.current_position.qty }}
    </span>
    <span v-else class="no-position">无持仓</span>
  </div>
</td>
```

---

## 📊 5. 实施优先级

### P0 - 立即实施
1. ✅ **信号类型正确赋值**：修改 `signal_engine.py` 的信号生成逻辑
2. ✅ **基础过滤规则**：实现 ENTRY 和 EXIT 信号的持仓过滤

### P1 - 近期实施（1-2周）
3. **完整过滤服务**：实现 `SignalPositionFilter` 类
4. **API集成**：在 `/signals/pending` 中添加 `filter_by_position` 参数
5. **前端展示**：显示信号类型和持仓状态

### P2 - 中期优化（1个月）
6. **智能类型推断**：根据持仓自动判断信号类型
7. **仓位管理规则**：集成仓位限制检查
8. **信号优先级调整**：根据持仓动态调整优先级

### P3 - 长期优化（3-6个月）
9. **多策略协调**：处理多个策略产生的冲突信号
10. **风险预算分配**：根据持仓情况动态调整风险预算
11. **性能监控**：追踪过滤规则对策略表现的影响

---

## 🔧 6. 配置化管理

```python
# backend/app/core/config.py

class QuantLoopConfig:
    """量化闭环配置"""
    
    # 信号过滤配置
    ENABLE_POSITION_FILTER = True
    FILTER_ENTRY_WITH_POSITION = True
    FILTER_EXIT_WITHOUT_POSITION = True
    FILTER_ADD_WITHOUT_POSITION = True
    
    # 仓位管理配置
    MAX_POSITION_PER_SYMBOL = 0.15
    MAX_SECTOR_EXPOSURE = 0.30
    MAX_TOTAL_LEVERAGE = 2.0
    
    # 信号优先级配置
    PRIORITY_BOOST_STOP_LOSS = 30
    PRIORITY_BOOST_TAKE_PROFIT = 20
    PRIORITY_REDUCE_SECTOR_OVERWEIGHT = 15
```

---

## 📈 7. 预期效果

### 量化指标
- **信号有效性提升**：30-40%（通过过滤无法执行的信号）
- **资金利用率提升**：20-30%（避免重复开仓）
- **风险控制加强**：减少单标的/行业过度集中
- **执行效率提升**：减少无效信号处理时间

### 用户体验
- ✅ 待执行信号列表更精准，无需人工筛选
- ✅ 清晰显示信号类型和当前持仓状态
- ✅ 自动过滤冲突或无效信号
- ✅ 提供详细的过滤原因说明

---

## 🚀 8. 快速实施指南

### Step 1: 修改信号生成逻辑（5分钟）
```bash
# 编辑 backend/app/engine/signal_engine.py
# 在 _create_signal_from_asset 中添加智能类型推断
```

### Step 2: 实现基础过滤器（30分钟）
```bash
# 创建 backend/app/engine/signal_position_filter.py
# 实现 SignalPositionFilter 类
```

### Step 3: API集成（15分钟）
```bash
# 编辑 backend/app/routers/quant_loop.py
# 在 get_pending_signals 中调用过滤器
```

### Step 4: 前端显示优化（20分钟）
```bash
# 编辑 src/components/quant-loop/PendingSignalsTable.vue
# 添加信号类型和持仓状态列
```

### Step 5: 测试验证（30分钟）
```bash
# 运行单元测试
pytest tests/test_signal_position_filter.py

# 集成测试
# 1. 有持仓时生成ENTRY信号 → 应被过滤
# 2. 无持仓时生成EXIT信号 → 应被过滤
# 3. 有持仓时生成EXIT信号 → 应通过
```

---

## 📝 总结

通过实施信号与持仓联动优化，我们可以：

1. **提升信号质量**：自动过滤无法执行或不合理的信号
2. **加强风险管理**：避免单标的/行业过度集中
3. **优化资金使用**：避免重复开仓，提高资金利用率
4. **改善用户体验**：减少人工筛选工作，提高执行效率

建议按照 P0 → P1 → P2 → P3 的优先级逐步实施，先解决最核心的开仓/平仓过滤问题，再逐步完善高级功能。
