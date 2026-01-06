from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from pydantic import field_validator
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
    # 默认使用项目根目录下的 demo.db（SQLite, async）
    DATABASE_URL: str = "sqlite+aiosqlite:///./demo.db"

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

    # ==================== 网络代理配置 ====================
    # 通过配置管理代理开关；启用后会在应用启动时设置 HTTP(S)_PROXY/NO_PROXY 环境变量，
    # 使 OpenAI SDK、fredapi（requests）等都能通过代理访问。
    PROXY_ENABLED: bool = False
    HTTP_PROXY: str | None = None
    HTTPS_PROXY: str | None = None
    NO_PROXY: str | None = None

    # FRED API 配置（宏观经济数据）
    FRED_API_KEY: str | None = None

    # News API 配置（地缘政治事件）
    NEWS_API_KEY: str | None = None

    # 数据缓存配置（小时）
    CACHE_TTL_TECHNICAL_HOURS: int = 1
    CACHE_TTL_FUNDAMENTAL_HOURS: int = 24
    CACHE_TTL_MACRO_HOURS: int = 6
    CACHE_TTL_GEOPOLITICAL_HOURS: int = 4

    # 定时任务配置
    ENABLE_SCHEDULER: bool = True
    SCHEDULER_TECHNICAL_HOURS: int = 1
    SCHEDULER_FUNDAMENTAL_HOURS: int = 24
    SCHEDULER_MACRO_HOURS: int = 24
    SCHEDULER_GEOPOLITICAL_HOURS: int = 4
    SCHEDULER_RISK_HOURS: int = 6

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE else ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @field_validator("TIGER_PRIVATE_KEY_PATH", mode="before")
    @classmethod
    def _resolve_private_key_path(cls, value: str | Path | None) -> str | None:
        if not value:
            return None
        resolved_path = Path(value)
        if not resolved_path.is_absolute():
            resolved_path = BASE_DIR / resolved_path
        return str(resolved_path)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _resolve_database_url(cls, value: str | None) -> str:
        """将 SQLite URL 中的相对路径稳定解析到项目根目录。

        典型问题：
        - 在仓库根目录执行 init_db.py 会创建 ./demo.db（根目录）
        - 在 backend/ 目录启动 uvicorn 时，sqlite+aiosqlite:///./demo.db 指向 backend/demo.db

        为避免“读写不同数据库文件”，这里把 sqlite URL 的相对路径部分按 BASE_DIR 解析为绝对路径。
        """
        if not value:
            return "sqlite+aiosqlite:///./demo.db"

        # 仅处理 sqlite URL
        if not (value.startswith("sqlite+aiosqlite:///") or value.startswith("sqlite:///")):
            return value

        parts = urlsplit(value)

        # parts.path 对于 sqlite URL 形如 '/./demo.db' 或 '/Users/.../demo.db'
        raw_path = parts.path or ""
        if raw_path.startswith("/"):
            raw_path = raw_path[1:]

        path_obj = Path(raw_path)

        # 已是绝对路径（例如 'Users/...')：raw_path 不以 '.' 开头且在文件系统语义上是绝对路径时
        # 但在去掉开头 '/' 后，Path 视角不再是绝对；因此用原始 parts.path 判断。
        if parts.path.startswith("/") and not parts.path.startswith("/."):
            return value

        resolved = (BASE_DIR / path_obj).resolve()
        new_path = "/" + str(resolved)
        return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment))


settings = Settings()
