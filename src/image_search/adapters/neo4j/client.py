from neo4j import GraphDatabase


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
