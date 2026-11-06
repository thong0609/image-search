"""Run only against an empty, disposable local database after migration."""

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from image_search.adapters.object_storage.local import LocalObjectStorage
from image_search.adapters.postgres.database import create_database_engine
from image_search.adapters.postgres.schema import (
    collections,
    images,
    jobs,
    metadata,
    search_configs,
)
from image_search.adapters.qdrant.client import create_qdrant_client
from image_search.config import get_settings
from image_search.health import Readiness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="Set RUN_INTEGRATION=1 with migrated local services",
    ),
]


def test_migrated_stack_is_ready_and_has_all_nine_tables(tmp_path):
    settings = get_settings()
    engine, client = create_database_engine(settings), create_qdrant_client(settings)
    try:
        assert all(Readiness(engine, client, LocalObjectStorage(tmp_path)).check().values())
        assert set(metadata.tables) <= set(sa.inspect(engine).get_table_names())
    finally:
        client.close()
        engine.dispose()


def test_database_prevents_two_active_search_configs():
    engine = create_database_engine(get_settings())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(search_configs.insert().values(id=uuid4(), status="active"))
                with pytest.raises(sa.exc.IntegrityError):
                    with connection.begin_nested():
                        connection.execute(
                            search_configs.insert().values(id=uuid4(), status="active")
                        )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def db_connection():
    engine = create_database_engine(get_settings())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_job_rejects_missing_image_without_content_version(db_connection):
    with pytest.raises(sa.exc.IntegrityError) as error:
        with db_connection.begin_nested():
            db_connection.execute(
                jobs.insert().values(
                    id=uuid4(),
                    type="purge",
                    image_id=uuid4(),
                    content_version=None,
                    dedupe_key=str(uuid4()),
                )
            )
    assert error.value.orig.sqlstate == "23503"
    assert error.value.orig.diag.constraint_name == "fk_jobs_image_id"


def test_job_accepts_existing_image_without_content_version(db_connection):
    collection_id, image_id, job_id = uuid4(), uuid4(), uuid4()
    db_connection.execute(collections.insert().values(id=collection_id, name="Fixture"))
    db_connection.execute(
        images.insert().values(
            id=image_id,
            collection_id=collection_id,
            source_id="fixture",
            source_item_key=str(image_id),
        )
    )
    db_connection.execute(
        jobs.insert().values(
            id=job_id,
            type="purge",
            image_id=image_id,
            content_version=None,
            dedupe_key=str(job_id),
        )
    )
    assert db_connection.scalar(sa.select(jobs.c.image_id).where(jobs.c.id == job_id)) == image_id


def test_job_accepts_no_image_for_import_root(db_connection):
    job_id = uuid4()
    db_connection.execute(
        jobs.insert().values(
            id=job_id,
            type="import",
            image_id=None,
            content_version=None,
            dedupe_key=str(job_id),
        )
    )
    assert db_connection.scalar(sa.select(jobs.c.id).where(jobs.c.id == job_id)) == job_id
