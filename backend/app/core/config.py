from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "知面 API"
    database_url: str = "postgresql+asyncpg://zhimian:change-me@localhost:5432/zhimian"
    # 本地 Vite 默认地址。单实例无账号，正式公网部署前必须增加访问保护。
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 密钥只从服务端环境读取，不向客户端返回。
    model_base_url: str = "https://api.openai.com/v1"
    model_name: str = ""
    model_api_key: SecretStr = SecretStr("")
    model_timeout: float = 60.0
    # 仅隔离验收显式启用；默认不改变供应商请求。
    model_enable_thinking: bool | None = None
    model_test_include_usage: bool = False
    model_test_ledger_path: str | None = None
    # M3 单操作总尝试次数（含首次）、输出 token 与单次最长执行时间。
    model_ai_max_attempts: int = Field(default=3, ge=1, le=10)
    model_ai_max_output_tokens: int = Field(default=1024, ge=1, le=8192)
    model_ai_max_duration_seconds: int = Field(default=120, ge=10, le=900)

    @property
    def allowed_origins(self) -> list[str]:
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
