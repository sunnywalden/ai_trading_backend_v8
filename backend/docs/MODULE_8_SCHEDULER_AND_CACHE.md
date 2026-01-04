# 模块8: 定时任务和缓存策略设计

## 1. 概述

### 职责
- 定时刷新技术指标数据
- 定时刷新基本面数据
- 定时刷新宏观经济指标
- 定时抓取地缘政治事件
- 管理数据缓存策略
- 清理过期数据

### 技术栈
- **APScheduler** - 定时任务调度
- **SQLite/数据库** - 缓存存储
- **可选: Redis** - 高速缓存

---

## 2. 定时任务设计

### 2.1 任务调度器

```python
# app/jobs/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class JobScheduler:
    """定时任务调度器"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            timezone="America/New_York",  # 使用美国东部时间
            job_defaults={
                'coalesce': True,  # 合并错过的任务
                'max_instances': 1  # 同一任务最多1个实例
            }
        )
    
    def start(self):
        """启动调度器"""
        self._register_jobs()
        self.scheduler.start()
        logger.info("Job scheduler started")
    
    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown()
        logger.info("Job scheduler stopped")
    
    def _register_jobs(self):
        """注册所有定时任务"""
        
        # 1. 技术指标刷新（每小时）
        self.scheduler.add_job(
            func=refresh_technical_indicators,
            trigger=IntervalTrigger(hours=1),
            id="refresh_technical",
            name="刷新技术指标",
            replace_existing=True
        )
        
        # 2. 基本面数据刷新（每天凌晨2点）
        self.scheduler.add_job(
            func=refresh_fundamental_data,
            trigger=CronTrigger(hour=2, minute=0),
            id="refresh_fundamental",
            name="刷新基本面数据",
            replace_existing=True
        )
        
        # 3. 宏观指标刷新（每天早上9点）
        self.scheduler.add_job(
            func=refresh_macro_indicators,
            trigger=CronTrigger(hour=9, minute=0),
            id="refresh_macro",
            name="刷新宏观指标",
            replace_existing=True
        )
        
        # 4. 地缘政治事件抓取（每4小时）
        self.scheduler.add_job(
            func=fetch_geopolitical_events,
            trigger=IntervalTrigger(hours=4),
            id="fetch_geopolitical",
            name="抓取地缘政治事件",
            replace_existing=True
        )
        
        # 5. 宏观风险评分计算（每6小时）
        self.scheduler.add_job(
            func=calculate_macro_risk,
            trigger=IntervalTrigger(hours=6),
            id="calculate_macro_risk",
            name="计算宏观风险评分",
            replace_existing=True
        )
        
        # 6. 数据清理（每天凌晨3点）
        self.scheduler.add_job(
            func=cleanup_old_data,
            trigger=CronTrigger(hour=3, minute=0),
            id="cleanup_data",
            name="清理过期数据",
            replace_existing=True
        )
        
        logger.info(f"Registered {len(self.scheduler.get_jobs())} scheduled jobs")

# 全局调度器实例
scheduler = JobScheduler()
```

---

### 2.2 任务实现

#### 2.2.1 刷新技术指标

```python
# app/jobs/data_refresh_jobs.py

from app.models.db import SessionLocal
from app.services.technical_analysis_service import TechnicalAnalysisService
from app.services.account_service import AccountService
import asyncio

async def refresh_technical_indicators():
    """
    刷新技术指标
    
    策略:
    1. 获取所有活跃持仓标的
    2. 并发刷新技术指标
    3. 记录成功/失败统计
    
    执行频率: 每小时
    执行时间: 约2-5分钟
    """
    
    logger.info("Starting technical indicators refresh...")
    start_time = datetime.utcnow()
    
    try:
        async with SessionLocal() as session:
            # 1. 获取活跃标的列表
            account_service = AccountService(session, "default_account")
            positions = await account_service.get_current_positions()
            symbols = [p.symbol for p in positions]
            
            if not symbols:
                logger.info("No active positions to refresh")
                return
            
            # 2. 并发刷新
            tech_service = TechnicalAnalysisService(session)
            tasks = [
                tech_service.get_technical_analysis(symbol, use_cache=False)
                for symbol in symbols
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 3. 统计结果
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            failed_count = len(results) - success_count
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Technical indicators refresh completed: "
                f"{success_count} succeeded, {failed_count} failed "
                f"in {duration:.2f}s"
            )
            
    except Exception as e:
        logger.error(f"Technical indicators refresh failed: {e}", exc_info=True)
```

#### 2.2.2 刷新基本面数据

```python
async def refresh_fundamental_data():
    """
    刷新基本面数据
    
    策略:
    1. 获取所有标的
    2. 串行刷新（避免API限流）
    3. 失败重试
    
    执行频率: 每天凌晨2点
    执行时间: 约10-20分钟
    """
    
    logger.info("Starting fundamental data refresh...")
    start_time = datetime.utcnow()
    
    try:
        async with SessionLocal() as session:
            from app.services.fundamental_analysis_service import FundamentalAnalysisService
            
            # 获取标的列表
            account_service = AccountService(session, "default_account")
            positions = await account_service.get_current_positions()
            symbols = [p.symbol for p in positions]
            
            if not symbols:
                logger.info("No positions to refresh")
                return
            
            # 串行刷新（避免限流）
            fundamental_service = FundamentalAnalysisService(session)
            success_count = 0
            failed_count = 0
            
            for symbol in symbols:
                try:
                    await fundamental_service.get_fundamental_analysis(
                        symbol, use_cache=False
                    )
                    success_count += 1
                    
                    # 限速：每个请求间隔1秒
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Failed to refresh {symbol}: {e}")
                    failed_count += 1
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Fundamental data refresh completed: "
                f"{success_count} succeeded, {failed_count} failed "
                f"in {duration:.2f}s"
            )
            
    except Exception as e:
        logger.error(f"Fundamental data refresh failed: {e}", exc_info=True)
```

#### 2.2.3 刷新宏观指标

```python
async def refresh_macro_indicators():
    """
    刷新宏观指标
    
    策略:
    1. 从FRED API获取所有指标
    2. 保存到数据库
    
    执行频率: 每天早上9点
    执行时间: 约30-60秒
    """
    
    logger.info("Starting macro indicators refresh...")
    start_time = datetime.utcnow()
    
    try:
        async with SessionLocal() as session:
            from app.services.macro_indicators_service import MacroIndicatorsService
            
            indicators_service = MacroIndicatorsService(session)
            result = await indicators_service.refresh_all_indicators()
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Macro indicators refresh completed: "
                f"{result['success']} succeeded, {result['failed']} failed "
                f"in {duration:.2f}s"
            )
            
    except Exception as e:
        logger.error(f"Macro indicators refresh failed: {e}", exc_info=True)
```

#### 2.2.4 抓取地缘政治事件

```python
async def fetch_geopolitical_events():
    """
    抓取地缘政治事件
    
    策略:
    1. 从News API获取最新新闻
    2. 分类和评估
    3. 去重后保存
    
    执行频率: 每4小时
    执行时间: 约10-20秒
    """
    
    logger.info("Starting geopolitical events fetch...")
    start_time = datetime.utcnow()
    
    try:
        async with SessionLocal() as session:
            from app.services.geopolitical_events_service import GeopoliticalEventsService
            
            geo_service = GeopoliticalEventsService(session)
            events = await geo_service.fetch_recent_events(days=1)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Geopolitical events fetch completed: "
                f"{len(events)} events fetched in {duration:.2f}s"
            )
            
    except Exception as e:
        logger.error(f"Geopolitical events fetch failed: {e}", exc_info=True)
```

#### 2.2.5 计算宏观风险

```python
async def calculate_macro_risk():
    """
    计算宏观风险评分
    
    策略:
    1. 计算5维度风险
    2. 生成综合评分
    3. 保存到数据库
    
    执行频率: 每6小时
    执行时间: 约5-10秒
    """
    
    logger.info("Starting macro risk calculation...")
    start_time = datetime.utcnow()
    
    try:
        async with SessionLocal() as session:
            from app.services.macro_risk_scoring_service import MacroRiskScoringService
            
            risk_service = MacroRiskScoringService(session)
            result = await risk_service.get_macro_risk_overview(use_cache=False)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Macro risk calculation completed: "
                f"score={result.overall_risk.score}, "
                f"level={result.overall_risk.level} "
                f"in {duration:.2f}s"
            )
            
    except Exception as e:
        logger.error(f"Macro risk calculation failed: {e}", exc_info=True)
```

#### 2.2.6 清理过期数据

```python
async def cleanup_old_data():
    """
    清理过期数据
    
    策略:
    1. 删除90天前的技术指标
    2. 删除180天前的基本面数据
    3. 删除30天前的地缘政治事件
    4. 删除90天前的风险评分
    
    执行频率: 每天凌晨3点
    执行时间: 约10-30秒
    """
    
    logger.info("Starting old data cleanup...")
    start_time = datetime.utcnow()
    
    try:
        async with SessionLocal() as session:
            from sqlalchemy import delete
            from datetime import timedelta
            
            cutoff_dates = {
                "technical_indicators": datetime.utcnow() - timedelta(days=90),
                "fundamental_data": datetime.utcnow() - timedelta(days=180),
                "geopolitical_events": datetime.utcnow() - timedelta(days=30),
                "macro_risk_scores": datetime.utcnow() - timedelta(days=90)
            }
            
            deleted_counts = {}
            
            # 删除技术指标
            from app.models.technical_indicator import TechnicalIndicator
            stmt = delete(TechnicalIndicator).where(
                TechnicalIndicator.timestamp < cutoff_dates["technical_indicators"]
            )
            result = await session.execute(stmt)
            deleted_counts["technical_indicators"] = result.rowcount
            
            # 删除基本面数据
            from app.models.fundamental_data import FundamentalData
            stmt = delete(FundamentalData).where(
                FundamentalData.timestamp < cutoff_dates["fundamental_data"]
            )
            result = await session.execute(stmt)
            deleted_counts["fundamental_data"] = result.rowcount
            
            # 删除地缘政治事件
            from app.models.macro_risk import GeopoliticalEvent
            stmt = delete(GeopoliticalEvent).where(
                GeopoliticalEvent.timestamp < cutoff_dates["geopolitical_events"]
            )
            result = await session.execute(stmt)
            deleted_counts["geopolitical_events"] = result.rowcount
            
            # 删除风险评分
            from app.models.macro_risk import MacroRiskScore
            stmt = delete(MacroRiskScore).where(
                MacroRiskScore.timestamp < cutoff_dates["macro_risk_scores"]
            )
            result = await session.execute(stmt)
            deleted_counts["macro_risk_scores"] = result.rowcount
            
            await session.commit()
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"Old data cleanup completed: "
                f"{sum(deleted_counts.values())} records deleted "
                f"in {duration:.2f}s. Details: {deleted_counts}"
            )
            
    except Exception as e:
        logger.error(f"Old data cleanup failed: {e}", exc_info=True)
```

---

## 3. 缓存策略设计

### 3.1 缓存层次

```
┌─────────────────────┐
│  Application Cache  │ ← Python内存缓存（LRU）
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Database Cache    │ ← SQLite持久化缓存
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  External APIs      │ ← 原始数据源
└─────────────────────┘
```

### 3.2 缓存时长配置

```python
# app/core/cache_config.py

from datetime import timedelta

class CacheConfig:
    """缓存配置"""
    
    # 技术指标缓存（1小时）
    TECHNICAL_INDICATORS = timedelta(hours=1)
    
    # 基本面数据缓存（1天）
    FUNDAMENTAL_DATA = timedelta(days=1)
    
    # 持仓评分缓存（1小时）
    POSITION_SCORES = timedelta(hours=1)
    
    # 宏观指标缓存（6小时）
    MACRO_INDICATORS = timedelta(hours=6)
    
    # 地缘政治事件缓存（4小时）
    GEOPOLITICAL_EVENTS = timedelta(hours=4)
    
    # 宏观风险评分缓存（6小时）
    MACRO_RISK_SCORES = timedelta(hours=6)
    
    # AI分析摘要缓存（1小时）
    AI_SUMMARIES = timedelta(hours=1)
```

### 3.3 缓存失效策略

```python
# app/services/cache_service.py

from typing import Optional, Any
from datetime import datetime

class CacheService:
    """统一缓存服务"""
    
    @staticmethod
    def is_cache_valid(
        timestamp: datetime,
        ttl: timedelta
    ) -> bool:
        """检查缓存是否有效"""
        return (datetime.utcnow() - timestamp) < ttl
    
    @staticmethod
    async def invalidate_cache(
        session: AsyncSession,
        model_class: Any,
        filters: dict
    ) -> int:
        """失效指定缓存"""
        from sqlalchemy import delete
        
        stmt = delete(model_class)
        for key, value in filters.items():
            stmt = stmt.where(getattr(model_class, key) == value)
        
        result = await session.execute(stmt)
        await session.commit()
        
        return result.rowcount
    
    @staticmethod
    async def clear_all_cache(session: AsyncSession) -> dict:
        """清空所有缓存"""
        from sqlalchemy import delete
        
        models = [
            TechnicalIndicator,
            FundamentalData,
            PositionScore,
            MacroIndicator,
            GeopoliticalEvent,
            MacroRiskScore
        ]
        
        counts = {}
        for model in models:
            result = await session.execute(delete(model))
            counts[model.__tablename__] = result.rowcount
        
        await session.commit()
        return counts
```

---

## 4. 启动和关闭

### 4.1 应用启动时

```python
# app/main.py

from contextlib import asynccontextmanager
from app.jobs.scheduler import scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    
    # 启动时
    logger.info("Starting application...")
    
    # 启动定时任务调度器
    scheduler.start()
    
    yield
    
    # 关闭时
    logger.info("Shutting down application...")
    
    # 关闭调度器
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
```

### 4.2 手动触发任务

```python
# app/routers/admin.py (管理员端点)

from fastapi import APIRouter, Depends
from app.jobs.data_refresh_jobs import *

admin_router = APIRouter(prefix="/admin", tags=["管理员"])

@admin_router.post("/jobs/trigger/{job_name}")
async def trigger_job(
    job_name: str,
    _: str = Depends(verify_admin)  # 管理员权限验证
):
    """手动触发定时任务"""
    
    job_functions = {
        "technical": refresh_technical_indicators,
        "fundamental": refresh_fundamental_data,
        "macro": refresh_macro_indicators,
        "geopolitical": fetch_geopolitical_events,
        "risk": calculate_macro_risk,
        "cleanup": cleanup_old_data
    }
    
    if job_name not in job_functions:
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        await job_functions[job_name]()
        return {"success": True, "message": f"Job {job_name} triggered"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 5. 监控和日志

### 5.1 任务执行日志

```python
# app/jobs/job_monitor.py

from datetime import datetime
from typing import Optional

class JobExecutionLog:
    """任务执行日志"""
    
    def __init__(self, job_name: str):
        self.job_name = job_name
        self.start_time = datetime.utcnow()
        self.end_time: Optional[datetime] = None
        self.status = "running"
        self.error: Optional[str] = None
        self.metrics = {}
    
    def success(self, metrics: dict = None):
        """记录成功"""
        self.end_time = datetime.utcnow()
        self.status = "success"
        self.metrics = metrics or {}
        self._log()
    
    def failure(self, error: str):
        """记录失败"""
        self.end_time = datetime.utcnow()
        self.status = "failed"
        self.error = error
        self._log()
    
    def _log(self):
        """写入日志"""
        duration = (self.end_time - self.start_time).total_seconds()
        
        log_msg = (
            f"Job '{self.job_name}' {self.status} "
            f"in {duration:.2f}s"
        )
        
        if self.metrics:
            log_msg += f" | Metrics: {self.metrics}"
        
        if self.error:
            log_msg += f" | Error: {self.error}"
        
        if self.status == "success":
            logger.info(log_msg)
        else:
            logger.error(log_msg)

# 使用示例
async def refresh_technical_indicators():
    job_log = JobExecutionLog("refresh_technical")
    
    try:
        # ... 执行任务 ...
        job_log.success({"symbols_count": 10, "success_count": 9})
    except Exception as e:
        job_log.failure(str(e))
        raise
```

### 5.2 性能监控

```python
# app/jobs/job_metrics.py

class JobMetrics:
    """任务性能指标"""
    
    _metrics = {}
    
    @classmethod
    def record_execution(cls, job_name: str, duration: float, success: bool):
        """记录执行"""
        if job_name not in cls._metrics:
            cls._metrics[job_name] = {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "total_duration": 0,
                "average_duration": 0,
                "last_execution": None
            }
        
        metrics = cls._metrics[job_name]
        metrics["total_executions"] += 1
        
        if success:
            metrics["successful_executions"] += 1
        else:
            metrics["failed_executions"] += 1
        
        metrics["total_duration"] += duration
        metrics["average_duration"] = (
            metrics["total_duration"] / metrics["total_executions"]
        )
        metrics["last_execution"] = datetime.utcnow()
    
    @classmethod
    def get_metrics(cls, job_name: Optional[str] = None):
        """获取指标"""
        if job_name:
            return cls._metrics.get(job_name)
        return cls._metrics
```

---

## 6. 实现检查清单

- [ ] 创建 `app/jobs/scheduler.py` - 调度器
- [ ] 创建 `app/jobs/data_refresh_jobs.py` - 刷新任务
- [ ] 实现6个定时任务函数
- [ ] 创建 `app/core/cache_config.py` - 缓存配置
- [ ] 创建 `app/services/cache_service.py` - 缓存服务
- [ ] 在 `app/main.py` 中集成调度器
- [ ] 实现任务监控和日志
- [ ] 添加管理员端点（手动触发）
- [ ] 编写任务单元测试
- [ ] 性能测试（确保不影响主服务）
- [ ] 文档：任务执行时间表

---

## 7. 任务执行时间表

| 任务 | 执行频率 | 执行时间（EST） | 预计耗时 | 优先级 |
|------|---------|----------------|----------|--------|
| 技术指标刷新 | 每小时 | 整点 | 2-5分钟 | P0 |
| 基本面刷新 | 每天 | 凌晨2:00 | 10-20分钟 | P1 |
| 宏观指标刷新 | 每天 | 早上9:00 | 30-60秒 | P0 |
| 地缘事件抓取 | 每4小时 | 0/4/8/12/16/20 | 10-20秒 | P1 |
| 风险评分计算 | 每6小时 | 0/6/12/18 | 5-10秒 | P0 |
| 数据清理 | 每天 | 凌晨3:00 | 10-30秒 | P2 |

---

**预计工作量**: 6-8小时
**优先级**: P0 (核心功能)
**依赖**: 所有Service层完成

**注意事项**:
1. 确保任务不会在交易时段造成性能影响
2. 实现任务失败重试机制
3. 监控任务执行时长，设置超时告警
4. 定期检查数据库大小，及时清理
