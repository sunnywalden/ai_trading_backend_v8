import asyncio
from app.models.db import SessionLocal
from app.services.order_book_service import order_book_service

async def main():
    async with SessionLocal() as db:
        res = await order_book_service.list_orders(db)
        summary = await order_book_service.get_summary(db)
        
        # 提取分组
        groups_dict = {g.group_id: g.items for g in res.groups}
        active_items = groups_dict.get('active', [])
        monitoring_items = groups_dict.get('monitoring', [])
        completed_items = groups_dict.get('completed', [])

        print('--- VERIFICATION RESULTS ---')
        print(f'Active Count: {len(active_items)}')
        print(f'Monitoring Count: {len(monitoring_items)}')
        print(f'Completed Count: {len(completed_items)}')
        print(f'Summary Total Active: {summary.total_active}')
        
        # 验证是否有 EXECUTED + HELD 的在 active 中
        held_in_active = [r for r in active_items if r.plan_status == 'EXECUTED' and r.position_fsm_state == 'HELD']
        print(f'HELD Plans in Active group: {len(held_in_active)}')
        
        # 验证是否有 EXECUTED + CLOSED 的在 completed 中
        closed_in_completed = [r for r in completed_items if r.plan_status == 'EXECUTED' and r.position_fsm_state == 'CLOSED']
        print(f'CLOSED Plans in Completed group: {len(closed_in_completed)}')
        print('--- END ---')

if __name__ == "__main__":
    asyncio.run(main())
