"""Patch autonomous_engine.py: add _integrate_position_lifecycle method (V10.4.4)."""

import os
import sys

TARGET = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "autonomous_engine.py"
)

NEW_METHOD = '''
    async def _integrate_position_lifecycle(
        self,
        db,
        account_id: str,
        signal: dict,
        decision: dict,
        execution_intent_id,
        execution_path: str,
        autonomy_level: str,
        order_id: str,
    ) -> None:
        """V10.4.4: Route a successfully-submitted order into the Position lifecycle.

        - ENTRY / ADD signals  → open_position (or add_to_position if one already exists)
        - EXIT / REDUCE / STOP → reduce_position
        Updates the corresponding AutonomousExecutionIntent with position_id and
        execution_slice_id so both models stay in sync.
        """
        try:
            from app.services.position_lifecycle_manager import PositionLifecycleManager
            from app.models.execution_slice import SliceAction
            from app.models.position import ClosingReason

            plm = PositionLifecycleManager(db)
            sig_type = str(signal.get("signal_type") or "").upper()
            action    = str(decision.get("action")     or "").upper()
            symbol    = str(decision.get("symbol")     or signal.get("symbol") or "")
            qty       = float(decision.get("qty") or 0)
            thesis_key = str(signal.get("thesis_key") or "default")

            # Determine signal direction
            sig_dir   = str(signal.get("direction") or signal.get("signal_direction") or "").upper()
            is_closing = (
                sig_type in ("EXIT", "STOP_LOSS_EXIT", "TAKE_PROFIT_EXIT")
                or action in ("SELL", "CLOSE", "REDUCE")
                or sig_dir in ("EXIT", "SHORT_EXIT", "LONG_EXIT")
            )
            is_entry_add = sig_type in ("ENTRY", "ADD") or (
                action in ("BUY", "LONG") and not is_closing
            )

            _pos_id: int | None = None
            _slc_id: int | None = None

            if is_entry_add:
                # Try to find an existing active position (idempotent open)
                existing = await plm._find_active_position(account_id, symbol, thesis_key)
                if existing is not None:
                    # Scale in
                    slc = await plm.add_to_position(
                        position_id=existing.id,
                        requested_qty=qty,
                        signal_id=str(signal.get("signal_id") or signal.get("id") or ""),
                        signal_db_id=int(signal.get("id") or 0) or None,
                        intent_id=execution_intent_id,
                        execution_path=execution_path,
                        order_id=order_id,
                    )
                    _pos_id = existing.id
                    _slc_id = slc.id
                else:
                    # New position
                    pos, slc = await plm.open_position(
                        account_id=account_id,
                        symbol=symbol,
                        requested_qty=qty,
                        thesis_key=thesis_key,
                        direction=sig_dir or action,
                        signal_id=str(signal.get("signal_id") or signal.get("id") or ""),
                        signal_db_id=int(signal.get("id") or 0) or None,
                        intent_id=execution_intent_id,
                        execution_path=execution_path,
                        autonomy_level=autonomy_level,
                        order_id=order_id,
                    )
                    _pos_id = pos.id
                    _slc_id = slc.id

            elif is_closing:
                existing = await plm._find_active_position(account_id, symbol, thesis_key)
                if existing is not None:
                    if sig_type == "STOP_LOSS_EXIT":
                        cr = ClosingReason.STOP_LOSS
                    elif sig_type == "TAKE_PROFIT_EXIT":
                        cr = ClosingReason.TAKE_PROFIT
                    else:
                        cr = ClosingReason.VOLITIONAL
                    slc = await plm.reduce_position(
                        position_id=existing.id,
                        requested_qty=qty if qty > 0 else float(existing.open_qty or 0),
                        closing_reason=cr,
                        signal_id=str(signal.get("signal_id") or signal.get("id") or ""),
                        signal_db_id=int(signal.get("id") or 0) or None,
                        intent_id=execution_intent_id,
                        execution_path=execution_path,
                        order_id=order_id,
                    )
                    _pos_id = existing.id
                    _slc_id = slc.id

            # Back-link execution_intent → position / slice
            if _pos_id and execution_intent_id:
                try:
                    from sqlalchemy import update as _sa_upd
                    from app.models.execution_intent import AutonomousExecutionIntent
                    await db.execute(
                        _sa_upd(AutonomousExecutionIntent)
                        .where(AutonomousExecutionIntent.intent_id == execution_intent_id)
                        .values(position_id=_pos_id, execution_slice_id=_slc_id)
                    )
                    await db.commit()
                except Exception as _lnk_err:
                    logger.warning(
                        "[AutonomousEngine] intent→position link failed (non-fatal): %s",
                        _lnk_err,
                    )
                    try:
                        await db.rollback()
                    except Exception:
                        pass

        except Exception as plm_err:
            logger.warning(
                "[AutonomousEngine] _integrate_position_lifecycle failed (non-fatal): %s",
                plm_err,
                exc_info=True,
            )

'''

with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

ANCHOR = "    async def _create_plan_for_executed_signal("
if ANCHOR not in content:
    print("ERROR: anchor not found")
    sys.exit(1)

new_content = content.replace(ANCHOR, NEW_METHOD + ANCHOR, 1)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(new_content)

print("DONE: _integrate_position_lifecycle inserted.")
