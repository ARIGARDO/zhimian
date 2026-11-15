from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.learning import router as learning_router
from app.core.config import get_settings
from app.db.session import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # 无需数据库时不会提前创建 Engine；测试 /docs 等不必建立数据库连接。
    from app.db.session import get_engine as engine_factory
    if engine_factory.cache_info().currsize:
        await get_engine().dispose()


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/api/v1/health", tags=["health"])
async def health():
    return {"status": "ok", "milestone": "M1"}


@app.get("/api/v1/health/ready", tags=["health"])
async def ready():
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="数据库尚未就绪") from exc
    return {"status": "ready"}


app.include_router(learning_router, prefix="/api/v1")
