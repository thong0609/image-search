"""Record theo ảnh/entity từ metadata nguồn; không đọc câu hỏi/đáp án benchmark."""

from collections import defaultdict

from image_search.adapters.qdrant.metadata import name_key


class Catalog:
    def __init__(self, records, image_ids, aliases=None):
        self.aliases = aliases or {}
        self.image_entities = defaultdict(set)
        self.records = defaultdict(list)
        valid, known = set(image_ids), set()
        for row in records:
            iid = row.get("image_id")
            if row.get("download_status") != "success" or iid not in valid:
                continue
            known.add(row["entity_id"])
            self.image_entities[iid].add(row["entity_id"])
            self.records[iid].append(row)
        for alias, entity_ids in self.aliases.items():
            if (
                not name_key(alias)
                or not isinstance(entity_ids, list)
                or not entity_ids
                or not set(entity_ids) <= known
            ):
                raise ValueError("Alias cần tên và danh sách entity ID có trong catalog")
