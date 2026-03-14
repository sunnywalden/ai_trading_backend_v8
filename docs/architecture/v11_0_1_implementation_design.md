# V11.0.1 实现架构设计文档

> 文档类型：后端系统架构与实现设计  
> 版本：1.0 | 日期：2026-03-14  
> 对应规划：`docs/archived/v11/v11.0/RELEASE_PLAN_V11.0.1.md`

---

## 1. 实现优先级矩阵

| 模块 | 紧迫度 | 代码影响范围 | V10.5.4 问题修复 |
|------|--------|------------|----------------|
| M1.5 Conviction Friction Relief | 🔴 P0 | `signal_quality_funnel.py` + 新服务 | ✅ ORCL 信号反复被拒 |
| M1.5.3 GEA Idle-Capital Check | 🔴 P0 | `gross_exposure_allocator.py` | ✅ no-headroom 双重阻断 |
| M2.3 False-Hold Alert + REDUCE bypass | 🔴 P0 | `position_rebalance_monitor.py` + 新服务 | ✅ ACDC 亏损仓位 |
| M1.1-4 Capital Velocity Score | 🟡 P1 | `capacity_arbiter.py` + 新服务 | 资金效率 |
| M2 Meta-State Snapshot | 🟡 P1 | 新服务 + DB migration | 自感知 |
| M3 Self-Improvement | 🟢 P2 | `insight_service.py` 扩展 | 持续提升 |
| M4 Self-Evolution | 🟢 P2 | `v1051_research_service.py` 扩展 | 自进化 |
| M5 Frontend | 🟡 P1 | Vue 组件升级 | 可视性 |

---

## 2. 数据流架构

```
决策周期（每小时）
│
├── AutonomousEngine._ai_decide()
│   ├── GrossExposureAllocator.allocate_entry()  ← M1.5.3 修改点
│   └── [GEA 结果写入 decision metadata]
│
├── SignalQualityFunnel.evaluate()
│   ├── Layer 0-3 [不变]
│   ├── Layer 4 _layer4_conviction()             ← M1.5.2 修改点
│   │   ├── 查询 ConvictionFrictionTracker       ← M1.5.1 新服务
│   │   └── [软化通过时写 SOFT_THRESHOLD 标签]
│   └── [通过/拒绝 → WritAuditLog]
│
└── PositionRebalanceMonitor.scan()              ← M2.3 修改点
    ├── 生成 REDUCE/EXIT 信号
    ├── 记录 rejection_count per symbol         ← 新逻辑
    └── 触发 FalseHoldDetector                  ← 新逻辑

后台任务（每周期结束）
└── MetaStateSnapshotService.build_snapshot()   ← M2 新服务
    ├── throttled_signals (来自 ConvictionFrictionTracker)
    ├── false_hold_alerts (来自 FalseHoldDetector)
    ├── capital_state
    └── [持久化到 MetaStateSnapshot 表]
```

---

## 3. 新增服务

### 3.1 ConvictionFrictionTracker (`app/services/conviction_friction_tracker.py`)

**职责**：Redis 后端持久化每个 symbol/direction 的置信度摩擦状态

**核心数据结构（Redis Hash）**：
```
key: cv_friction:{symbol}:{direction}:{regime}
fields:
  rejection_count: int         # 连续被拒次数
  last_conviction: float       # 最近一次 conviction 分值
  last_rejected_at: ISO8601    # 最近被拒时间
  threshold_at_rejection: int  # 被拒时的阈值
  soft_relief_used_count: int  # 本周期已用软化次数
  soft_relief_last_used_at: ISO8601
```

**TTL**：24小时（仅跟踪当日摩擦）

**API**：
- `record_rejection(symbol, direction, regime, conviction, threshold)` → 增加计数
- `record_pass(symbol, direction, regime)` → 重置计数
- `get_friction_state(symbol, direction, regime) -> FrictionState`
- `get_all_throttled_signals() -> list[FrictionState]`
- `can_use_soft_relief(symbol, direction, regime, max_per_cycle) -> bool`
- `record_soft_relief_used(symbol, direction, regime)`

### 3.2 MetaStateSnapshotService (`app/services/meta_state_snapshot_service.py`)

**职责**：每个决策周期生成系统元状态快照

**核心输出结构**：
```json
{
  "snapshot_id": "uuid",
  "generated_at": "ISO8601",
  "throttled_signals": [
    {
      "symbol": "ORCL", "direction": "LONG", "regime": "BULL_TREND",
      "rejection_count": 6, "last_conviction": 92.0,
      "friction_gap": 1, "composite_score": 98.0, "resonance_bonus": 90,
      "soft_relief_eligible": true
    }
  ],
  "false_hold_alerts": [
    {
      "symbol": "ACDC", "position_id": "...",
      "current_score": 50, "rejection_count": 4,
      "rejection_stage": "QUALITY_FUNNEL",
      "unrealized_pnl": -9234.5, "unrealized_pnl_pct": -9.36,
      "last_signal_id": "..."
    }
  ],
  "capital_state": {
    "total_equity": 905000,
    "idle_cash": 298000,
    "idle_cash_ratio": 0.329,
    "positions_count": 5,
    "gross_exposure_pct": 0.667
  }
}
```

### 3.3 CapitalVelocityService (`app/services/capital_velocity_service.py`)

**职责**：为每个持仓/候选信号计算 CVS 分值

**CVS 公式实现**：
```
CVS = WinProb × ExpectedNetAlpha × FillConfidence × TimeEfficiency
      - RiskPenalty - FrictionPenalty - CrowdingPenalty + IdleCapitalBonus
```

**注意**：初始实现用简化代理指标，后续迭代替换为精确计算。

---

## 4. 现有服务修改点

### 4.1 `signal_quality_funnel.py` — Layer 4 软化

**修改位置**：`evaluate()` 方法中 Layer 4 执行前

**新增逻辑（伪代码）**：
```python
# 在 _layer4_conviction 调用前
if settings.CAPITAL_VELOCITY_V1101_ENABLED and not is_closing:
    effective_threshold = await _compute_effective_threshold(
        signal, conviction, threshold, idle_cash_ratio
    )
else:
    effective_threshold = threshold

reject = self._layer4_conviction(conviction, cfg, effective_threshold)
```

**私有方法 `_compute_effective_threshold`**：
1. 查询 `ConvictionFrictionTracker` 获取摩擦状态
2. 若摩擦条件满足（连续被拒 ≥ N + idle_cash_ratio > 0.25 + composite ≥ 96 + resonance ≥ 80）
3. 计算 soft_relief，更新 effective_threshold
4. 写入 signal metadata `soft_threshold_applied=True`

### 4.2 `gross_exposure_allocator.py` — no-headroom 分支修改

**修改位置**：第 271 行 `if remaining_cap_pct <= 0 or max_additional_symbol_pct <= 0:` 分支

**新增逻辑**：
```python
# 检查是否满足闲置资本感知条件
if settings.CAPITAL_VELOCITY_V1101_ENABLED:
    idle_cash_ratio = _get_idle_cash_ratio_from_context()
    if (idle_cash_ratio > settings.IDLE_CAPITAL_ALERT_THRESHOLD
            and base_pct <= idle_cash_ratio * settings.IDLE_CAPITAL_GEA_HEADROOM_FACTOR):
        # 临时上调 effective_max
        effective_max = current_gross_pct + min(idle_cash_ratio, settings.IDLE_CAPITAL_GEA_MAX_BORROW)
        effective_remaining_cap = max(0.0, effective_max - current_gross_pct)
        # 重跑分配逻辑（带 idle_capital_adjusted=True 标记）
        ...
```

**问题**：`allocate_entry()` 当前没有 `idle_cash_ratio` 参数，需要添加可选参数。

### 4.3 `position_rebalance_monitor.py` — False-Hold 检测

**修改位置**：`scan()` 主循环，在创建信号后追踪 rejection 状态

**新增数据收集（Redis）**：
```
key: false_hold_track:{account_id}:{symbol}
fields:
  reduce_rejection_count: int
  last_rejection_stage: str
  last_rejection_reason: str
  last_signal_id: str
  sequence_start: ISO8601
```

**触发告警**：当 `consecutive_rejected_reduce_signals ≥ FALSE_HOLD_DETECTION_ROUNDS`，
写入 `MetaStateSnapshotService.false_hold_alerts`

---

## 5. 数据模型新增

### 5.1 `MetaStateSnapshot` 表
```sql
CREATE TABLE meta_state_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_id UUID NOT NULL UNIQUE,
    generated_at TIMESTAMP NOT NULL,
    capital_state JSONB,
    throttled_signals JSONB,
    false_hold_alerts JSONB,
    model_state JSONB,
    execution_state JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
-- TTL: 保留90天，通过定时清理
CREATE INDEX idx_meta_state_generated ON meta_state_snapshots(generated_at DESC);
```

### 5.2 `ImprovementCandidate` 表 (M3)
```sql
CREATE TABLE improvement_candidates (
    id SERIAL PRIMARY KEY,
    candidate_id UUID NOT NULL UNIQUE,
    candidate_type VARCHAR(50) NOT NULL,  -- RULE/PARAMETER/SIZING/EXECUTION
    title VARCHAR(200),
    evidence JSONB,
    expected_impact JSONB,
    status VARCHAR(30) DEFAULT 'PENDING',  -- PENDING/SHADOW/ADOPTED/REJECTED
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 6. Feature Flag 注册规范

所有新 V11 flag 遵循：
1. 在 `app/core/config.py` 注册（默认 `False`）
2. 在 `.env.example` 注释
3. 在 `GET /api/v1/autonomy/status` 的 `flags` 字段中暴露

---

## 7. API 契约新增

### 7.1 `GET /api/v1/autonomy/meta-state` (新增)
返回最新 `MetaStateSnapshot`，前端 `/autonomy` 页面专用。

### 7.2 `GET /api/v1/signals/friction-state` (新增)
返回当前 `throttled_signals` 列表，用于 Signal Pipeline 视图。

### 7.3 `GET /api/v1/positions/false-hold-alerts` (新增)
返回当前 `false_hold_alerts` 列表，用于 Portfolio 视图告警。

### 7.4 `GET /api/v1/capital-velocity/scores` (新增)
返回每个持仓的 CVS 分值，用于 Capital Velocity Cockpit。
