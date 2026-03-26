import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .db import (
    close_pool,
    ensure_schema,
    init_pool,
    seed_asset_types,
    seed_widget_templates,
)
from .routes.api import router as api_router
from .routes.web import router as web_router


def configure_logging() -> None:
    """Ensure application INFO logs are visible under uvicorn."""
    app_logger = logging.getLogger("finance_app")
    app_logger.setLevel(logging.INFO)
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    if uvicorn_error_logger.handlers:
        app_logger.handlers = uvicorn_error_logger.handlers
    app_logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init pool + schema. Shutdown: close pool."""
    init_pool()
    ensure_schema()
    seed_asset_types()
    seed_widget_templates()
    yield
    close_pool()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Finance Hub", lifespan=lifespan)
    app.mount(
        "/static",
        StaticFiles(directory=str(settings.static_dir)),
        name="static",
    )
    app.state.templates = Jinja2Templates(
        directory=str(settings.templates_dir)
    )
    app.include_router(api_router)
    app.include_router(web_router)
    return app
