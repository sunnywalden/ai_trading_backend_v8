import asyncio
from sqlalchemy import text
from app.models.db import SessionLocal

async def migrate_db():
    print("开始检查并更新数据库字段...")
    async with SessionLocal() as session:
        # FundamentalData 表更新
        for col, col_type in [("sector", "VARCHAR(64)"), ("industry", "VARCHAR(128)"), ("beta", "FLOAT")]:
            try:
                await session.execute(text(f"ALTER TABLE fundamental_data ADD COLUMN {col} {col_type}"))
                print(f"fundamental_data ADD COLUMN {col} 成功")
            except Exception:
                # 忽略已存在的列错误
                pass

        # PositionScore 表更新
        for col, col_type in [("sector", "VARCHAR(64)"), ("industry", "VARCHAR(128)"), ("beta", "FLOAT")]:
            try:
                await session.execute(text(f"ALTER TABLE position_scores ADD COLUMN {col} {col_type}"))
                print(f"position_scores ADD COLUMN {col} 成功")
            except Exception:
                # 忽略已存在的列错误
                pass

        await session.commit()
    print("数据库迁移完成。")

if __name__ == "__main__":
    asyncio.run(migrate_db())
