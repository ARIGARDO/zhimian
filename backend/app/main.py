from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from fastapi.responses import JSONResponse
from app.api.v1.interviews import router as interview_router
from app.services.interview import InterviewConflict, InterviewNotFound, InterviewValidation
from app.api.v1.chat import router as chat_router
from app.api.v1.learning import router as learning_router
from app.api.v1.tasks import router as tasks_router
from app.core.config import get_settings, model_configuration_status
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
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)


@app.get("/api/v1/health", tags=["health"])
async def health():
    return {"status": "ok", "milestone": "M2"}


@app.get('/api/v1/model/configuration', tags=['configuration'])
async def model_configuration():
    settings = get_settings()
    return {
        'chat': model_configuration_status(settings.model_base_url, settings.model_name, settings.model_api_key),
        'embedding': model_configuration_status(settings.embedding_base_url, settings.embedding_model, settings.embedding_api_key),
        'embedding_dimensions': 384,
    }


@app.get("/api/v1/health/ready", tags=["health"])
async def ready():
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="数据库尚未就绪") from exc
    return {"status": "ready"}


@app.exception_handler(InterviewConflict)
async def interview_error(request, exc):
    status = 404 if isinstance(exc, InterviewNotFound) else 422 if isinstance(exc, InterviewValidation) else 409
    return JSONResponse(status_code=status, content={'detail': str(exc)})


app.include_router(interview_router, prefix="/api/v1")
app.include_router(learning_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
