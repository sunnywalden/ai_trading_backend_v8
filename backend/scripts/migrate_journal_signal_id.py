import asyncio
from sqlalchemy import text
from app.models.db import engine


async def migrate():
    """为 trade_journal 表添加缺失的 signal_id 列"""
    print("Connecting to database to check trade_journal table...")
    async with engine.begin() as conn:
        # 检查列是否存在
        result = await conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'trade_journal'
                  AND column_name = 'signal_id'
                """
            )
        )
        exists = (result.scalar() or 0) > 0

        if not exists:
            print("Column 'signal_id' missing in 'trade_journal'. Adding it now...")
            await conn.execute(
                text("ALTER TABLE trade_journal ADD COLUMN signal_id VARCHAR(64) NULL AFTER journal_status")
            )
            print("✓ Column 'signal_id' added successfully.")
        else:
            print("• Column 'signal_id' already exists in 'trade_journal'. No action needed.")


if __name__ == "__main__":
    asyncio.run(migrate())
