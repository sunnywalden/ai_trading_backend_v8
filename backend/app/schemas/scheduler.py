from pydantic import BaseModel, Field


class JobScheduleRequest(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="计划执行的小时")
    minute: int = Field(..., ge=0, le=59, description="计划执行的分钟")
    timezone: str = Field("Asia/Shanghai", description="Cron 表达式所参考的时区")
