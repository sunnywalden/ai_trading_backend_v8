# Scheduler（定时任务与手动触发）

本项目使用 APScheduler 维护周期任务，启动时由 `backend/app/main.py` 的 lifespan 初始化并启动。

## 查看任务

- `GET /admin/scheduler/jobs`

响应中包含 `jobs[]`，每项包含 `id/name/next_run_time/trigger/paused` 等。

## 暂停/恢复任务

- `POST /admin/scheduler/jobs/{job_id}/pause`
- `POST /admin/scheduler/jobs/{job_id}/resume`

## 修改任务计划（cron）

- `PUT /admin/scheduler/jobs/{job_id}/schedule`

请求体：`JobScheduleRequest`（cron 表达式为 Linux crontab 5 段）。

## Opportunities 扫描相关

`POST /api/v1/opportunities/scan` 支持在请求中传入：
- `schedule_cron`
- `schedule_timezone`

它会尝试 reschedule 固定 job id：`scan_daily_opportunities_tech`，并在响应 `notes` 中返回 scheduler 变更信息。
