from contextlib import asynccontextmanager

from fastapi import FastAPI

from image_search.adapters.object_storage.local import LocalObjectStorage
from image_search.adapters.postgres.database import create_database_engine
from image_search.adapters.qdrant.client import create_qdrant_client
from image_search.api.v1.health import router
from image_search.api.v1.playground import router as playground_router
from image_search.api.v1.search import router as search_router
from image_search.config import Settings, configure_logging, get_settings
from image_search.health import Readiness
from image_search.playground import PlaygroundService
from image_search.search import SearchService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        app.state.search = SearchService(settings.storage_root / "thumbnails")
        app.state.playground = PlaygroundService(app.state.search)
        engine = create_database_engine(settings)
        qdrant = create_qdrant_client(settings)
        app.state.readiness = Readiness(engine, qdrant, LocalObjectStorage(settings.storage_root))
        try:
            yield
        finally:
            app.state.search.close()
            qdrant.close()
            engine.dispose()

    app = FastAPI(title="Images-search", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(search_router)
    app.include_router(playground_router)
    return app


app = create_app()
