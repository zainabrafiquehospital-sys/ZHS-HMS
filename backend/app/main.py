from fastapi import FastAPI

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import register_middleware


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
    )

    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
