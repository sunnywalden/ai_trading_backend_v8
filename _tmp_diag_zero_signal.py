import asyncio
from sqlalchemy import text, bindparam
from app.models.db import SessionLocal

RUN_IDS = [
    "026124b1-42f4-4482-8a2c-6b9be2ef34b4",
    "90ae84f6-186f-4074-8356-6879bceb2d2a",
    "6f2cd85b-71da-4865-8f71-a446950214a6",
]
ACCOUNT_ID = "21272246230273657"


async def main() -> None:
    async with SessionLocal() as s:
        q1 = text(
            """
            SELECT sr.id, sr.target_universe, sr.status,
                   st.name AS strategy_name, st.style, st.is_active, st.auto_scan_enabled
            FROM strategy_runs sr
            LEFT JOIN strategies st ON st.id = sr.strategy_id
            WHERE sr.id IN :run_ids
            ORDER BY sr.created_at ASC
            """
        ).bindparams(bindparam("run_ids", expanding=True))
        rows = (await s.execute(q1, {"run_ids": RUN_IDS})).mappings().all()
        print("RUNS:")
        for row in rows:
            print(dict(row))

        q2 = text(
            """
            SELECT COUNT(*) AS cnt
            FROM technical_indicators
            WHERE DATE(timestamp) = CURDATE()
              AND (symbol REGEXP '^[0-9]{5}$' OR symbol LIKE '%.HK')
            """
        )
        print("\nHK_TECH_TODAY:", dict((await s.execute(q2)).mappings().one()))

        q3 = text(
            """
            SELECT symbol, timeframe, timestamp, ma_50, ma_200, bb_upper, bb_lower, atr_14
            FROM technical_indicators
            WHERE DATE(timestamp) = CURDATE()
              AND (symbol REGEXP '^[0-9]{5}$' OR symbol LIKE '%.HK')
            ORDER BY timestamp DESC
            LIMIT 10
            """
        )
        rows3 = (await s.execute(q3)).mappings().all()
        print("HK_TECH_SAMPLE:")
        for row in rows3:
            print(dict(row))

        q4 = text(
            """
            SELECT signal_origin_mode, status, COUNT(*) AS cnt
            FROM trading_signals
            WHERE account_id = :account_id
              AND status IN ('GENERATED', 'VALIDATED', 'QUEUED')
            GROUP BY signal_origin_mode, status
            ORDER BY signal_origin_mode, status
            """
        )
        rows4 = (await s.execute(q4, {"account_id": ACCOUNT_ID})).mappings().all()
        print("\nPENDING_SIGNALS:")
        for row in rows4:
            print(dict(row))


if __name__ == "__main__":
    asyncio.run(main())
