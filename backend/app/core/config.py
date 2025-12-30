from pathlib import Path
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
    OPENAI_MODEL: str = "gpt-4"

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


settings = Settings()
