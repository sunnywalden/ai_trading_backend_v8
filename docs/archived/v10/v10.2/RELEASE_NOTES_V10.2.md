# Release Notes — V10.2

**Release Date:** 2025-Q2  
**Theme:** *Intelligent Context · Self-Evolution · Copilot Partner*

---

## Overview

V10.2 builds on the V10.1 Market Regime Intelligence Engine (M1) to deliver seven additional production-grade milestones that transform the system from a signal-execution pipeline into a fully adaptive, self-learning trading organism.

---

## Milestones

### M1 — Market Regime Intelligence Engine ✅ (V10.1)
*Already released. See RELEASE_NOTES_V10.1.md.*

---

### M2 — Earnings Fence & Event Calendar

**Backend**
- `EventCalendarEntry` ORM model — stores earnings, FOMC, CPI, NFP, index rebalance, and dividend events with `risk_level` and `requires_fence` flags.
- `EventCalendarService` — daily 07:00 ET job scans upcoming earnings via **yfinance** and merges a hard-coded 2025 macro calendar (FOMC, CPI, NFP dates).
- `EarningsFenceService` — automatic position-size cap (≤50%) within `PREEARNING_DAYS=1` of any earnings event. Supports analyst override with reason logging.
- REST endpoints: `GET /api/v1/events/calendar`, `GET /api/v1/events/earnings-fence`, `PUT /api/v1/events/earnings-fence/{id}/override`, `POST /api/v1/events/earnings-result`.

**Frontend**
- `EventCalendarPage.vue` — grid of upcoming events colour-coded by risk level (LOW/MEDIUM/HIGH/EXTREME), EPS beat/miss indicator, fence status badges, and override modal.
- Navigation entry under **AI Autonomous Engine → Event Calendar**.

---

### M3 — Dynamic Position Lifecycle Management

**Backend**
- `PositionStateMachine` — lifecycle states: `ENTERING → SCALING_IN → HELD → SCALING_OUT / EXITING_FULL / STOP_LOSS_EXIT → CLOSED`.
- `ScaleInEngine` — three independent triggers:
  - Confidence boost ≥+10 pp → add 25% size.
  - Resistance breakout confirmed → add 20%.
  - Strategy resonance ≥2 aligned dims → add 15%.
- `ScaleOutEngine` — six priority-ordered exit rules: hard stop-loss (−8%), signal decay (<0.45), thesis broken (75% confidence collapse), time stop (60 d), partial target (+10-20%), full target (+20%).
- `TrailingStopEngine` — activates after +1% PnL; trail percentage per regime: BULL_TREND 5%, HIGH_VOL 4%, MEAN_REVERT 3%, RANGE_BOUND 3%, CRISIS 2%.
- REST endpoints: `POST /api/v1/positions/{id}/lifecycle`, `POST /api/v1/positions/{id}/manual-scale`, `POST /api/v1/positions/scale-in-candidates`.

---

### M4 — Multi-Dimensional Signal Fusion Engine

**Backend**
- `SignalFusionEngine` — six weighted dimensions:

  | Dimension      | Weight |
  |----------------|--------|
  | Technical      | 25%    |
  | Fundamental    | 20%    |
  | Macro          | 15%    |
  | Volume Anomaly | 15%    |
  | Options        | 15%    |
  | Sentiment      | 10%    |

- Resonance bonus: +5% per aligned dimension above 3.
- Conflict penalty: −15% when technical and fundamental conflict.
- Regime multipliers: BULL_TREND ×1.05, BEAR_TREND ×0.90, HIGH_VOL ×0.95, MEAN_REVERT ×0.88, CRISIS ×0.75.
- `SentimentScorer` — aggregates news, social, analyst revision, and insider activity sub-components.
- REST endpoints: `POST /api/v1/signals/fuse`, `POST /api/v1/signals/sentiment/{symbol}`.

---

### M5 — Three-Layer Trade Attribution Engine

**Backend**
- `TradeAttributionEntry` ORM model — 25 columns storing per-trade layer results as JSON blobs.
- `TradeAttributionEngine` — three attribution layers:
  1. **Alpha Source** — identifies the dominant signal dimension by `score × weight`.
  2. **Execution Quality** — compares entry slippage against `benchmark_entry`; timing score 0–1.
  3. **Position Management** — awards/penalises based on scale-in decisions and trailing stop outcomes.
- `get_summary()` — grouped statistics by `WIN / LOSS / BREAKEVEN` category.
- REST endpoints: `GET /api/v1/attribution/trades`, `GET /api/v1/attribution/summary`.

**Frontend**
- `AttributionPage.vue` — summary KPI cards, ECharts pie chart (WIN/LOSS/BREAKEVEN), sortable detail table with inline JSON drawers for each layer.

---

### M6 — AI Self-Evolution & Adaptive Insight Engine

**Backend**
- `AIInsight` ORM model — persistent experience repository with `insight_type` (PATTERN / TRAP / EXECUTION / PARAM_SUGGESTION), `actionable_rule` JSON, confidence, and `applied_count`.
- `ABExperiment` ORM model — A/B parameter experiments with Welch's t-test (`scipy.stats.ttest_ind`), auto-apply when `p < 0.05` and treatment win rate exceeds control.
- `WeeklyInsightGenerator` — Sunday 22:00 ET APScheduler job; queries last 30 days of attribution data, sends structured prompt to **deepseek-reasoner**, persists 3–7 insights.
- `ABTestEngine` — evaluates running experiments daily at 08:00 ET; automatically applies winning parameters.
- REST endpoints: `GET/POST /api/v1/insights/repository`, `PATCH /api/v1/insights/repository/{id}`, `GET/POST /api/v1/insights/experiments`.

**Frontend**
- `EvolutionPage.vue` — tabbed view: **Insights** (colour-coded type badges, confidence %, actionable rule JSON) and **A/B Experiments** (control vs. treatment win rate, p-value, significance badge).

---

### M7 — Copilot Partner Intelligence

**Backend**
- `ProactiveIntelligenceService` — four proactive alert builders:
  - `REGIME_SWITCH` — triggered when market regime changes.
  - `SCALE_IN_OPP` — surfaces high-conviction scale-in candidates.
  - `DRAWDOWN_ALERT` — fires at −5%/−8%/−12% portfolio drawdown thresholds.
  - `WEEKLY_PREVIEW` — Monday morning market context briefing.
- `MultiStepIntentEngine` — decomposes complex queries into steps via **deepseek-chat**, executes each step (yfinance data fetch, indicator calculation), synthesises via **deepseek-reasoner**.
- `DeepResearchEngine` — gathers six data sources (price history, fundamentals, options chain, macro indicators, news sentiment, analyst ratings), produces structured `DeepResearchReport` with rating, price target, and 500-word analysis body.
- REST endpoint: `POST /api/v1/copilot/deep-research`.

**Frontend**
- `CopilotPage.vue` updated — mode toggle (Standard ↔ Deep Research), symbol + query inputs, structured report display (rating badge, price target, full body, data sources).

---

### M8 — Documentation & Release

- ✅ This `RELEASE_NOTES_V10.2.md`
- ✅ `BACKEND_DESIGN.md` updated with V10.2 API table and project tree
- ✅ `FRONTEND_DESIGN.md` updated with navigation map and page catalogue
- ✅ `PRODUCT.md` updated with V10.2 feature summary

---

## Database Migrations

Run the migration script before deploying:

```bash
python scripts/migrations/upgrade_to_v10_2_m2_m8.py
# Dry-run: python scripts/migrations/upgrade_to_v10_2_m2_m8.py --check
# Rollback: python scripts/migrations/upgrade_to_v10_2_m2_m8.py --rollback
```

New tables created:
- `event_calendar_entries`
- `trade_attribution_entries`
- `ai_insight_repository`
- `ab_experiments`

---

## API Summary

| Method | Path | Milestone | Description |
|--------|------|-----------|-------------|
| GET | `/api/v1/events/calendar` | M2 | Upcoming event list |
| GET | `/api/v1/events/earnings-fence` | M2 | Active position fences |
| GET | `/api/v1/events/earnings-fence/{symbol}` | M2 | Single symbol fence status |
| PUT | `/api/v1/events/earnings-fence/{id}/override` | M2 | Override fence with reason |
| POST | `/api/v1/events/earnings-result` | M2 | Record actual EPS result |
| POST | `/api/v1/positions/{id}/lifecycle` | M3 | Evaluate position lifecycle |
| POST | `/api/v1/positions/{id}/manual-scale` | M3 | Manual scale in/out |
| POST | `/api/v1/positions/scale-in-candidates` | M3 | List scale-in opportunities |
| POST | `/api/v1/signals/fuse` | M4 | Fuse multi-dimensional signals |
| POST | `/api/v1/signals/sentiment/{symbol}` | M4 | Sentiment score only |
| GET | `/api/v1/attribution/trades` | M5 | Attribution trade list |
| GET | `/api/v1/attribution/summary` | M5 | Attribution summary stats |
| GET | `/api/v1/insights/repository` | M6 | Insight list |
| POST | `/api/v1/insights/repository` | M6 | Create insight |
| PATCH | `/api/v1/insights/repository/{id}` | M6 | Update insight |
| GET | `/api/v1/insights/experiments` | M6 | A/B experiment list |
| POST | `/api/v1/insights/experiments` | M6 | Create A/B experiment |
| POST | `/api/v1/copilot/deep-research` | M7 | Deep research report |

---

## Frontend Pages

| Path | Component | Milestone |
|------|-----------|-----------|
| `/events` | `EventCalendarPage.vue` | M2 |
| `/attribution` | `AttributionPage.vue` | M5 |
| `/evolution` | `EvolutionPage.vue` | M6 |
| `/copilot` (updated) | `CopilotPage.vue` | M7 |

---

## Scheduled Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `_run_event_calendar_scan` | Daily 07:00 ET | Sync earnings + macro events |
| `_run_weekly_insight_generation` | Sunday 22:00 ET | AI insight analysis |
| `_run_ab_experiment_checker` | Daily 08:00 ET | Evaluate A/B significance |

---

## Dependencies Added

```
scipy>=1.12.0      # A/B t-test
yfinance>=0.2.38   # Earnings calendar (already present)
```

---

## Breaking Changes

None. All new routes are additive. Existing `/api/v1/copilot/chat` behaviour is unchanged.
