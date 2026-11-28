"""Conservative identities, candidate discovery and explicit merge decisions."""

from rapidfuzz import fuzz, process

from image_search.graph.offline.models import Extraction, digest, name_key


def build(responses, decisions=None):
    entities, relations, facts, sources = {}, {}, {}, {}
    for response in responses:
        group = response["input"]
        extracted = Extraction.model_validate(response["output"]).check_input(group)
        records = {r["record_id"]: r for r in group["records"]}
        scope = group["entity_id"]
        for record in extracted.records:
            source = records[record.record_id]
            sources[record.record_id] = {**source, "entity_id": scope}
            for a, predicate, b in record.triples:
                ids = []
                for name in (a, b):
                    # Source identity wins only when the name is explicitly the source name.
                    identity = (
                        ("source", scope)
                        if name_key(name)
                        == name_key(source.get("entity_name", group.get("entity_name", "")))
                        else ("mention", scope, name_key(name))
                    )
                    eid = digest(identity)
                    entity = entities.setdefault(
                        eid,
                        {
                            "id": eid,
                            "name": name,
                            "aliases": [],
                            "scope": scope,
                            "source_entity_id": scope if identity[0] == "source" else None,
                            "kind": "unclassified",
                            "record_ids": [],
                        },
                    )
                    if name != entity["name"] and name not in entity["aliases"]:
                        entity["aliases"].append(name)
                    if record.record_id not in entity["record_ids"]:
                        entity["record_ids"].append(record.record_id)
                    ids.append(eid)
                rid = digest(("relationship", predicate))
                relations.setdefault(
                    rid,
                    {
                        "id": rid,
                        "name": predicate,
                        "aliases": [],
                        "definition": "",
                        "direction": "source_to_target",
                    },
                )
                key = digest((ids[0], rid, ids[1]))
                fact = facts.setdefault(
                    key,
                    {
                        "id": key,
                        "source": ids[0],
                        "relation": rid,
                        "target": ids[1],
                        "record_ids": [],
                    },
                )
                if record.record_id not in fact["record_ids"]:
                    fact["record_ids"].append(record.record_id)
    decisions = decisions or {}
    for rid, definition in decisions.get("definitions", {}).items():
        if rid not in relations or not isinstance(definition, str) or not definition.strip():
            raise ValueError("Định nghĩa relationship không hợp lệ")
        relations[rid]["definition"] = definition.strip()
    for kind, registry in (("entities", entities), ("relations", relations)):
        mapping = {}
        for old, target in decisions.get(kind, {}).items():
            if old not in registry or target not in registry or old == target:
                raise ValueError("Merge phải tham chiếu hai ID có thật")
            mapping[old] = target

        def canonical(key, mapping=mapping):
            seen = set()
            while key in mapping:
                if key in seen:
                    raise ValueError("Merge cycle")
                seen.add(key)
                key = mapping[key]
            return key

        for old in mapping:
            target = canonical(old)
            registry[target]["aliases"] = sorted(
                set(
                    registry[target]["aliases"] + registry[old]["aliases"] + [registry[old]["name"]]
                )
            )
            if kind == "entities":
                registry[target]["record_ids"] = sorted(
                    set(registry[target]["record_ids"] + registry[old]["record_ids"])
                )
        for fact in facts.values():
            for field in ("source", "target") if kind == "entities" else ("relation",):
                fact[field] = canonical(fact[field])
        for old in mapping:
            del registry[old]
    merged = {}
    for fact in facts.values():
        if fact["source"] == fact["target"]:
            raise ValueError("Merge tạo self-loop; cần xem lại quyết định")
        key = digest((fact["source"], fact["relation"], fact["target"]))
        row = merged.setdefault(key, {**fact, "id": key, "record_ids": []})
        row["record_ids"] = sorted(set(row["record_ids"] + fact["record_ids"]))
    artifact = {
        "entities": sorted(entities.values(), key=lambda r: r["id"]),
        "relations": sorted(relations.values(), key=lambda r: r["id"]),
        "facts": sorted(merged.values(), key=lambda r: r["id"]),
        "sources": sorted(sources.values(), key=lambda r: r["record_id"]),
        "extraction_sha256": digest(responses),
        "decisions": decisions,
    }
    return {**artifact, "generation": digest(artifact)}


def candidates(artifact):
    result = []
    for kind in ("entities", "relations"):
        rows = artifact[kind]
        names = {r["id"]: name_key(r["name"]) for r in rows}
        for row in rows:
            matches = process.extract(names[row["id"]], names, scorer=fuzz.WRatio, limit=6)
            for _, score, key in matches:
                if key != row["id"] and score >= 75:
                    result.append(
                        {
                            "kind": kind,
                            "source": row["id"],
                            "candidate": key,
                            "score": score,
                            "method": "rapidfuzz",
                            "auto_merge": False,
                        }
                    )
    return result
