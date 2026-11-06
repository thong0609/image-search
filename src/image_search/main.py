from contextlib import asynccontextmanager

from fastapi import FastAPI

from image_search.adapters.object_storage.local import LocalObjectStorage
from image_search.adapters.postgres.database import create_database_engine
from image_search.adapters.qdrant.client import create_qdrant_client
from image_search.api.v1.health import router
from image_search.config import Settings, get_settings
from image_search.health import Readiness
from image_search.shared.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        engine = create_database_engine(settings)
        qdrant = create_qdrant_client(settings)
        app.state.readiness = Readiness(engine, qdrant, LocalObjectStorage(settings.storage_root))
        try:
            yield
        finally:
            qdrant.close()
            engine.dispose()

    app = FastAPI(title="Images-search", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
