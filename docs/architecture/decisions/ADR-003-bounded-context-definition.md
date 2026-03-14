# ADR-003: Bounded Context Definition — Engine vs Services

**Status**: Accepted  
**Date**: 2026-03-14  
**Version**: V11.1.1

---

## Context

`app/services/` now contains **100+ `.py` files** with no sub-namespace structure. `app/engine/` contains the core decision-and-execution orchestration components. As the codebase grew, the boundary between "orchestration" and "domain business logic" blurred: some services call back into engine abstractions, some routers directly orchestrate multi-domain operations.

V11.1.1 establishes formal bounded-context divisions to support V11.1.x and V11.2 development without further code entropy.

## Decision

### Layer definitions

| Directory | Name | Responsibility |
|-----------|------|---------------|
| `app/engine/` | Orchestration Layer | Cross-domain coordination, main decision loop, quality funnel, job dispatch |
| `app/services/` | Domain Services | Single-domain business rules, I/O operations, state management |
| `app/routers/` | Transport Layer | HTTP request/response, auth check, parameter validation only |

**Dependency rule**: `engine` → `services` → `models/adapters`. Services MUST NOT import from `app/engine/`. Routers MUST NOT perform business logic beyond parameter validation.

### Domain sub-contexts inside `app/services/`

New capabilities must be placed under the appropriate sub-context. Existing files are not forcibly moved in V11.1.1 — migration happens as files are touched:

| Sub-context | Path pattern | Contains |
|-------------|-------------|---------|
| `autonomy` | `app/services/autonomy/` | MetaState, FrictionState, ImprovementCandidates, FalseHold |
| `research` | `app/services/research/` | AlphaLab, ResearchService, signal scoring |
| `portfolio` | `app/services/portfolio/` | CapacityArbiter, position sizing, risk budget |
| `execution` | `app/services/execution/` | ExecutionPolicy, OrderManager, PaperTrading |
| `governance` | `app/services/governance/` | GovernancePipeline, graduation logic, EvolutionService |
| `observability` | `app/services/observability/` | SignalWatchtower, AuditLog, attribution |
| `platform` | `app/services/platform/` | Scheduler, health, config, external adapters |

### Workbench Read Models

To avoid frontend assembling 4–8 calls per page, each major workbench gets a dedicated **read model service** that aggregates and shapes data for that view's primary query pattern. Read models live in `app/services/read_models/`:

| Workbench | Read model service |
|-----------|-------------------|
| Dashboard / War Room | `dashboard_summary.py` |
| Order Book | `order_book_workbench.py` |
| System Monitor | `system_monitor_workbench.py` |
| Governance Pipeline | `governance_pipeline_workbench.py` (future) |
| Execution Policy | `execution_policy_workbench.py` (future) |

Read model services are **read-only** — they call existing domain services and DB queries but never write. They may be cached aggressively.

### Protected area

`app/engine/autonomous_engine.py` (`AutonomousEngine.run_decision_cycle()`) remains the **sole orchestration entry-point** for automated trading. No second decision loop is permitted. The legacy `POST /execute-signals` entry-point in `quant_loop.py` is in sunset — V11.1.1 confirms the deprecated annotation; V11.2 removes the endpoint.

## Consequences

- **Positive**: new services have a clear home; code review can enforce placement.
- **Positive**: workbench read models reduce frontend N+1 API call patterns.
- **Neutral**: existing 100+ service files are not forcibly reorganised in V11.1.1; migration is incremental and happens when files are modified.
- **Risk**: The dependency rule (services must not import engine) may break a small number of existing files. These will be identified during V11.1.2 and converted to pass data via function arguments rather than direct engine imports.

## Verification

```sh
# Check that no app/services file imports app/engine
grep -rn "from app.engine" app/services/ | grep -v "__pycache__"
# Some violations may exist pre-V11.1.1; document and schedule for V11.1.2
```
