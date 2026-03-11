from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Locate the nearest .env starting from this file's directory
def find_env_file() -> Path | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        env_file = parent / ".env"
        if env_file.exists():
            return env_file
    return None


ENV_FILE = find_env_file()
BASE_DIR = ENV_FILE.parent if ENV_FILE else Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    APP_NAME: str = "AI Trading Risk & Auto-Hedge System"

    # 数据库配置
    DB_TYPE: str = "sqlite"  # sqlite / mysql
    SQLITE_DB_PATH: str = "./demo.db"
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "password"
    MYSQL_DB: str = "ai_trading"

    @property
    def DATABASE_URL(self) -> str:
        if self.DB_TYPE == "mysql":
            # 去掉可能的包裹引号（single/double quote）并对用户名/密码进行 URL 编码
            user = (
                quote_plus(str(self.MYSQL_USER).strip("'\"")) if self.MYSQL_USER else ""
            )
            pwd = (
                quote_plus(str(self.MYSQL_PASSWORD).strip("'\""))
                if self.MYSQL_PASSWORD
                else ""
            )
            return (
                f"mysql+aiomysql://{user}:{pwd}@{self.MYSQL_HOST}:"
                f"{self.MYSQL_PORT}/{self.MYSQL_DB}"
            )

        # 处理 SQLite 路径解析逻辑
        path = self.SQLITE_DB_PATH
        if path.startswith("./"):
            path = str((BASE_DIR / path[2:]).resolve())
        elif not Path(path).is_absolute():
            path = str((BASE_DIR / path).resolve())

        return f"sqlite+aiosqlite:///{path}"

    # Redis 配置
    REDIS_HOST: str = "192.168.2.233"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0
    REDIS_ENABLED: bool = True

    @property
    def REDIS_URL(self) -> str:
        password_str = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return (
            f"redis://{password_str}{self.REDIS_HOST}:{self.REDIS_PORT}/"
            f"{self.REDIS_DB}"
        )

    # 交易模式：OFF / DRY_RUN / REAL
    TRADE_MODE: str = "DRY_RUN"

    # 券商账户（老虎）
    TIGER_ACCOUNT: str = "demo-account"

    # Tiger Open API 相关配置（使用 tigeropen SDK）
    # PRIVATE_KEY_PATH：RSA 私钥文件路径（.pem 格式）
    # TIGER_ID：开发者 ID（从老虎开放平台获取）
    # 例如: "/path/to/your_private_key.pem"
    TIGER_PRIVATE_KEY_PATH: str | None = None
    TIGER_ID: str | None = None

    # 行情数据模式配置
    # DELAYED: 免费延迟行情（约15-20分钟延迟，适合开发测试）
    # REALTIME: 实时行情（需付费订阅，生产环境必须）
    TIGER_QUOTE_MODE: str = "DELAYED"

    # 是否在 API 响应中显示数据延迟警告
    QUOTE_DATA_WARNING: bool = True

    # LLM / OpenAI 配置（用于 AI 决策助手）
    OPENAI_API_KEY: str | None = None
    # 可选：OpenAI API Base（代理/镜像/自建网关）。示例：https://your-proxy-url.com/v1
    # 兼容文档中的 OPENAI_API_BASE 配置。
    OPENAI_API_BASE: str | None = None
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_MAX_TOKENS: int = 500
    OPENAI_TIMEOUT_SECONDS: int = 30

    # DeepSeek API 配置（兜底方案）
    # DeepSeek API 完全兼容 OpenAI 格式，用作备用 AI 能力
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"  # 或 "deepseek-reasoner" (思考模式)
    DEEPSEEK_ENABLED: bool = True  # 是否启用 DeepSeek 作为兜底
    DEEPSEEK_TIMEOUT_SECONDS: int = 90  # DeepSeek 超时时间（reasoner 模式需要更长时间）

    # AI 提供商策略配置
    # 可用的提供商列表，逗号分隔
    AI_PROVIDERS: str = "openai,deepseek"
    # 优先使用的提供商（如果存在于 AI_PROVIDERS 中，则会被移到首位）
    AI_PREFERRED_PROVIDER: str = "openai"

    # ==================== 网络代理配置 ====================
    # 通过配置管理代理开关；启用后会在应用启动时设置 HTTP(S)_PROXY/NO_PROXY 环境变量，
    # 使 OpenAI SDK、fredapi（requests）等都能通过代理访问。
    PROXY_ENABLED: bool = False
    HTTP_PROXY: str | None = None
    HTTPS_PROXY: str | None = None
    NO_PROXY: str | None = None

    # ==================== CORS 配置 ====================
    # 生产环境应通过环境变量覆盖；默认覆盖本地开发与当前生产域名。
    CORS_ALLOW_ORIGINS: Any = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "https://sunnywalden.com",
        "https://www.sunnywalden.com",
        "https://api.sunnywalden.com",
    ]
    CORS_ALLOW_ORIGIN_REGEX: str | None = None

    # ==================== 认证配置（默认启用） ====================
    # 是否开启认证（默认 True）。在生产环境请通过环境变量覆盖默认用户名/密码。
    AUTH_ENABLED: bool = True
    ADMIN_USERNAME: str = "admin"
    # 必须通过环境变量或 .env 显式设置，避免回退到弱口令默认值
    ADMIN_PASSWORD: str | None = None
    # 用于签发 JWT token 的密钥，请在部署时设置为强随机值
    JWT_SECRET_KEY: str = "change-me-please"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    STRATEGY_EXECUTE_USERS: Any = ["admin"]
    STRATEGY_MANAGE_USERS: Any = ["admin"]
    EXPORT_ROOT: str = "./exports"

    # FRED API 配置（宏观经济数据）
    FRED_API_KEY: str | None = None

    # News API 配置（地缘政治事件）
    NEWS_API_KEY: str | None = None

    # 数据缓存配置（小时）
    CACHE_TTL_TECHNICAL_HOURS: int = 1
    CACHE_TTL_FUNDAMENTAL_HOURS: int = 24
    CACHE_TTL_MACRO_HOURS: int = 6
    CACHE_TTL_GEOPOLITICAL_HOURS: int = 4

    # 风险预算（用于持仓评估预算占用率）
    DEFAULT_RISK_BUDGET_USD: float = 20000.0

    # 并发控制配置（中期优化）
    EXTERNAL_API_CONCURRENCY: int = 5  # 外部API并发上限
    REFRESH_CONCURRENCY: int = 5  # 刷新任务并发上限

    # 外部 API 限流规避配置
    API_RATE_LIMIT_COOLDOWN_SECONDS: int = 900  # 触发限流后冷却时间（秒）

    # 定时任务配置
    ENABLE_SCHEDULER: bool = True
    SCHEDULER_TECHNICAL_HOURS: int = 1
    SCHEDULER_FUNDAMENTAL_HOURS: int = 24
    SCHEDULER_MACRO_HOURS: int = 24
    SCHEDULER_GEOPOLITICAL_HOURS: int = 4
    SCHEDULER_RISK_HOURS: int = 6

    # ==================== V9: 新增配置 ====================
    # 订单模式：OFF / PAPER / REAL
    ORDER_MODE: str = "PAPER"
    # 单笔订单最大占净值比例
    MAX_SINGLE_ORDER_PCT: float = 0.2
    # 日亏损熔断阈值
    MAX_DAILY_LOSS_PCT: float = 0.05
    # Telegram 通知
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    # 权益快照定时（小时）
    SCHEDULER_EQUITY_SNAPSHOT_HOURS: int = 24
    # 告警检查间隔（分钟）
    SCHEDULER_ALERT_CHECK_MINUTES: int = 5

    # ==================== V10: AI 自主闭环配置 ====================
    # AI 自主级别：FULL（全自主）/ SEMI（半自主，默认）/ ADVISORY（仅建议）
    AI_AUTONOMY_LEVEL: str = "SEMI"

    # 允许交易的标的类型：STOCK / ALL（ALL 包含期权，谨慎开启）
    ALLOWED_ASSET_TYPES: str = "STOCK"

    # 风险门边界（不可绕过）
    MAX_SINGLE_POSITION_PCT: float = 0.25  # 单标的最大仓位占比
    MAX_VAR_PCT: float = 0.03  # 投资组合 VaR@95% 上限
    MAX_STRESS_LOSS_PCT: float = 0.15  # 压力测试最大损失占比
    MAX_DAILY_TRADES: int = 10  # 单日最大自主交易笔数
    ALLOW_CLOSING_DURING_CIRCUIT_BREAKER: bool = True  # 熔断期间允许减仓/平仓
    EXIT_ORDER_COOLDOWN_MINUTES: int = 5  # 减仓/平仓方向最短冷却（分钟）
    EXIT_ORDER_LOCK_SECONDS: int = 30  # 减仓/平仓 Redis 并发锁（秒）

    # 半自主模式：撤单窗口（分钟）
    REVOKE_WINDOW_MINUTES: int = 30

    # Paper Trading 配置
    PAPER_INITIAL_CAPITAL: float = 100000.0
    PAPER_AUTO_GRADUATE: bool = True  # 达标后是否自动建议升级 Live

    # DataHub 数据源优先级
    DATA_HUB_PRIMARY: str = "yfinance"  # yfinance / tiger
    DATA_HUB_FALLBACK: str = "tiger"  # 主源失败时使用

    # 期权分析缓存时间（小时）
    OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS: int = 24

    # AI 模型路由（轻量 vs 复杂推理）
    AI_LIGHTWEIGHT_MODEL: str = "deepseek-chat"  # 轻量查询/摘要
    AI_COMPLEX_MODEL: str = "deepseek-reasoner"  # 深度推理/自主决策

    # 回测配置
    BACKTEST_MAX_CONCURRENT: int = 3  # 最大并发回测任务数
    BACKTEST_COMMISSION_PCT: float = 0.001  # 模拟佣金 0.1%
    BACKTEST_SLIPPAGE_PCT: float = 0.0005  # 模拟滑点 0.05%

    # 持仓监控 & 自动止损/止盈
    POSITION_STOP_LOSS_PCT: float = 0.05  # 止损阈值：浮亏 >= 5% 触发 EXIT 信号
    POSITION_TAKE_PROFIT_PCT: float = 0.15  # 止盈阈值：浮盈 >= 15% 触发 EXIT 信号
    POSITION_MONITOR_INTERVAL_MINUTES: int = 15  # 持仓扫描间隔（分钟）
    POSITION_CAPACITY_GUARD_INTERVAL_MINUTES: int = (
        15  # 超并发持仓主动降载扫描间隔（分钟）
    )

    # 券商订单状态自动对账（用于回写手动撤单/成交结果）
    BROKER_ORDER_SYNC_INTERVAL_MINUTES: int = 10
    BROKER_ORDER_SYNC_LOOKBACK_DAYS: int = 3

    # 态势感知栏：围栏统计向前展望天数（默认 30 天）
    SA_FENCE_LOOKAHEAD_DAYS: int = 30

    # AI 周报定时（每周一 08:00 生成上周复盘）
    SCHEDULER_WEEKLY_REPORT_DAY: str = "mon"
    SCHEDULER_WEEKLY_REPORT_HOUR: int = 8

    # ==================== V10.2-M1: 市场体制感知配置 ====================
    # 是否启用市场体制分类（关闭后体制固定为 BULL_TREND，不影响其他模块）
    REGIME_ENABLED: bool = True

    # 体制「连续确认」天数：连续 N 天同一体制信号才切换（防止噪声翻转）
    REGIME_CONFIRM_DAYS: int = 3

    # 各体制下的 VaR 门限倍数（相对于 MAX_VAR_PCT）。
    # 格式："BULL_TREND:1.2,BEAR_TREND:0.8,HIGH_VOL:0.7,MEAN_REVERT:1.0,RANGE_BOUND:1.0,CRISIS:0.5"
    REGIME_VAR_MULTIPLIERS: str = (
        "BULL_TREND:1.2,BEAR_TREND:0.8,HIGH_VOL:0.7,"
        "MEAN_REVERT:1.0,RANGE_BOUND:1.0,CRISIS:0.5"
    )

    # 每日体制分类 Job 触发小时（UTC+0 系统时间，默认 08:00 港股/美股开盘前）
    REGIME_CLASSIFICATION_HOUR: int = 8

    # ==================== 宏观风险建议参数化配置 ====================
    # RISK_OFF 场景下风险资产仓位上限（相对常态）建议区间
    MACRO_RISK_OFF_POSITION_CAP_MIN: float = 0.50
    MACRO_RISK_OFF_POSITION_CAP_MAX: float = 0.70
    # RISK_OFF 场景下止损收紧比例（相对常态）
    MACRO_RISK_OFF_STOP_TIGHTEN_PCT: float = 0.20
    # CAUTIOUS 场景下建议保留现金比例区间
    MACRO_CAUTIOUS_CASH_BUFFER_MIN: float = 0.10
    MACRO_CAUTIOUS_CASH_BUFFER_MAX: float = 0.20

    # ==================== V10.5.3: Profit Engine Upgrade
    # Feature Flags ====================
    ALPHA_TRUTH_V2_ENABLED: bool = True
    SEAT_VALUE_ARBITER_ENABLED: bool = False
    EXECUTION_POLICY_HARD_CONTROL_ENABLED: bool = False
    GOVERNANCE_HARD_GATE_ENABLED: bool = False

    # ==================== V10.5.4: Signal Pipeline Integrity &
    # Control-Plane Hardening ====================
    SIGNAL_PIPELINE_V1054_ENABLED: bool = False
    AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED: bool = False
    NATIVE_AUDIT_V1054_ENABLED: bool = False

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE else ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator(
        "STRATEGY_EXECUTE_USERS",
        "STRATEGY_MANAGE_USERS",
        "CORS_ALLOW_ORIGINS",
        mode="before",
    )
    @classmethod
    def _parse_user_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            # 支持逗号分隔
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("TIGER_PRIVATE_KEY_PATH", mode="before")
    @classmethod
    def _resolve_private_key_path(cls, value: str | Path | None) -> str | None:
        if not value:
            return None
        resolved_path = Path(value)
        if not resolved_path.is_absolute():
            resolved_path = BASE_DIR / resolved_path
        return str(resolved_path)

    @model_validator(mode="after")
    def _validate_auth_settings(self) -> "Settings":
        if self.AUTH_ENABLED and not (self.ADMIN_PASSWORD or "").strip():
            raise ValueError("ADMIN_PASSWORD must be set when AUTH_ENABLED=true")
        return self


settings = Settings()
