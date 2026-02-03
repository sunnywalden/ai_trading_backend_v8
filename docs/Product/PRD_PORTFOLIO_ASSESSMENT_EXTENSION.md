# 持仓评估模块：整体持仓评估与优化建议计划 (PRD)

## 1. 背景与目标
目前持仓评估模块已实现了对个股的技术面、基本面和情绪面分析。然而，交易员还需要从更宏观的视角审视整个账户的健康度，包括资产分布是否均匀、整体风险暴露（Beta）是否超标，以及如何根据当前的各标的评分来优化资金分配。

本扩展旨在：
- 提供账户级的资产配置快照。
- 自动化识别集中度风险。
- 基于 AI 算法给出具体的持仓优化建议（调仓、对冲、减持等）。

## 2. 核心功能需求

### 2.1 整体指标聚合 (Portfolio Metrics)
- **加权平均得分**：基于持仓市值的加权技术、基本、情绪面平均分。
- **组合盈亏汇总**：总未实现盈亏、当日盈亏贡献（P/L attribution）。
- **组合希腊字母 (Portfolio Greeks)**：聚合所有期权与正股的 Delta, Gamma, Theta, Vega（统一折算为正股等效）。

### 2.2 多维分布分析 (Diversification Analysis)
- **行业/板块分布**：通过饼图展示持仓在不同 Sector/Industry 的占比。
- **个股集中度**：识别是否有单标的占比超过 20% 的集中风险。
- **资产类别占比**：正股与期权的比重。

### 2.3 组合风险评估 (Risk Assessment)
- **组合 Beta 计算**：估算持仓相对大盘（SPY/QQQ）的整体相关性。
- **压力测试 (Stress Test)**：模拟市场下跌 5%/10% 时，预期账户回撤比例。
- **流动性评估**：评估在极端市场下，变现持仓的难易程度。

### 2.4 AI 优化建议 (Optimization Engine)
- **调仓建议 (Rebalancing)**：若高评分标的占比低，而低评分标的占比高，建议调配资金。
- **防御对冲建议**：当组合 Beta 过高或宏观风险水位升高时，建议增加的反向头寸（如买入 Put 或空头 ETF）。
- **冗余清理**：识别当前评分极低且趋势走坏的“僵尸头寸”，建议清仓。

## 3. 技术实现方案

### 3.1 接口扩展
- **Endpoint**: `GET /api/v1/positions/assessment`
- **Response 扩展**:
  ```json
  {
    "positions": [...],
    "portfolio_analysis": {
      "summary": { "weighted_score": 75.5, "total_beta": 1.2 },
      "distribution": { "technology": 0.6, "healthcare": 0.2, ... },
      "risk_metrics": { "value_at_risk": 5000, "stress_test_drawdown": 0.08 },
      "ai_recommendations": [
        { "type": "REBALANCE", "action": "将资金从 AAPL 转移至 NVDA", "reason": "NVDA 基本面评分更高且处于突破趋势" },
        { "type": "HEDGE", "action": "买入 SPY Put", "reason": "组合 Beta 过高（1.5），宏观风险窗口期" }
      ]
    }
  }
  ```

### 3.2 数据层
- 在 `position_trend_snapshots` 中增加或独立存储每日组合快照。
- 利用 OpenAI 对聚合后的分布数据进行生成式解读，输出优化文字建议。

## 4. 前端展示 (UI/UX)
- **概览面板**：在持仓列表上方增加一个大卡片，展示加权评分和 Beta。
- **可视化图表**：使用 ECharts 展示行业分布饼图。
- **优化任务清单**：以 Actionable List 形式展示 AI 建议。

## 5. 验收标准
- 组合加权评分计算逻辑准确（市值加权）。
- 行业分布数据与标的基本面分类一致。
- AI 建议能识别显著的配置偏差（如单一标的满仓）。
