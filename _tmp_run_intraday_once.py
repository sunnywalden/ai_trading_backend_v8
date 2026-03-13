import asyncio
from app.jobs.quant_loop_jobs import run_intraday_signal_cycle

if __name__ == "__main__":
    asyncio.run(run_intraday_signal_cycle())
