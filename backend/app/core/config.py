from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "AI Trading Risk & Auto-Hedge System"

    # 交易模式：OFF / DRY_RUN / REAL
    TRADE_MODE: str = "DRY_RUN"

    # 券商账户（老虎）
    # 模拟账户
    TIGER_ACCOUNT: str | None = None

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
    OPENAI_MODEL: str = "gpt-5.1"

    class Config:
        env_file = ".env"


settings = Settings()
