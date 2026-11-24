"""Tra entity từ metadata nguồn, không đọc câu hỏi/đáp án benchmark."""

from collections import defaultdict

from image_search.baseline.keyword import tokenize


def name_key(text):
    return " ".join(tokenize(text))


class Catalog:
    def __init__(self, records, image_ids, aliases=None):
        self.image_entities = defaultdict(set)
        self.entity_images = defaultdict(set)
        self.names = defaultdict(set)
        self.records = defaultdict(list)
        self.uncertain = set()
        valid = set(image_ids)
        for row in records:
            iid = row.get("image_id")
            if row.get("download_status") != "success" or iid not in valid:
                continue
            eid = row["entity_id"]
            self.image_entities[iid].add(eid)
            self.entity_images[eid].add(iid)
            self.names[name_key(row["entity_name"])].add(eid)
            self.records[iid].append(row)
            if any(
                term in row.get("mo_ta", "").casefold()
                for term in ("có thể là", "có lẽ", "chưa xác định", "không rõ")
            ):
                self.uncertain.add(iid)
        for alias, eids in (aliases or {}).items():
            if (
                not name_key(alias)
                or not isinstance(eids, list)
                or not eids
                or not all(eid in self.entity_images for eid in eids)
            ):
                raise ValueError("Alias cần tên và danh sách entity ID có trong catalog")
            self.names[name_key(alias)].update(eids)

    def resolve(self, mention):
        return set(self.names.get(name_key(mention), set()))

    def images_for(self, entity_ids):
        return (
            set().union(*(self.entity_images[eid] for eid in entity_ids)) if entity_ids else set()
        )

    def bridge_entity(self, iid):
        eids = self.image_entities[iid]
        # Không tự chọn địa điểm cho ảnh được gán nhiều entity hoặc nguồn chưa chắc chắn.
        return next(iter(eids)) if len(eids) == 1 and iid not in self.uncertain else None
