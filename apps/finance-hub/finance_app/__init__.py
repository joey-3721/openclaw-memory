from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .routes.web import router as web_router


def create_app():
    app = FastAPI(title="Finance Hub")
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    app.state.templates = Jinja2Templates(directory=str(settings.templates_dir))
    app.include_router(web_router)
    return app
