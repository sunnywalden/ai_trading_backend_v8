"""Patch autonomous_engine.py: add Position lifecycle integration call (V10.4.4)."""

import os
import re
import sys

TARGET = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "autonomous_engine.py"
)

with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

MARKER = '                        if level == "SEMI":\n                            await self._schedule_revoke_window(account_id, order_id)\n                        # 执行成功后，自动写入 TradingPlan 供生命周期中心观测'
REPLACEMENT = (
    '                        if level == "SEMI":\n'
    "                            await self._schedule_revoke_window(account_id, order_id)\n"
    "                        # V10.4.4: Position-centric 生命周期整合\n"
    "                        await self._integrate_position_lifecycle(\n"
    "                            db=db,\n"
    "                            account_id=account_id,\n"
    "                            signal=signal,\n"
    "                            decision=decision,\n"
    "                            execution_intent_id=execution_intent_id,\n"
    "                            execution_path=execution_path,\n"
    "                            autonomy_level=level,\n"
    "                            order_id=order_id,\n"
    "                        )\n"
    "                        # 执行成功后，自动写入 TradingPlan 供生命周期中心观测"
)

if MARKER not in content:
    print("ERROR: marker not found in file")
    sys.exit(1)

count = content.count(MARKER)
if count != 1:
    print(f"ERROR: marker found {count} times (expected 1)")
    sys.exit(1)

new_content = content.replace(MARKER, REPLACEMENT, 1)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(new_content)

print("DONE: PLM integration call inserted.")
