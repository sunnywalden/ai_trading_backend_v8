# V9 Alpha Loop 功能指标说明

## 📊 Dashboard（仪表盘）

### 核心指标
- **总权益**：账户资产总值（现金 + 持仓市值）
- **当日盈亏**：今日相对昨日收盘的损益金额和百分比
- **MTD/YTD**：月度/年度累计收益率
- **风险等级**：基于 Greeks 暴露自动评估（LOW/MEDIUM/HIGH/EXTREME）

### Greeks 敞口水位
- **Delta**: 方向性风险敞口（>80% 为极端）
- **Gamma**: 二阶风险，Delta 变化速度
- **Vega**: 波动率风险敞口
- **Theta**: 时间价值衰减

### 计划执行
- **活跃计划数**：当前 ACTIVE 状态的交易计划
- **执行率**：已执行计划 / 总计划数

### 最近信号
- 价格告警触发记录（最近5条）
- 可跳转到告警详情页

### 待办事项
- 今日到期的交易计划
- 需要复盘的交易
- 超限的 Greeks 敞口

---

## 💰 资金曲线 & PnL归因

### 权益曲线
- **时间范围选择**：7D / 30D / 90D / 180D / 365D
- **主曲线**：账户总权益变化
- **回撤柱状图**：最大回撤百分比（红色）
- **基准对比**：可选 SPY 等基准指数

### PnL 归因
支持两种归因维度：

#### 按标的归因
- 展示每个交易标的的盈亏贡献
- 交易笔数统计
- 占总盈亏的百分比

#### 按策略归因
- momentum（动量策略）
- mean_reversion（均值回归）
- breakout（突破策略）
- value（价值策略）
- growth（成长策略）

---

## 📓 交易日志

### 日志字段
- **标的 & 方向**：交易标的代码和 BUY/SELL 方向
- **入场/出场**：日期和价格
- **数量 & 盈亏**：交易规模和已实现损益
- **执行质量**：1-5 分自评（1=差，5=优秀）
- **情绪状态**：calm / fomo / revenge / confident / anxious
- **策略类型**：关联的交易策略
- **错误标签**：chase_high（追高）/ sell_fly（卖飞）/ no_plan（无计划）
- **反思记录**：交易后的总结

### AI 复盘
- 点击"AI 复盘"按钮触发
- 调用 GPT 分析交易得失
- 自动生成执行质量评价、情绪分析和改进建议
- 评分 0-100

### 筛选条件
- 按标的筛选
- 按状态筛选（DRAFT / COMPLETED / REVIEWED）

### 周报功能
- 生成指定周的交易汇总
- 整体表现评价
- 做得好的地方
- 需要改进的点
- 下周重点关注事项

---

## 🔔 价格告警

### 告警规则
- **标的 & 条件**：支持"价格高于"和"价格低于"两种触发条件
- **阈值**：触发价格
- **动作**：
  - `notify`：仅通知
  - `auto_execute`：自动执行关联计划
  - `log_only`：仅记录日志
- **状态**：ACTIVE / TRIGGERED / PAUSED

### 操作
- **暂停/恢复**：临时停用或恢复告警
- **删除**：永久删除告警规则

### 触发历史
- 记录每次告警触发的时间、价格
- 显示执行的动作

---

## 🧭 交易助手（Trading Plans）

### 计划字段
- **标的 & 方向**：交易标的和 BUY/SELL
- **入场价格区间**：entry_price_low ~ entry_price_high
- **止损价**：stop_loss_price
- **止盈价**：take_profit_price
- **目标数量**：target_quantity
- **有效期**：valid_until（过期自动失效）
- **策略类型**：关联策略
- **备注**：交易理由和注意事项

### 执行状态
- **DRAFT**：草稿，未激活
- **ACTIVE**：活跃监控中
- **EXECUTED**：已执行
- **CANCELLED**：已取消
- **EXPIRED**：已过期

### 通知
- 计划即将到期（Dashboard 待办事项）
- 价格进入入场区间（可配置告警）

---

## 🎯 研究模块（未实施详细功能）

### 市场热点
- 聚合美股、全球宏观及重大财经动态
- 支持网格/列表视图切换

### 宏观分析
- 展示宏观风险摘要与等级
- 支持展开查看详细仪表盘

### 股票分析（AI Advice）
- 输入港美股标的
- 获取多周期 K 线深度走势预测与操作建议

### 策略筛选
- 浏览内置私募精选策略
- 触发异步回测或实盘扫描

### 行为评分
- 基于近 N 天老虎证券历史成交与盈亏数据
- 计算交易行为评分

### 持仓评估
- 从技术面、基本面、情绪面三维度
- 对当前持仓进行综合评分

---

## 🩺 系统监控

### 服务健康
- 后端服务状态检查
- 最后更新时间
- 监控系统启用状态

### API 监控
- **提供商状态**：Tiger / Yahoo Finance / OpenAI 等
- **统计粒度**：日统计 / 时统计 / 分统计
- **Rate Limit**：调用次数、限额、剩余配额
- **告警面板**：Critical alerts / Warnings / 最近错误

---

## 🚀 快速开始

### 1. 初始化演示数据

```bash
cd backend
python init_v9_demo_data.py
```

这会生成：
- 过去 30 天的资金曲线快照
- 25 条交易日志（含盈亏）
- 12 个交易计划（活跃+已执行）
- 10 个价格告警规则和历史记录

### 2. 启动后端服务

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

### 3. 启动前端服务

```bash
cd ../ai_trading_frontend_v4
npm run dev
```

### 4. 访问前端页面

- Dashboard: http://localhost:5173/dashboard
- 资金曲线: http://localhost:5173/equity
- 交易日志: http://localhost:5173/journal
- 价格告警: http://localhost:5173/alerts
- 交易助手: http://localhost:5173/plans
- 系统监控: http://localhost:5173/system

---

## 🔐 认证说明

默认管理员账号（可在 `.env` 中修改）：
- 用户名：`admin`
- 密码：`admin123`

JWT Token 有效期：默认 24 小时

---

## 📝 开发建议

### 数据层
- 所有 Service 已实现业务逻辑
- 数据库表自动创建（`app/models/db.py` 中的 `ensure_mysql_tables()`）
- 使用 SQLAlchemy Async 驱动

### 前端组件
- 所有页面已实现（`src/views/`）
- Pinia Store 管理状态（`src/stores/`）
- API 客户端统一封装（`src/api/client.ts`）

### 扩展方向
1. **实时推送**：WebSocket 支持已预留（`src/stores/websocket.ts`）
2. **AI 增强**：GPT 集成在 `journal_service.py` 中
3. **回测引擎**：已有策略运行基础设施
4. **多账户支持**：数据库设计支持多账户隔离

---

## 🐛 常见问题

### Q: Dashboard 数据全是 0？
A: 运行 `python init_v9_demo_data.py` 初始化演示数据

### Q: Tiger API rate limit 错误？
A: Broker 客户端已改为单例模式，重启后端即可

### Q: 前端路由 /api-monitoring 或 /monitoring 不存在？
A: 已合并为 `/system`，旧路由会自动 redirect

### Q: 如何切换到真实 Tiger API？
A: 在 `.env` 中配置 `TIGER_PRIVATE_KEY_PATH`、`TIGER_ID`、`TIGER_ACCOUNT`

---

## 📌 下一步计划

- [ ] WebSocket 实时推送（Greeks 变化、告警触发）
- [ ] 计划自动执行（价格触发时下单）
- [ ] 交易日志自动导入（从券商同步）
- [ ] 更多归因维度（按行业、按市场）
- [ ] 移动端适配
- [ ] 暗色/浅色主题完善
