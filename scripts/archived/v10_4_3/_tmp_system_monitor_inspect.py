import asyncio
import json

import app.models.strategy  # preload ORM relationships used by TradingSignal-related queries
from app.jobs.data_refresh_jobs import register_all_jobs
from app.jobs.data_sync_jobs import register_data_sync_jobs
from app.jobs.observability_jobs import register_observability_jobs
from app.jobs.scheduler import init_scheduler
from app.models.db import SessionLocal
from app.routers.system_monitor import (
    _build_data_flow_payload,
    _build_lifecycle_overview,
    _build_service_payload,
)

WINDOW = 60


async def main() -> None:
    scheduler = init_scheduler()
    register_all_jobs(scheduler)
    register_observability_jobs(scheduler)
    register_data_sync_jobs(scheduler)

    async with SessionLocal() as db:
        lifecycle = await _build_lifecycle_overview(db, WINDOW, False)
        flows, failures = await _build_data_flow_payload(db, WINDOW)
        modules, services, _, svc_failures = await _build_service_payload(db, WINDOW)

    payload = {
        "lifecycle_headline": lifecycle.headline.model_dump(mode="json"),
        "lifecycle_pipeline_degraded": [
            stage.model_dump(mode="json")
            for stage in lifecycle.pipeline
            if (stage.warn_count or stage.critical_count or stage.stuck_count)
        ],
        "lifecycle_exceptions": [item.model_dump(mode="json") for item in lifecycle.exceptions[:20]],
        "degraded_flows": [flow.model_dump(mode="json") for flow in flows if flow.status != "HEALTHY"],
        "degraded_services": [svc.model_dump(mode="json") for svc in services if svc.status != "HEALTHY" or svc.degraded],
        "degraded_modules": [mod.model_dump(mode="json") for mod in modules if mod.status != "HEALTHY"],
        "service_failures": {
            key: [item.model_dump(mode="json") for item in value]
            for key, value in svc_failures.items()
            if value
        },
        "flow_failures": {
            key: [item.model_dump(mode="json") for item in value]
            for key, value in failures.items()
            if value
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
