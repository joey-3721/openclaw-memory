import logging
from logging.handlers import TimedRotatingFileHandler
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
    """Ensure application logs are visible in console and written to disk."""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    file_handler = TimedRotatingFileHandler(
        filename=str(settings.logs_dir / "finance-hub.log"),
        when="midnight",
        interval=1,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    app_logger = logging.getLogger("finance_app")
    app_logger.setLevel(logging.INFO)
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_access_logger = logging.getLogger("uvicorn.access")

    console_handlers = list(uvicorn_error_logger.handlers)
    app_logger.handlers = [*console_handlers, file_handler]
    app_logger.propagate = False

    for logger_name in ("uvicorn.error", "uvicorn.access"):
        target_logger = logging.getLogger(logger_name)
        target_logger.setLevel(logging.INFO)
        existing_file_handler = any(
            isinstance(handler, TimedRotatingFileHandler)
            and getattr(handler, "baseFilename", "") == file_handler.baseFilename
            for handler in target_logger.handlers
        )
        if not existing_file_handler:
            target_logger.addHandler(file_handler)

    uvicorn_access_logger.propagate = False


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
