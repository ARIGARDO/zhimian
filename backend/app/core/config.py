from functools import lru_cache

from pydantic import SecretStr
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

    @property
    def allowed_origins(self) -> list[str]:
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
