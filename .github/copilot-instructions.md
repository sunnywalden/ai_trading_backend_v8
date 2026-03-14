# AI Trading Backend V8 Copilot Instructions

This repository is a FastAPI backend for trading risk control, position assessment, execution governance, and autonomous decision support.

## Scope and priorities

- Prefer focused, minimal changes that preserve existing APIs, schema shapes, and route structure unless the task explicitly requires an interface change.
- Treat docs in `docs/PRODUCT.md`, `docs/API.md`, and `docs/BACKEND_DESIGN.md` as the authoritative functional and architecture context before using archived material.
- Favor fixing root causes over adding compatibility layers, one-off branches, or duplicated logic.

## Backend conventions

- Keep Python code compatible with the repository's current dependency set in `requirements.txt`.
- Follow existing FastAPI patterns already used in the repo. For route query parameters with `Annotated` and `Query(...)`, put defaults on the parameter assignment, not inside `Query(default=...)`.
- Preserve the current service-oriented structure under `app/services`, routers under `app/routers`, schemas under `app/schemas`, and engine/orchestration logic under `app/engine`.
- Do not introduce direct secrets or real credentials into tracked files. If configuration examples must change, update template files such as `.env.example` rather than local secret files.

## Validation

- For focused backend changes, prefer targeted validation before broad test runs.
- Common verified commands in this repo:
  - `.venv\Scripts\python.exe -m pytest tests\unit\test_v1051_research_service.py tests\unit\test_capacity_arbiter_service.py tests\unit\test_execution_policy_service.py tests\unit\test_paper_trading_service.py`
  - `.venv\Scripts\python.exe scripts\checks\_acceptance_v10_5_4.py`
- If a change touches only one service or router, run the smallest relevant unit test slice first.

## Trading and risk safety

- Be conservative with any code that can affect order generation, execution, or risk gating. Do not relax limits, change execution mode semantics, or widen permissions unless explicitly requested.
- Production behavior often depends on feature flags, staged rollout logic, and governance checks. Preserve those controls when refactoring.
- Avoid assuming that generated signals should always execute. This system deliberately contains validation, quality funnel, and governance layers that may block execution.

## Response style for this repo

- When explaining changes, mention user-visible behavior, risk implications, and the exact validation run.
- If a task appears to require data migrations, release sequencing, or rollout guardrails, call that out explicitly instead of silently folding it into code edits.