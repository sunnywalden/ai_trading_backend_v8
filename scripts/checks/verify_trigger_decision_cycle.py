"""复验：直接调用 autonomy.trigger_decision_cycle 并打印结果。"""
import asyncio

# 关键：预先导入策略模型，确保 TradingSignal 的 relationship("Strategy") 可解析
import app.models.strategy  # noqa: F401

from app.models.db import SessionLocal
from app.routers.autonomy import trigger_decision_cycle


async def main() -> None:
    async with SessionLocal() as session:
        result = await trigger_decision_cycle(
            rescue_queued=True,
            rescue_queued_minutes=3,
            session=session,
            current_user="manual-verify",
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
