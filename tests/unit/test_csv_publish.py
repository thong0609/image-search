from image_search.ingestion.publish import Publisher


def row(**values):
    return {
        "entity_id": "A",
        "entity_name": "Chợ A",
        "image_url": "https://example.com/a.jpg",
        "approve": "yes",
        **values,
    }


def test_graph_extension_preserves_relations_and_only_adds_image_links():
    graph = {
        "entities": [],
        "relations": [],
        "image_links": [],
        "image_ids": [],
        "metadata_sha256": "old",
    }
    record = {**row(), "image_id": "image"}
    updated = Publisher.extend_graph(
        graph, {"image_ids": ["image"], "search_metadata_sha256": "new"}, [record]
    )
    assert updated["entities"][0]["source_ids"] == ["A"]
    assert updated["relations"] == []
    assert len(updated["image_links"]) == 1
    assert graph["entities"] == []
