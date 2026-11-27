from neo4j import GraphDatabase

from image_search.adapters.neo4j.store import GraphStore
from image_search.graph.settings import GraphSettings


def create_graph_driver(settings):
    driver = GraphDatabase.driver(
        settings.uri,
        auth=(settings.username, settings.password.get_secret_value()),
        connection_timeout=settings.timeout,
        max_transaction_retry_time=settings.timeout,
    )
    try:
        driver.verify_connectivity()
        return driver
    except Exception:
        driver.close()
        raise


def load_graph(index, payloads, settings=None):
    settings = settings or GraphSettings()
    driver = create_graph_driver(settings)
    graph = GraphStore(driver, settings, index["search_metadata_sha256"])
    try:
        graph.validate(index, payloads)
        return graph
    except Exception:
        driver.close()
        raise
