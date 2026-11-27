import argparse
import logging
import threading

from image_search.adapters.object_storage.local import LocalObjectStorage
from image_search.adapters.postgres.database import create_database_engine
from image_search.adapters.qdrant.client import create_qdrant_client
from image_search.config import configure_logging, get_settings
from image_search.health import Readiness
from image_search.ingestion.worker import ImportWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="CSV import worker: download, embed and publish")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    engine, client = create_database_engine(settings), create_qdrant_client(settings)
    readiness = Readiness(engine, client, LocalObjectStorage(settings.storage_root))
    worker = ImportWorker(engine, client, settings)
    try:
        while True:
            processed = worker.run_once()
            checks = readiness.check()
            logging.getLogger(__name__).info("worker idle; dependencies=%s", checks)
            if args.once:
                raise SystemExit(0 if all(checks.values()) else 1)
            if not processed:
                threading.Event().wait(3)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        engine.dispose()
