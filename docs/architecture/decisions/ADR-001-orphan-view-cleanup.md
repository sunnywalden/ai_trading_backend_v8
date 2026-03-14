# ADR-001: Orphan Frontend View Cleanup

**Status**: Accepted  
**Date**: 2026-03-14  
**Version**: V11.1.1

---

## Context

Prior to V11.1.1, `src/views/` contained **53 `.vue` files** while `src/router/index.ts` listed **18 legacy redirect aliases** (excluding the root `/` redirect). Code archaeology confirmed 13 of these view files had zero active routes pointing to them — they existed only as the *source* of legacy redirects, not as live destinations. Similar dead code inflated the redirect table with 8 aliases that served no backward-compatibility purpose.

## Decision

Delete all 13 orphan view files and remove their associated 8 redirect entries as a *pre-convergence cleanup* step, before any functional page merges. This reduces risk: deleting unreferenced code cannot break running behaviour.

### Deleted view files

| File | Reason |
|------|--------|
| `DashboardPage.vue` | Superseded by `DashboardV2Page.vue` |
| `AIAdvisorPage.vue` | `/ai-advisor` redirected to `/autonomy` |
| `AiAdvicePage.vue` | No route, duplicate of above |
| `ExecutionCenter.vue` | `/execution-center` redirected to `/autonomy` |
| `ExecutionListPage.vue` | No active route |
| `AlgoExecutionPage.vue` | Covered by `/execution-policy` |
| `StressTestPage.vue` | `/stress-test` redirected to `/backtest` |
| `BehaviorScorePage.vue` | No active route |
| `MarketHotspotsPage.vue` | `/hotspots` redirected to `/opportunities` |
| `ApiMonitoringPage.vue` | `/api-monitoring` redirect kept, view dead |
| `ServiceHealthPage.vue` | `/service-health` redirect kept, view dead |
| `SystemHealthPage.vue` | No route, covered by `SystemMonitorPage` |
| `ExternalApiMonitoringPage.vue` | No route, monitoring view duplicate |

### Removed redirect aliases (8 of 18)

`/hotspots`, `/behavior`, `/ai-advisor`, `/execution-center`, `/stress-test`, `/execution-algo`, `/plans`, `/dashboard-v1`

### Retained redirects (10 remaining)

All 10 retained aliases have explicit backward-compatibility rationale:

- `/api-monitoring`, `/service-health` → system-monitor tab deep-links  
- `/monitoring`, `/system` → nav shorthand used in ops runbooks  
- `/observability/execution-microscope`, `/observability/signal-intelligence`, `/observability/risk-cluster` → documentation URL alignment  
- `/ai-hub/factor-weights`, `/ai-hub/post-mortems` → naming evolution  
- `/advice` → external entry-point shorthand

## Consequences

- **Positive**: frontend views reduced from 53 → **40** (meets V11.1.1 ≤ 40 target). Router file is measurably cleaner.
- **Positive**: no functional regression possible — each deleted file was confirmed to have zero imports and zero active router references.
- **Neutral**: the 10 retained redirects remain as technical debt; their sunset deadline is V11.2.
- **Negative**: none identified.

## Verification

```sh
# Count views after cleanup
(Get-ChildItem src/views -Recurse -Filter *.vue).Count  # expect ≤ 40
npm run build                                           # must pass cleanly
```
