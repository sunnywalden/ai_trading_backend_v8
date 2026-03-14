# ADR-002: Legacy Backend Router Sunset

**Status**: Accepted  
**Date**: 2026-03-14  
**Version**: V11.1.1

---

## Context

`app/main.py` registered **5 legacy route files** whose corresponding frontend pages had already been redirected or removed. These routes continued to consume import-time resources, polluted OpenAPI docs, and created the illusion of live API surfaces for deprecated features.

## Decision

Remove all 5 legacy router registrations from `app/main.py` by V11.1.1. Where a router contained genuinely live endpoints still called by active frontend components, migrate those endpoints to the canonical successor router before removing.

### Disposal matrix

| Router file | API prefix | Disposal | Notes |
|-------------|------------|----------|-------|
| `ai_advisor.py` | `/api/v1/ai-advisor/...` | **Removed** | No active frontend API calls; `/ai-advisor` redirect removed in ADR-001 |
| `execution_center.py` | `/api/v1/execution-center/...` | **Removed** | Only caller was `PlanEditDialog.vue`, which was itself an orphan component with zero importers |
| `hotspots.py` | `/api/v1/hotspots/...` | **Removed** | `fetchLatestHotspots()` defined in `client.ts` but never called from any active Vue component |
| `stress_test.py` | `/api/v1/stress-test/...` | **Migrated then removed** | `VaRRiskMonitor.vue` (used in `DashboardV2Page`) called `/v1/stress-test/run` and `/v1/stress-test/scenarios`; endpoints migrated to `POST /v1/backtest/stress-test/run` and `GET /v1/backtest/stress-test/scenarios` inside `backtest.py`; `stressTestService.ts` URL updated |
| `dashboard.py` (V9) | `/api/v1/dashboard/...` | **Deprecated tag** | Still registered in `main.py` but tagged `[DEPRECATED-V9]`; planned removal in V11.2 |

### Orphan component cleanup

`src/components/PlanEditDialog.vue` — the only caller of `execution_center.py` — was itself confirmed to have zero importers across the entire frontend. It was also deleted.

## Consequences

- **Positive**: `app/main.py` now imports only actively-used routers; legacy API surfaces no longer appear in OpenAPI /docs.
- **Positive**: Meets M1 target: ≤ 2 active legacy routes remain (`dashboard.py` V9, kept temporarily).
- **Risk (mitigated)**: `stress_test.py` migration path was validated by tracing `VaRRiskMonitor.vue` → `stressTestService.ts` → backend; all URLs updated atomically.
- **Sunset deadline**: `dashboard.py` (V9) must be removed by V11.2. Its registration will be the only legacy registration remaining after this ADR.

## Migration guide

Frontend code that previously called `/v1/stress-test/run` or `/v1/stress-test/scenarios` must be updated:

```
# Old
POST  /api/v1/stress-test/run
GET   /api/v1/stress-test/scenarios

# New (V11.1.1)
POST  /api/v1/backtest/stress-test/run
GET   /api/v1/backtest/stress-test/scenarios
```

`stressTestService.ts` has been updated accordingly.

## Verification

```sh
# Backend startup must succeed without import errors
.venv\Scripts\python.exe -c "from app.main import app; print('OK')"

# Stress-test migration (via acceptance script)
.venv\Scripts\python.exe scripts\checks\_acceptance_v10_5_4.py
```
