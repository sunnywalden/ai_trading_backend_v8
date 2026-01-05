# 持仓评估 & 宏观风险分析 - 产品设计文档

## 一、产品概述

### 1.1 目标
在现有行为评分（历史交易）基础上，新增三大核心模块：
- **持仓评估**：实时评估当前持仓标的质量、风险、机会
- **宏观风险分析**：华尔街视角的系统性风险监控
- **潜在机会**：每日自动扫描科技股股票池，输出 1-3 只高分标的

### 1.2 整体架构
```
AI Trading System v8
├── 行为评分模块 (已实现)
│   ├── 基于历史交易数据的行为画像
│   ├── 蝇营狗苟评分 (Sell-Fly Score)
│   ├── 过度交易评分 (Overtrading Score)
│   └── 报复性交易评分 (Revenge Trading Score)
├── 持仓评估模块 (已实现)
│   ├── 持仓标的综合评分 (技术+基本面+情绪)
│   ├── 技术分析 (趋势、RSI、MACD等)
│   ├── 基本面分析 (估值、盈利、成长性)
│   └── 操作建议 (BUY/HOLD/SELL)
├── 宏观风险分析模块 (已实现)
    ├── 货币政策风险 (政策、通胀、利率)
    ├── 地缘政治风险 (冲突、制裁、选举)
    ├── 行业泡沫风险 (估值、情绪、杠杆)
    ├── 经济周期风险 (GDP、PMI、失业率)
    └── 市场情绪风险 (VIX、Put/Call、资金流向)
└── 潜在机会模块 (已实现)
  ├── 动态股票池 (按市值/行业筛选：中大型科技股)
  ├── 三维评分门槛 (技术/基本面/情绪均 ≥ 75)
  ├── 宏观风险融合 (HIGH/EXTREME 时阈值提高到 80)
  ├── 每日定时任务 (北京时间 20:30 自动运行)
  └── 结果落库与回溯 (run 表 + items 表)
```

### 1.3 UI/UX 设计理念

**核心设计原则**：
- **模块化导航**：采用 Vue Router 实现四个独立页面，而非 Tab 页切换
- **全局配置管理**：window_days（时间窗口）作为全局参数，跨页面共享
- **页面级说明指南**：将评分标准和指标说明放在对应页面底部，而非全局侧边栏
- **友好错误提示**：超时、网络错误等异常情况提供中文友好提示
- **深色主题**：专业金融交易风格，减少视觉疲劳

---

## 二、前端架构与实现

### 2.1 技术栈

**核心框架**：
- Vue 3.5.0 (Composition API + TypeScript)
- Vue Router 4.x (路由管理)
- Vite 7.3.0 (构建工具)
- Axios 1.7.0 (HTTP 客户端)

**开发环境**：
- TypeScript 5.7.3
- Node.js (ESM 模式)

### 2.2 页面架构

#### 2.2.1 总体布局
```
┌─────────────────────────────────────────────┐
│ AI Trading · 控制塔                          │
│ ┌─────────┐ ┌───────────────────────────┐  │
│ │ 侧边栏   │ │ 主内容区                   │  │
│ │         │ │ ┌─────────────────────┐   │  │
│ │ 导航菜单 │ │ │ Router View         │   │  │
│ │ 🎯 行为 │ │ │ (页面内容动态切换)   │   │  │
│ │ 📊 持仓 │ │ │                     │   │  │
│ │ 🌍 宏观 │ │ └─────────────────────┘   │  │
│ │ 💡 机会 │ │                           │  │
│ │         │ │                           │  │
│ │         │ │ Footer (版本信息)          │  │
│ └─────────┘ └───────────────────────────┘  │
└─────────────────────────────────────────────┘
```

**布局特点**：
- 左侧固定宽度侧边栏 (260px)
- 导航采用 `<router-link>` 实现页面切换
- 主内容区使用 `<router-view>` 渲染当前路由组件
- 响应式设计：移动端侧边栏自动折叠

#### 2.2.2 路由配置
```typescript
// src/router/index.ts
const routes = [
  {
    path: '/',
    redirect: '/behavior'
  },
  {
    path: '/behavior',
    name: 'BehaviorScore',
    component: () => import('../views/BehaviorScorePage.vue'),
    meta: { title: '行为评分' }
  },
  {
    path: '/positions',
    name: 'Positions',
    component: () => import('../views/PositionsPage.vue'),
    meta: { title: '持仓评估' }
  },
  {
    path: '/macro',
    name: 'MacroRisk',
    component: () => import('../views/MacroRiskPage.vue'),
    meta: { title: '宏观风险' }
  },
  {
    path: '/opportunities',
    name: 'Opportunities',
    component: () => import('../views/OpportunitiesPage.vue'),
    meta: { title: '潜在机会' }
  }
];
```

**路由特性**：
- 懒加载 (Lazy Loading)：按需加载页面组件，优化首屏加载速度
- 元信息 (Meta)：设置页面标题，自动更新浏览器 Tab 标题
- 默认路由：访问根路径自动跳转到行为评分页面
- 过渡动画：路由切换时使用 fade 渐变效果

#### 2.2.3 全局状态管理
```typescript
// src/config/global.ts
export const appConfig = reactive({
  windowDays: 15  // 默认15天时间窗口
});

export function updateWindowDays(days: number) {
  appConfig.windowDays = days;
}
```

**全局配置特点**：
- 使用 Vue 3 Reactive 实现响应式配置
- `windowDays` 参数跨页面共享
- 任何页面修改后，其他页面自动同步

### 2.3 页面详细设计

#### 2.3.1 行为评分页面 (BehaviorScorePage.vue)

**页面功能**：
- 显示基于历史交易的行为画像
- 展示行为评分、蝇营狗苟、过度交易、报复性交易四个维度
- Greeks 风险水位可视化
- 支持窗口天数调整和行为评分重算

**核心组件**：
```
BehaviorScorePage
├── RiskSummaryCard (风险总览卡片)
├── GreeksWaterLevel (Greeks水位图)
├── SymbolBehaviorCard × N (标的行为卡片)
└── BehaviorGuideline (行为评分说明)
```

**交互功能**：
- 窗口天数调整：实时修改 `windowDays` 并重新加载数据
- 重新计算按钮：调用 `/api/v1/behavior/rebuild` 重算行为评分
- 加载状态：显示"正在重算..."提示
- 错误处理：超时显示"⏱️ 请求超时，请稍后再试！"

**数据流**：
```
用户输入 → updateWindowDays() → 全局配置更新 
         → loadAiState() → fetchAiState(windowDays)
         → 后端 API → 更新页面数据
```

#### 2.3.2 持仓评估页面 (PositionsPage.vue)

**页面功能**：
- 展示当前持仓标的的综合评分
- 技术面、基本面、情绪面三维度评分
- 显示持仓市值、盈亏、风险等级
- 提供操作建议 (BUY/HOLD/SELL)

**页面布局**：
```
PositionsPage
├── Header (标题 + 刷新按钮)
├── SummaryBar (汇总信息条)
│   ├── 总持仓数
│   ├── 总市值
│   ├── 总盈亏
│   ├── 平均评分
│   └── 高风险数量
├── PositionScoreCard × N (持仓评分卡片)
└── PositionsGuideline (持仓评估说明)
```

**核心数据展示**：
```typescript
interface Position {
  symbol: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  unrealized_pnl: number;
  overall_score: number;      // 综合评分 0-100
  technical_score: number;    // 技术面 0-100
  fundamental_score: number;  // 基本面 0-100
  sentiment_score: number;    // 情绪面 0-100
  recommendation: string;     // BUY/HOLD/SELL
  risk_level: string;         // LOW/MEDIUM/HIGH/CRITICAL
  ai_advice: string;          // AI建议
}
```

**交互功能**：
- 刷新按钮：调用 `/api/v1/positions/refresh` 更新持仓数据
- 数据加载：显示"正在加载持仓数据..."提示
- 空状态：无持仓时显示"暂无持仓数据"
- 错误处理：网络错误显示"🌐 网络连接失败，请检查网络或后端服务状态"

#### 2.3.3 宏观风险页面 (MacroRiskPage.vue)

**页面功能**：
- 展示五维宏观风险分析
- 货币政策、地缘政治、行业泡沫、经济周期、市场情绪
- 综合风险等级评估
- 关键指标监控

**页面布局**：
```
MacroRiskPage
├── Header (标题 + 刷新按钮)
├── MacroRiskDashboard (五维风险仪表盘)
│   ├── 综合风险评分
│   ├── 货币政策维度
│   ├── 地缘政治维度
│   ├── 行业泡沫维度
│   ├── 经济周期维度
│   └── 市场情绪维度
└── MacroRiskGuideline (宏观风险说明)
```

**核心数据结构**：
```typescript
interface MacroRiskOverview {
  overall_risk: {
    score: number;        // 0-100 (越高越安全)
    level: string;        // LOW/MEDIUM/HIGH/CRITICAL
    summary: string;      // AI总结
  };
  dimensions: {
    monetary_policy: RiskDimension;
    geopolitical: RiskDimension;
    sector_bubble: RiskDimension;
    economic_cycle: RiskDimension;
    market_sentiment: RiskDimension;
  };
}
```

**交互功能**：
- 刷新按钮：调用 `/api/v1/macro/refresh` 更新宏观数据
- 数据加载：显示"正在加载宏观风险数据..."提示
- 错误处理：超时显示"⏱️ 刷新请求超时，请稍后再试！"

#### 2.3.4 潜在机会页面 (OpportunitiesPage.vue)

**页面定位**：
- 把“从持仓里找机会”扩展为“从股票池里找机会”，面向未来建仓/加仓决策
- 核心交付：展示最新一次扫描结果（Top 1-3），并支持手动触发扫描与历史回溯

**核心接口（与后端实现保持一致）**：
- 获取最新：`GET /api/v1/opportunities/latest?universe_name=US_LARGE_MID_TECH`
- 手动扫描：`POST /api/v1/opportunities/scan`（body：`universe_name/min_score/max_results/force_refresh`）
- 历史列表：`GET /api/v1/opportunities/runs?limit=20&universe_name=...`
- 单次详情：`GET /api/v1/opportunities/runs/{run_id}`

**页面布局**：
```
OpportunitiesPage
├── Header (标题 + 扫描按钮 + 参数控件)
├── StatusBar (最新扫描时间 + 宏观风险徽章 + 任务时间提示)
├── OpportunityTopPicks (Top 1-3 推荐卡片)
│   ├── SymbolPill + 价格/涨跌（可选）
│   ├── 三维评分条 (T/F/S) + 综合分
│   ├── 推荐动作 (BUY/STRONG_BUY)
│   └── 关键理由 (reason)
├── RunHistoryPanel (最近 N 次扫描)
│   ├── RunsTable (run_key/as_of/qualified/elapsed)
│   └── RunDetailDrawer (点开查看 items 与宏观快照)
└── OpportunitiesGuideline (机会模块说明)
```

**交互与状态设计**（与已有页面风格一致：按钮 + 加载态 + 友好错误）：

1) **扫描参数区（Header 右侧）**
- `universe_name`：下拉（默认 `US_LARGE_MID_TECH`）
- `min_score`：数字输入（默认 75，范围 0-100）
- `max_results`：数字输入（默认 3，范围 1-10）
- `force_refresh`：开关（默认 false）
  - 文案："强制刷新（可能触发限流，耗时更长）"
  - 交互：开启后给出黄色提示（Warning Banner）

2) **手动扫描按钮（主要 CTA）**
- 点击后调用 `POST /api/v1/opportunities/scan`
- 加载态：按钮进入 loading，主区显示“正在扫描（可能需要 30-90 秒）…”
- 成功态：立即渲染 run 与 items
- 幂等提示：若后端返回 `notes.idempotent=true`，在页面角落提示：
  - “本次请求命中幂等缓存，返回今日已生成结果”

3) **宏观风险融合的 UI 表达（关键要求）**
- 在 `StatusBar` 显示宏观风险徽章（与宏观页风格一致）：
  - `LOW/MEDIUM/HIGH/EXTREME` + `overall_score`
- 当 `risk_level` 为 `HIGH/EXTREME` 时：
  - 显示红/橙色提示条：
    - “宏观风险偏高，本次机会筛选阈值自动提高到 80”
  - 若 `notes.macro_adjustment` 存在，可在 hover/展开中展示 before/after 细节

4) **动态股票池的解释与透明度**
- 在 `OpportunitiesGuideline` 中说明：
  - 股票池为动态生成：从候选集合中按 **市值（中大型）+ 行业（科技/科技相关）**筛选
  - 若发生数据源限流，系统可能使用“科技股兜底清单”保证扫描可用
- 若后端在 `notes.universe.fallback_used=true`（后续前端可直接展示该字段）：
  - UI 显示提示："数据源限流，已使用兜底股票池（结果可能偏保守）"

5) **历史回溯（Runs 列表 + 详情抽屉）**
- RunsTable 列：
  - 时间（as_of）、qualified/total、elapsed_ms、macro risk badge
  - 行为：点击一行打开 Drawer，展示 items 详情
- Drawer 中：
  - “宏观快照”小卡片（risk_level/score/summary）
  - items 列表（Top 1-3 或空）

**空状态与异常状态**：
- 无最新数据：显示空态插画/图标 + “点击‘立即扫描’生成今日机会”
- 限流/网络错误：统一用中文提示：
  - “🌐 网络连接失败，请检查网络或后端服务状态”
  - “⏱️ 扫描超时，请稍后再试（建议关闭强制刷新）”

**推荐卡片视觉规范（保持深色专业交易风格）**：
- 卡片左上：Symbol + 小标签（Universe）
- 右上：综合分圆环或徽章（0-100）
- 中间：三维评分条（颜色从红→黄→绿）
- 底部：reason（最多 2 行，超出省略，点击展开）

### 2.4 页面级说明指南设计

**设计理念**：将评分标准和指标说明从全局侧边栏移至各页面底部，实现上下文相关的帮助信息。

#### 2.4.1 行为评分说明 (BehaviorGuideline.vue)
**内容模块**：
- 行为评分 (0-100) 分级标准 (T1-T4)
- 蝇营狗苟评分说明（追涨杀跌行为）
- 过度交易评分说明（交易频率控制）
- 报复性交易评分说明（情绪化交易）
- Greeks 指标说明（Delta、Gamma、Theta、Vega）
- 操作建议（不同分数段的应对策略）

**布局样式**：
- 横向网格布局 (Grid Layout)
- 响应式设计：自动适配不同屏幕宽度
- 卡片式展示：每个模块独立卡片，易于阅读
- 颜色编码：优秀(绿色)、良好(浅绿)、警惕(橙色)、危险(红色)

#### 2.4.2 持仓评估说明 (PositionsGuideline.vue)
**内容模块**：
- 综合评分说明（技术+基本面+情绪加权）
- 技术面评分详解（趋势、RSI、MACD、布林带等）
- 基本面评分详解（估值、盈利能力、成长性、财务健康）
- 情绪面评分详解（分析师评级、机构持仓、期权数据）
- 操作建议说明（STRONG BUY/BUY/HOLD/SELL/STRONG SELL）
- 风险等级说明（LOW/MEDIUM/HIGH/CRITICAL）

**布局特点**：
- 多列网格展示：充分利用页面宽度
- 评分范围标注：使用彩色标签标注分数区间
- 示例说明：每个维度配有典型指标说明
- 注意事项：底部醒目提示风险警告

#### 2.4.3 宏观风险说明 (MacroRiskGuideline.vue)
**内容模块**：
- 五维风险模型总览
- 政治风险详解（政策变化、地缘冲突、法规监管）
- 经济风险详解（经济增长、通胀压力、利率环境）
- 市场风险详解（波动率、估值水平、流动性）
- 金融风险详解（信用风险、银行健康、杠杆水平）
- 技术风险详解（技术颠覆、创新风险、网络安全）
- 风险应对策略（防御、对冲、分散、时机）
- 关键监测指标（VIX、美债收益率曲线、PMI等）

**布局特点**：
- 分层展示：每个风险维度独立展开
- 风险区间：用颜色区分低/中/高风险
- 策略网格：四宫格展示应对策略
- 指标监控：关键指标阈值一览表

### 2.5 错误处理与用户体验

#### 2.5.1 友好错误提示
**实现逻辑**：
```typescript
try {
  data = await fetchData();
} catch (e: any) {
  if (e.code === 'ECONNABORTED' || e.message?.includes('timeout')) {
    errorMsg.value = '⏱️ 请求超时，请稍后再试！';
  } else if (e.code === 'ERR_NETWORK' || e.message?.includes('Network Error')) {
    errorMsg.value = '🌐 网络连接失败，请检查网络或后端服务状态';
  } else {
    errorMsg.value = '❌ 获取数据失败';
  }
}
```

**错误类型覆盖**：
- ⏱️ **请求超时**：API 调用超过 30 秒
- 🌐 **网络错误**：无法连接后端服务
- ❌ **其他错误**：未知错误的通用提示

**应用场景**：
- 所有页面的数据加载
- 刷新按钮点击
- 重新计算操作

#### 2.5.2 加载状态设计
```vue
<p v-if="loading" class="loading-message">
  正在加载持仓数据...
</p>
<p v-else-if="errorMsg" class="error-message">
  {{ errorMsg }}
</p>
<div v-else-if="data">
  <!-- 正常数据展示 -->
</div>
<p v-else class="info-message">
  暂无数据
</p>
```

**状态优先级**：
1. Loading（加载中）
2. Error（错误）
3. Data（有数据）
4. Empty（无数据）

### 2.6 样式系统

#### 2.6.1 配色方案
```css
/* 主题色 */
--primary: #38bdf8;        /* 天蓝色 - 品牌色 */
--success: #22c55e;        /* 绿色 - 成功/上涨 */
--warning: #f59e0b;        /* 橙色 - 警告 */
--danger: #ef4444;         /* 红色 - 危险/下跌 */

/* 背景色 */
--bg-primary: #020617;     /* 深蓝黑 */
--bg-secondary: #0f172a;   /* 次级背景 */
--bg-card: rgba(15, 23, 42, 0.85);  /* 卡片背景 */

/* 文本色 */
--text-primary: #e5e7eb;   /* 主文本 */
--text-secondary: #9ca3af; /* 次要文本 */
--text-muted: #6b7280;     /* 弱化文本 */

/* 边框色 */
--border-primary: rgba(56, 189, 248, 0.4);
--border-secondary: rgba(55, 65, 81, 0.8);
```

#### 2.6.2 响应式设计
```css
/* 移动端适配 */
@media (max-width: 900px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);  /* 单列布局 */
  }
  .sidebar {
    border-right: none;
    border-bottom: 1px solid rgba(30, 64, 175, 0.6);
  }
}
```

#### 2.6.3 动画效果
```css
/* 路由切换动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 按钮悬停效果 */
.nav-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.8);
}
```

---

## 三、持仓评估模块设计

### 3.1 功能定义

#### 3.1.1 持仓标的评分 (Position Scoring)
**目标**：为每个持仓标的生成综合评分 (0-100)

**评分维度**：
```
综合评分 = 技术面评分 × 40% + 基本面评分 × 40% + 情绪面评分 × 20%

技术面评分 (0-100):
- 趋势强度: MA均线排列、趋势线、动量指标
- 支撑/阻力: 当前价格位置、关键价位距离
- 波动率: ATR、布林带宽度、历史波动率
- 量价关系: 成交量确认、资金流向

基本面评分 (0-100):
- 估值水平: PE、PB、PS、PEG vs 行业均值
- 盈利能力: ROE、毛利率、净利率、营收增长
- 财务健康: 资产负债率、流动比率、现金流
- 成长性: 营收/利润增长率、市场份额变化

情绪面评分 (0-100):
- 市场情绪: 社交媒体热度、分析师评级变化
- 资金流向: 主力资金流入/流出、机构持仓变化
- 期权市场: Put/Call Ratio、隐含波动率
```

#### 3.1.2 技术走势分析 (Technical Analysis)
**输出内容**：
```json
{
  "symbol": "AAPL",
  "technical_analysis": {
    "trend": {
      "direction": "BULLISH",  // BULLISH/BEARISH/SIDEWAYS
      "strength": 75,           // 0-100
      "description": "Strong uptrend with MA50 > MA200 golden cross"
    },
    "indicators": {
      "rsi": {
        "value": 62.5,
        "status": "NEUTRAL",    // OVERSOLD/NEUTRAL/OVERBOUGHT
        "signal": "HOLD"
      },
      "macd": {
        "value": 2.15,
        "signal_line": 1.89,
        "histogram": 0.26,
        "status": "BULLISH_CROSSOVER"
      },
      "bollinger_bands": {
        "upper": 185.50,
        "middle": 180.00,
        "lower": 174.50,
        "current_price": 182.30,
        "position": "MIDDLE_TO_UPPER",
        "width_percentile": 65  // 波动率相对位置
      }
    },
    "support_resistance": {
      "key_support": [175.00, 170.50, 165.00],
      "key_resistance": [185.00, 190.00, 195.00],
      "current_level": "NEAR_SUPPORT"
    },
    "volume_analysis": {
      "avg_volume_20d": 45000000,
      "current_volume": 52000000,
      "volume_trend": "INCREASING",
      "volume_price_divergence": false
    },
    "chart_patterns": [
      {
        "pattern": "CUP_AND_HANDLE",
        "confidence": 0.78,
        "target_price": 195.00,
        "timeframe": "3M"
      }
    ],
    "ai_summary": "技术面偏多，RSI中性区域，MACD金叉确认，建议回调至175支撑位加仓"
  }
}
```

#### 3.1.3 基本面分析 (Fundamental Analysis)
**输出内容**：
```json
{
  "symbol": "AAPL",
  "fundamental_analysis": {
    "valuation": {
      "pe_ratio": 28.5,
      "pe_percentile": 65,     // 历史分位数
      "sector_avg_pe": 25.3,
      "peg_ratio": 1.8,
      "pb_ratio": 42.5,
      "ps_ratio": 7.2,
      "valuation_grade": "B",  // A/B/C/D/F
      "comment": "Slightly expensive vs sector, but justified by quality"
    },
    "profitability": {
      "roe": 0.175,
      "roa": 0.265,
      "gross_margin": 0.438,
      "operating_margin": 0.298,
      "net_margin": 0.253,
      "profitability_grade": "A+"
    },
    "growth": {
      "revenue_growth_yoy": 0.082,      // 8.2%
      "revenue_growth_qoq": 0.045,
      "eps_growth_yoy": 0.115,
      "earnings_surprise_last_4q": [0.03, 0.02, 0.05, 0.04],
      "growth_grade": "A"
    },
    "financial_health": {
      "debt_to_equity": 1.98,
      "current_ratio": 1.07,
      "quick_ratio": 0.95,
      "free_cash_flow": 99800000000,    // USD
      "cash_and_equivalents": 61550000000,
      "health_grade": "A"
    },
    "dividends": {
      "dividend_yield": 0.0048,          // 0.48%
      "payout_ratio": 0.15,
      "dividend_growth_5y": 0.065,       // 6.5% CAGR
      "consecutive_years": 12
    },
    "analyst_ratings": {
      "consensus": "BUY",
      "strong_buy": 18,
      "buy": 12,
      "hold": 5,
      "sell": 1,
      "strong_sell": 0,
      "avg_price_target": 195.50,
      "price_target_range": [165.00, 220.00]
    },
    "ai_summary": "优质科技龙头，盈利能力强，估值合理，现金流健康，建议长期持有"
  }
}
```

### 3.2 数据源设计

#### 3.2.1 技术分析数据源
```python
# 优先级排序
1. Tiger API (已有)
   - 实时行情、历史K线
   - 成交量数据
   
2. yfinance (免费)
   - 日线/周线/月线数据
   - 技术指标计算
   
3. Alpha Vantage (备选)
   - 技术指标 API
   - 分钟级数据
```

#### 3.2.2 基本面数据源
```python
1. Financial Modeling Prep (推荐)
   - 财务报表 API (免费额度500次/天)
   - 估值指标、财务比率
   - 分析师评级
   
2. Yahoo Finance API (yfinance)
   - 基本面数据
   - 分析师目标价
   
3. Tiger API
   - 公司基本信息
   - 财报日期
```

### 3.3 数据库设计

#### 3.3.1 持仓评分表
```sql
CREATE TABLE position_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 综合评分
    overall_score INTEGER,           -- 0-100
    technical_score INTEGER,         -- 0-100
    fundamental_score INTEGER,       -- 0-100
    sentiment_score INTEGER,         -- 0-100
    
    -- 技术面详情
    trend_direction TEXT,            -- BULLISH/BEARISH/SIDEWAYS
    trend_strength INTEGER,
    rsi_value REAL,
    rsi_status TEXT,
    macd_signal TEXT,
    
    -- 基本面详情
    pe_ratio REAL,
    peg_ratio REAL,
    roe REAL,
    revenue_growth_yoy REAL,
    valuation_grade TEXT,
    profitability_grade TEXT,
    
    -- AI总结
    technical_summary TEXT,
    fundamental_summary TEXT,
    recommendation TEXT,             -- BUY/HOLD/SELL
    
    UNIQUE(account_id, symbol, date(timestamp))
);
```

#### 3.3.2 技术分析缓存表
```sql
CREATE TABLE technical_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    timeframe TEXT,                  -- 1D/1W/1M
    
    -- 价格数据
    close_price REAL,
    volume BIGINT,
    
    -- 移动平均线
    ma_5 REAL,
    ma_10 REAL,
    ma_20 REAL,
    ma_50 REAL,
    ma_200 REAL,
    
    -- 动量指标
    rsi_14 REAL,
    macd REAL,
    macd_signal REAL,
    macd_histogram REAL,
    
    -- 波动率
    atr_14 REAL,
    bb_upper REAL,
    bb_middle REAL,
    bb_lower REAL,
    
    -- 成交量
    volume_sma_20 BIGINT,
    obv BIGINT,                      -- On-Balance Volume
    
    UNIQUE(symbol, timestamp, timeframe)
);
```

#### 3.3.3 基本面数据表
```sql
CREATE TABLE fundamental_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    fiscal_date DATE NOT NULL,
    data_type TEXT,                  -- QUARTERLY/ANNUAL
    
    -- 估值
    market_cap BIGINT,
    pe_ratio REAL,
    pb_ratio REAL,
    ps_ratio REAL,
    peg_ratio REAL,
    
    -- 盈利能力
    revenue BIGINT,
    net_income BIGINT,
    eps REAL,
    roe REAL,
    roa REAL,
    gross_margin REAL,
    operating_margin REAL,
    net_margin REAL,
    
    -- 增长
    revenue_growth_yoy REAL,
    eps_growth_yoy REAL,
    
    -- 财务健康
    total_assets BIGINT,
    total_debt BIGINT,
    cash_and_equivalents BIGINT,
    free_cash_flow BIGINT,
    debt_to_equity REAL,
    current_ratio REAL,
    
    UNIQUE(symbol, fiscal_date, data_type)
);
```

### 3.4 API 设计

#### 3.4.1 获取持仓评估
```http
GET /positions/assessment?window_days=7

Response:
{
  "account_id": "8606682",
  "timestamp": "2025-12-31T10:30:00Z",
  "total_score": 78,
  "positions": [
    {
      "symbol": "AAPL",
      "quantity": 100,
      "avg_cost": 175.50,
      "current_price": 182.30,
      "unrealized_pnl": 680.00,
      "pnl_pct": 0.0387,
      "weight": 0.35,                    // 占总仓位35%
      
      "scores": {
        "overall": 82,
        "technical": 78,
        "fundamental": 88,
        "sentiment": 75
      },
      
      "recommendation": {
        "action": "HOLD",                // BUY/HOLD/REDUCE/SELL
        "confidence": 0.85,
        "reason": "Strong fundamentals, overbought technically",
        "target_weight": 0.30,           // 建议降至30%
        "stop_loss": 175.00,
        "take_profit": 195.00
      },
      
      "risk_alerts": [
        {
          "level": "MEDIUM",
          "type": "CONCENTRATION",
          "message": "Position exceeds 30% portfolio weight"
        }
      ]
    }
  ],
  
  "portfolio_summary": {
    "avg_technical_score": 76,
    "avg_fundamental_score": 84,
    "diversification_score": 65,
    "concentration_risk": "MEDIUM",
    "sector_exposure": {
      "Technology": 0.60,
      "Healthcare": 0.25,
      "Consumer": 0.15
    }
  }
}
```

#### 3.4.2 获取技术分析
```http
GET /positions/{symbol}/technical?timeframe=1D

Response: (如 2.1.2 所示)
```

#### 3.4.3 获取基本面分析
```http
GET /positions/{symbol}/fundamental

Response: (如 2.1.3 所示)
```

#### 3.4.4 刷新持仓评估
```http
POST /positions/refresh
{
  "symbols": ["AAPL", "MSFT"],    // 可选，不传则刷新全部
  "force": false                   // 是否强制重新计算
}

Response:
{
  "status": "ok",
  "refreshed_count": 2,
  "cache_hits": 5,
  "calculation_time_ms": 1250
}
```

---

## 四、宏观风险分析模块设计

### 4.1 功能定义

#### 4.1.1 风险监控维度

**1. 货币政策风险 (Monetary Policy Risk)**
```
监控指标:
- 美联储利率决议、点阵图预期
- M2货币供应增速
- 美联储资产负债表规模
- 实际利率 vs 自然利率
- 通胀预期 (CPI/PCE/核心通胀)
- 美元指数 (DXY)

风险等级: 低/中/高
当前状态: "鹰派持续，流动性收缩"
影响资产: "高成长股、科技股负面"
```

**2. 地缘政治风险 (Geopolitical Risk)**
```
监控事件:
- 美中关系 (贸易/科技/台海)
- 俄乌战争进展
- 中东局势 (以巴冲突、伊朗核问题)
- 美国大选/政治极化
- 欧洲能源危机
- 全球供应链中断

风险等级: 低/中/高
热点事件: ["美国大选临近", "中东冲突升级"]
避险建议: "增加黄金、国债配置"
```

**3. 行业泡沫风险 (Sector Bubble Risk)**
```
监控行业:
- AI/科技股泡沫 (Seven Magnificent 估值)
- 加密货币泡沫
- 房地产泡沫
- 新能源汽车/绿色能源
- 生物科技

泡沫指标:
- 行业平均PE vs 历史分位数
- 散户持仓集中度
- 融资余额/杠杆率
- 新股发行热度
- 社交媒体情绪极值

当前评估: "AI板块估值过高，警惕回调"
```

**4. 经济周期风险 (Economic Cycle Risk)**
```
监控指标:
- GDP增速、PMI、零售销售
- 失业率、非农就业
- 消费者信心指数
- 收益率曲线 (2Y-10Y利差)
- 领先指标指数
- 衰退概率模型

周期阶段: 扩张/繁荣/衰退/萧条
衰退概率: 35%
持续时间: "距离衰退约6-9个月"
防御策略: "增加防御性股票、减少周期股"
```

**5. 市场情绪风险 (Market Sentiment Risk)**
```
监控指标:
- VIX恐慌指数
- Put/Call Ratio
- AAII散户情绪调查
- CNN Fear & Greed Index
- 资金流向 (股票/债券/现金)
- 内部人交易 (高管增减持)

当前情绪: 贪婪/恐惧/中性
极端信号: "VIX低于15，市场过度乐观"
```

### 4.2 宏观风险综合评分

```
宏观风险总分 (0-100，越高越安全):

总分 = 货币政策 × 30% + 地缘政治 × 20% + 行业泡沫 × 20% + 经济周期 × 20% + 市场情绪 × 10%

示例:
- 货币政策: 60/100 (中性偏紧)
- 地缘政治: 50/100 (多个热点)
- 行业泡沫: 45/100 (AI估值过高)
- 经济周期: 55/100 (软着陆概率上升)
- 市场情绪: 40/100 (过度乐观)

总分: 52/100 → "中等风险，建议保持防御性配置"
```

### 4.3 数据源设计

#### 4.3.1 宏观数据 API
```python
1. FRED (Federal Reserve Economic Data) - 免费
   - 美联储数据
   - 宏观经济指标
   - 利率、通胀、货币供应
   
2. Alpha Vantage - 部分免费
   - 经济指标 API
   - 技术指标
   
3. Trading Economics - 付费
   - 全球宏观数据
   - 经济日历
   
4. News API / RSS
   - 实时新闻监控
   - 关键事件提取
   
5. GPT-4 API
   - 新闻事件解读
   - 风险评估
   - AI总结
```

### 4.4 数据库设计

#### 4.4.1 宏观指标表
```sql
CREATE TABLE macro_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    indicator_type TEXT NOT NULL,    -- MONETARY/GEOPOLITICAL/SECTOR/ECONOMIC/SENTIMENT
    
    -- 货币政策
    fed_rate REAL,
    m2_growth_rate REAL,
    fed_balance_sheet BIGINT,
    inflation_rate REAL,
    dxy_index REAL,
    
    -- 经济周期
    gdp_growth REAL,
    unemployment_rate REAL,
    pmi_index REAL,
    yield_curve_2y10y REAL,
    recession_probability REAL,
    
    -- 市场情绪
    vix_index REAL,
    put_call_ratio REAL,
    fear_greed_index INTEGER,
    
    UNIQUE(date(timestamp), indicator_type)
);
```

#### 4.4.2 宏观风险评分表
```sql
CREATE TABLE macro_risk_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 分项评分 (0-100)
    monetary_policy_score INTEGER,
    geopolitical_score INTEGER,
    sector_bubble_score INTEGER,
    economic_cycle_score INTEGER,
    sentiment_score INTEGER,
    
    -- 综合评分
    overall_score INTEGER,
    risk_level TEXT,                 -- LOW/MEDIUM/HIGH/EXTREME
    
    -- AI分析
    risk_summary TEXT,
    key_concerns TEXT,               -- JSON array
    recommendations TEXT,
    
    -- 元数据
    data_sources TEXT,               -- JSON array
    confidence REAL,
    
    UNIQUE(date(timestamp))
);
```

#### 4.4.3 地缘政治事件表
```sql
CREATE TABLE geopolitical_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date DATETIME NOT NULL,
    event_type TEXT,                 -- TRADE_WAR/MILITARY/ELECTION/SANCTION
    region TEXT,
    title TEXT,
    description TEXT,
    
    -- 影响评估
    severity TEXT,                   -- LOW/MEDIUM/HIGH/CRITICAL
    affected_sectors TEXT,           -- JSON array
    market_impact_score INTEGER,     -- 0-100
    
    -- 来源
    news_source TEXT,
    news_url TEXT,
    
    UNIQUE(event_date, title)
);
```

### 4.5 API 设计

#### 4.5.1 获取宏观风险概览
```http
GET /macro/risk/overview

Response:
{
  "timestamp": "2025-12-31T10:30:00Z",
  "overall_risk": {
    "score": 52,
    "level": "MEDIUM",
    "trend": "INCREASING",           // INCREASING/STABLE/DECREASING
    "summary": "宏观环境中性偏空，货币政策紧缩，地缘风险上升，AI板块估值过高"
  },
  
  "risk_breakdown": {
    "monetary_policy": {
      "score": 60,
      "level": "MEDIUM",
      "status": "鹰派持续，流动性收缩",
      "key_indicators": {
        "fed_rate": 5.50,
        "next_meeting": "2025-01-31",
        "rate_cut_probability": 0.25,
        "inflation_cpi": 3.2,
        "inflation_target": 2.0
      },
      "impact": {
        "positive_sectors": ["Financial", "Energy"],
        "negative_sectors": ["Technology", "Growth Stocks"]
      }
    },
    
    "geopolitical": {
      "score": 50,
      "level": "MEDIUM",
      "hot_spots": [
        {
          "event": "US Election 2024",
          "severity": "HIGH",
          "probability": 0.95,
          "impact": "Policy uncertainty, market volatility"
        },
        {
          "event": "Middle East Conflict",
          "severity": "MEDIUM",
          "probability": 0.70,
          "impact": "Oil price volatility, safe haven demand"
        }
      ],
      "safe_haven_recommendation": "Gold, US Treasury, Defense stocks"
    },
    
    "sector_bubble": {
      "score": 45,
      "level": "MEDIUM_HIGH",
      "bubbles": [
        {
          "sector": "AI/Technology",
          "bubble_probability": 0.65,
          "indicators": {
            "avg_pe": 45.2,
            "historical_percentile": 92,
            "retail_ownership": 0.35,
            "margin_debt": "elevated"
          },
          "warning": "Magnificent 7估值过高，注意回调风险"
        },
        {
          "sector": "Cryptocurrency",
          "bubble_probability": 0.80,
          "warning": "极端投机情绪，建议降低仓位"
        }
      ]
    },
    
    "economic_cycle": {
      "score": 55,
      "level": "MEDIUM",
      "stage": "Late Expansion",
      "recession_probability": 0.35,
      "time_to_recession": "6-9 months",
      "leading_indicators": {
        "pmi": 48.5,
        "yield_curve": -0.25,
        "unemployment_trend": "rising",
        "consumer_confidence": 65.2
      },
      "defensive_strategy": "Increase healthcare, utilities, consumer staples"
    },
    
    "market_sentiment": {
      "score": 40,
      "level": "RISK_ON",
      "status": "过度乐观，警惕反转",
      "indicators": {
        "vix": 14.2,
        "put_call_ratio": 0.65,
        "fear_greed_index": 72,
        "aaii_bullish": 0.52,
        "aaii_bearish": 0.22
      },
      "warning": "Complacency high, volatility may spike"
    }
  },
  
  "ai_recommendations": [
    "考虑降低科技股仓位至30%以下",
    "增加防御性板块配置（医疗、公用事业）",
    "保持10-15%现金比例应对波动",
    "关注地缘政治事件对能源、国防股的影响",
    "警惕VIX突破20的系统性风险"
  ],
  
  "next_key_events": [
    {
      "date": "2025-01-15",
      "event": "CPI数据发布",
      "importance": "HIGH"
    },
    {
      "date": "2025-01-31",
      "event": "美联储FOMC会议",
      "importance": "CRITICAL"
    }
  ]
}
```

#### 4.5.2 获取货币政策分析
```http
GET /macro/monetary-policy

Response: (详细的货币政策分析)
```

#### 4.5.3 获取地缘政治事件
```http
GET /macro/geopolitical-events?days=30

Response: (最近30天的地缘政治事件及影响)
```

#### 4.5.4 刷新宏观数据
```http
POST /macro/refresh
{
  "indicators": ["all"],             // 或指定 ["monetary", "geopolitical"]
  "use_cache": true
}
```

---

## 五、实现路线图与进度

### 5.1 已完成功能 ✅

#### 5.1.1 前端架构 (已完成)
- ✅ Vue 3 + TypeScript + Vite 项目搭建
- ✅ Vue Router 4 路由系统集成
- ✅ 三个独立页面组件创建
  - ✅ BehaviorScorePage.vue (行为评分)
  - ✅ PositionsPage.vue (持仓评估)
  - ✅ MacroRiskPage.vue (宏观风险)
- ✅ 全局配置管理 (global.ts)
- ✅ Axios HTTP 客户端配置 (30秒超时)
- ✅ 深色主题 UI 设计

#### 5.1.2 页面级说明组件 (已完成)
- ✅ BehaviorGuideline.vue (行为评分说明)
  - 包含：行为评分、蝇营狗苟、过度交易、报复性交易说明
  - 包含：Greeks 指标详解和操作建议
- ✅ PositionsGuideline.vue (持仓评估说明)
  - 包含：技术面、基本面、情绪面评分详解
  - 包含：操作建议和风险等级说明
- ✅ MacroRiskGuideline.vue (宏观风险说明)
  - 包含：五维风险模型详细说明
  - 包含：风险应对策略和监测指标

#### 5.1.3 错误处理与用户体验 (已完成)
- ✅ 超时错误友好提示 (⏱️ 请求超时，请稍后再试！)
- ✅ 网络错误提示 (🌐 网络连接失败...)
- ✅ 加载状态显示
- ✅ 空数据状态处理
- ✅ 图标乱码修复 (宏观风险 🌍)

#### 5.1.4 API 客户端 (已完成)
- ✅ fetchAiState() - 获取行为评分状态
- ✅ rebuildBehavior() - 重新计算行为评分
- ✅ fetchPositionsAssessment() - 获取持仓评估
- ✅ refreshPositions() - 刷新持仓数据
- ✅ fetchMacroRiskOverview() - 获取宏观风险概览
- ✅ refreshMacroData() - 刷新宏观数据
- ✅ 所有 API 函数配置超时和错误处理

### 5.2 进行中功能 🔄

#### 5.2.1 后端 API 实现
- 🔄 持仓评估 API endpoints
- 🔄 技术分析数据采集
- 🔄 基本面数据集成
- 🔄 宏观风险评分算法

### 5.3 待实现功能 📋

#### 5.3.1 数据层 (Phase 1-2)
- [ ] 数据库表结构设计和创建
- [ ] 外部 API 集成 (yfinance, FMP, FRED)
- [ ] 缓存机制设计
- [ ] 技术指标计算引擎
六、技术栈

### 6.1 前端技术 (已实现)和存储
- [ ] 估值模型实现
核心框架:
- Vue 3.5.0 (Composition API)
- TypeScript 5.7.3
- Vue Router 4.x
- Vite 7.3.0

HTTP 客户端:
- Axios 1.7.0 (30秒超时配置)

UI 风格:
- 深色主题 (专业金融风格)
- 响应式设计 (移动端适配)
- 渐变动画效果
- 图标: Emoji Unicode

组件库 (自研):
- RiskSummaryCard (风险总览卡片)
- GreeksWaterLevel (Greeks水位图)
- SymbolBehaviorCard (标的行为卡片)
- PositionScoreCard (持仓评分卡片)
- MacroRiskDashboard (宏观风险仪表盘)
- BehaviorGuideline (行为评分说明)
- PositionsGuideline (持仓评估说明)
- MacroRiskGuideline (宏观风险说明)
```

### 6.2 后端技术 (现有 + 规划)
```
现有技术栈:
- FastAPI
- SQLite + SQLAlchemy (async)
- T七ger Open API
- Python 3.11+
7
规划新增:
- yfinance: 获取市场数据
- pandas-ta: 技术指标计算
- financialmodelingprep: 基本面数据
- fredapi: 美联储经济数据
- openai: GPT-4 AI分析
- newsapi: 新闻数据
- apscheduler: 定时任务
```

### 6.3 未来图表库规划
```
技术图表:
- TradingView Lightweight Charts
- EC7.2 开发成本 (预估)观数据可视化)

高级组件:
- Heat Map (行业/板块热力图)
- Timeline (事件时间线)
- Candlestick Chart (K线

###八5.1 后端技术
```
现有技术8:
- FastAPI
- SQLite + SQLAlchemy (async)
- Tiger Open API

新增依赖:
- yf8nance: 获取市场数据
- pandas-ta: 技术指标计算
- financialmodelingprep: 基本面数据
- fredapi: 美联储经济数据
- openai: GPT-4 AI分析
- ne8sapi: 新闻数据
- apscheduler: 定时任务
```

### 5.2 前端建议
```
图表库:
- TradingView Lightweight Charts (技术图表)
- E九harts (宏观数据可视化)
- Recharts (Portfolio分析)

UI组件:
- Risk Level Indicator (风险等级指示器)
- Score Card (评分卡片)
- Timeline (事件时间线)
- Heat Map (行业/板块热力图)
```

---

## 六、成本估算

### 6.1 API 费用 (月度)
```
免费:
- yfinance: $0
- FRED API: $0
- Tiger API: $0 (已有)
## 十、项目文件结构

```
ai_trading_frontend_v4/
├── index.html                          # 入口 HTML
├── package.json                        # 项目依赖配置
├── tsconfig.json                       # TypeScript 配置
├── vite.config.ts                      # Vite 构建配置
├── README.md                           # 项目说明
├── POSITION_AND_MACRO_RISK_DESIGN.md  # 本设计文档
│
└── src/
    ├── main.ts                         # 应用入口
    ├── App.vue                         # 根组件 (布局+导航)
    ├── style.css                       # 全局样式
    │
    ├── router/
    │   └── index.ts                    # Vue Router 配置
    │
    ├── config/
    │   └── global.ts                   # 全局配置 (windowDays)
    │
    ├── api/
    │   └── client.ts                   # API 客户端 (Axios)
    │
    ├── views/                          # 页面组件
    │   ├── BehaviorScorePage.vue       # 行为评分页面
    │   ├── PositionsPage.vue           # 持仓评估页面
    │   └── MacroRiskPage.vue           # 宏观风险页面
    │
    └── components/                     # 可复用组件
        ├── RiskSummaryCard.vue         # 风险总览卡片
        ├── GreeksWaterLevel.vue        # Greeks水位图
        ├── SymbolBehaviorCard.vue      # 标的行为卡片
        ├── PositionScoreCard.vue       # 持仓评分卡片
        ├── MacroRiskDashboard.vue      # 宏观风险仪表盘
        ├── BehaviorGuideline.vue       # 行为评分说明
        ├── PositionsGuideline.vue      # 持仓评估说明
        ├── MacroRiskGuideline.vue      # 宏观风险说明
        ├── FundamentalCard.vue         # 基本面卡片
        ├── TechnicalChart.vue          # 技术图表
        ├── RiskLevelIndicator.vue      # 风险等级指示器
        └── ScoreGuideline.vue          # 通用评分指南 (已弃用)
```

---

## 十一、版本历史

### v2.0 (2026-01-05) - 前端架构重构 ✅
**重大更新**：
- 从 Tab 页切换改为 Vue Router 页面导航
- window_days 提取为全局配置
- 评分标准说明从侧边栏移至各页面底部
- 超时和网络错误友好提示
- 修复宏观风险图标乱码

**文件变更**：
- 新增：`src/router/index.ts` (路由配置)
- 新增：`src/config/global.ts` (全局配置)
- 新增：`src/views/BehaviorScorePage.vue`
- 新增：`src/views/PositionsPage.vue`
- 新增：`src/views/MacroRiskPage.vue`
- 新增：`src/components/BehaviorGuideline.vue`
- 新增：`src/components/PositionsGuideline.vue`
- 新增：`src/components/MacroRiskGuideline.vue`
- 重构：`src/App.vue` (改为路由容器)
- 更新：`src/api/client.ts` (添加错误处理)

### v1.0 (2025-12) - 初始版本
- 行为评分模块基础实现
- Tab 页切换式 UI
- 基础 API 集成

---

**下一步行动计划**：
1. ✅ 完成前端架构和 UI/UX 设计
2. 🔄 继续完善后端 API 实现
3. 📋 集成外部数据源 (yfinance, FMP, FRED)
4. 📋 实现技术指标和评分算法
5. 📋 AI 分析增强~$50/月 (预估调用量)
- News API: $49/月 (Business计划)

总计: ~$130/月
```

### 6.2 开发成本
```
预估: 14周 × 40小时/周 = 560小时
```

---

## 七、风险和挑战

### 7.1 技术风险
- API 限流和稳定性
- 数据质量和准确性
- 实时性要求 vs 成本平衡
- 模型准确度验证

### 7.2 合规风险
- 投资建议合规性（需要免责声明）
- 数据使用许可
- 用户隐私保护

### 7.3 缓解措施
- 多数据源备份
- 缓存机制降低API调用
- A/B测试验证模型效果
- 明确"仅供参考"声明

---

## 八、后续优化方向

1. **机器学习增强**
   - 预测模型（价格预测、风险预测）
   - 异常检测（黑天鹅事件）
   
2. **个性化推荐**
   - 基于用户风险偏好的定制化建议
   - 学习用户交易习惯
   
3. **社交功能**
   - 专家观点聚合
   - 社区情绪分析
   
4. **移动端优化**
   - 实时推送
   - 轻量级Dashboard

---

**准备好开始实施了吗？建议从 Phase 1 开始，我可以帮您：**
1. 创建数据库 Migration 脚本
2. 集成第一个外部 API (yfinance)
3. 实现第一个技术指标计算函数
