from image_search.adapters.neo4j.client import create_graph_driver
from image_search.adapters.neo4j.store import GraphStore
from image_search.modules.graph.settings import GraphSettings


def load_graph(index, payloads):
    settings = GraphSettings()
    driver = create_graph_driver(settings)
    graph = GraphStore(driver, settings, index["search_metadata_sha256"])
    try:
        graph.validate(index, payloads)
        return graph
    except Exception:
        driver.close()
        raise
