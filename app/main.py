from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.automation.scheduler import start_scheduler, stop_scheduler
from app.api.error_handlers import register_exception_handlers
from app.api.router import api_router
from app.core.config import settings
from app.db import create_db_and_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
app.include_router(api_router)
register_exception_handlers(app)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
