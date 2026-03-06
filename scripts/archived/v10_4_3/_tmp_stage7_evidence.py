import asyncio
import json

from sqlalchemy import text

from app.models.db import SessionLocal

SQL = text(
    """
    WITH stage7 AS (
        SELECT
            p.id,
            p.symbol,
            p.account_id,
            p.plan_status,
            p.position_fsm_state,
            p.pipeline_stage,
            p.created_at,
            p.stage_entered_at,
            p.updated_at
        FROM trading_plan p
        WHERE p.pipeline_stage = 7
        ORDER BY p.created_at ASC
        LIMIT 60
    )
    SELECT
        g.id,
        g.symbol,
        g.account_id,
        g.plan_status,
        g.position_fsm_state,
        g.created_at,
        i.intent_id,
        i.signal_id AS intent_signal_id,
        i.status AS intent_status,
        i.reason AS intent_reason,
        i.order_id AS intent_order_id,
        a.order_id AS audit_order_id,
        a.revoked_at,
        a.revoke_reason,
        a.created_at AS audit_created_at
    FROM stage7 g
    LEFT JOIN autonomous_execution_intent i
      ON i.account_id = g.account_id
     AND i.symbol = g.symbol
     AND i.created_at BETWEEN g.created_at - INTERVAL 10 MINUTE AND g.created_at + INTERVAL 10 MINUTE
    LEFT JOIN autonomy_audit_log a
      ON a.account_id = g.account_id
     AND a.symbol = g.symbol
     AND a.created_at BETWEEN g.created_at - INTERVAL 10 MINUTE AND g.created_at + INTERVAL 10 MINUTE
    ORDER BY g.created_at ASC, a.created_at ASC
    """
)

async def main() -> None:
    async with SessionLocal() as db:
        rows = [dict(row._mapping) for row in (await db.execute(SQL)).fetchall()]
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    asyncio.run(main())
