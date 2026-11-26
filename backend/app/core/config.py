from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
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
    # 默认在本机执行，云端兼容接口需显式选择 openai。
    embedding_provider: str = 'local'
    embedding_base_url: str = ''
    embedding_model: str = 'intfloat/multilingual-e5-small'
    embedding_api_key: SecretStr = SecretStr('')
    embedding_timeout: float = 5.0
    embedding_cache_dir: str = '/tmp/zhimian-embedding-cache'
    # 仅隔离验收显式启用；默认不改变供应商请求。
    model_acceptance_mode: bool = False
    model_acceptance_isolated_account: bool = False
    model_acceptance_request_limit: int = Field(default=8, ge=1, le=8)
    model_acceptance_batch_id: str | None = None
    model_enable_thinking: bool | None = None
    model_test_include_usage: bool = False
    model_test_ledger_path: str | None = None
    # M3 单操作总尝试次数（含首次）、输出 token 与单次最长执行时间。
    model_ai_max_attempts: int = Field(default=3, ge=1, le=10)
    model_ai_max_output_tokens: int = Field(default=1024, ge=1, le=8192)
    model_ai_max_duration_seconds: int = Field(default=120, ge=10, le=900)

    @field_validator('model_enable_thinking', mode='before')
    @classmethod
    def empty_thinking_is_unset(cls, value):
        return None if value == '' else value

    @property
    def allowed_origins(self) -> list[str]:
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def model_configuration_status(url: str, name: str, key: SecretStr) -> str:
    """只检查配置格式，不访问供应商或返回密钥。"""
    if not url or not name.strip() or not key.get_secret_value().strip():
        return 'missing'
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return 'invalid_url'
        _ = parsed.port
    except ValueError:
        return 'invalid_url'
    return 'configured'
