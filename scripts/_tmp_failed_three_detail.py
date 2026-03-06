import asyncio
import json

from sqlalchemy import text

from app.models.db import SessionLocal

IDS = (49, 50, 53)

SQL = text(
    """
    SELECT
      p.id AS plan_id,
      p.symbol,
      p.plan_status,
      p.pipeline_stage,
      p.position_fsm_state,
      p.created_at AS plan_created_at,
      p.stage_entered_at,
      p.updated_at AS plan_updated_at,
      p.plan_tags,
      p.provenance_snapshot,
      i.intent_id,
      i.signal_id AS intent_signal_id,
      i.signal_db_id,
      i.status AS intent_status,
      i.reason AS intent_reason,
      i.order_id AS intent_order_id,
      a.order_id AS audit_order_id,
      a.decision_type,
      a.revoked_at,
      a.revoke_reason,
      a.created_at AS audit_created_at,
      s.id AS signal_pk,
      s.signal_id,
      s.status AS signal_status,
      s.order_id AS signal_order_id,
      s.created_at AS signal_created_at,
      s.updated_at AS signal_updated_at
    FROM trading_plan p
    LEFT JOIN autonomous_execution_intent i
      ON i.account_id = p.account_id
     AND i.symbol = p.symbol
     AND i.created_at BETWEEN p.created_at - INTERVAL 15 MINUTE AND p.created_at + INTERVAL 15 MINUTE
    LEFT JOIN autonomy_audit_log a
      ON a.account_id = p.account_id
     AND a.symbol = p.symbol
     AND a.created_at BETWEEN p.created_at - INTERVAL 15 MINUTE AND p.created_at + INTERVAL 15 MINUTE
    LEFT JOIN trading_signals s
      ON s.account_id = p.account_id
     AND s.symbol = p.symbol
     AND s.created_at BETWEEN p.created_at - INTERVAL 15 MINUTE AND p.created_at + INTERVAL 15 MINUTE
    WHERE p.id IN :ids
    ORDER BY p.id, s.created_at, a.created_at
    """
)

FSM_SQL = text(
    """
    SELECT plan_id, fsm_type, from_state, to_state, engine, trigger_reason, occurred_at
    FROM fsm_transition_log
    WHERE plan_id IN :ids
    ORDER BY plan_id, occurred_at, id
    """
)

async def main() -> None:
    async with SessionLocal() as db:
        rows = [dict(row._mapping) for row in (await db.execute(SQL, {"ids": IDS})).fetchall()]
        fsm = [dict(row._mapping) for row in (await db.execute(FSM_SQL, {"ids": IDS})).fetchall()]
    print(json.dumps({"rows": rows, "fsm": fsm}, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    asyncio.run(main())
