# Graph quan hệ Neo4j

Graph chỉ chứa entity và quan hệ; metadata tìm kiếm ở Qdrant. Nguồn là toàn bộ metadata
`approve=yes`, được tin cậy và không xác minh thêm.

## Schema

- `Image` (`image_id` dùng chung Qdrant) `-[:DEPICTS]->` `Entity`.
- `Entity`: ID ổn định, tên, alias, `kind` (place, part, brand, area, event, route, other), category,
  danh sách ID nguồn.
- `LOCATED_IN` (vị trí), `PART_OF` (bộ phận/phân khu), `BRANCH_OF` (chi nhánh thương hiệu).

Hiện có 1.886 Image, 319 Entity, 1.932 DEPICTS, 220 LOCATED_IN, 61 BRANCH_OF, 20 PART_OF. Không tự
gộp entity vì tên gần giống hoặc dùng chung ảnh; giữ tên và địa giới theo dataset.

Giới hạn: đã rà tên/nhãn của 185 nhóm và các câu thể hiện quan hệ, chưa gán nhãn đầy đủ mọi caption;
40 ghi chú thiếu/ngoài schema ở `graph.json.unresolved`. Một số nơi chưa có vị trí (ví dụ Mỹ Đình
Pearl) và một địa điểm có thể bị tách thành nhiều entity (ví dụ sân Mỹ Đình).

## Lệnh

Đặt `IMAGE_SEARCH_GRAPH_PASSWORD` riêng trong `.env` trước khi chạy.

```bash
docker compose --profile graph up -d neo4j
uv run image-search-graph prepare --output var/graph-manual-v1/groups-new.jsonl   # xuất metadata để điền
uv run image-search-graph build var/graph-manual-v1/reviewed.jsonl --output var/graph-manual-v1/graph-new.json
uv run image-search-graph import var/graph-manual-v1/graph-new.json
uv run image-search-graph check
uv run image-search-graph entity "Sân vận động Lạch Tray"
```

- `prepare`/`build` không gọi API; `build` kiểm tra schema và hash metadata. Dữ liệu đang dùng ở
  `var/graph-manual-v1/` (`decisions.tsv`, `reviewed.jsonl`, `graph.json`).
- `import` thay graph của dataset trong một transaction; sai ánh xạ Qdrant bị chặn trước khi ghi.
- `extract` gọi API trích xuất, chỉ dùng khi có yêu cầu mới.
- Browser <http://localhost:7474>, Bolt `bolt://localhost:7687`; volume `images-search_neo4j-data`.

```bash
RUN_NEO4J_INTEGRATION=1 uv run pytest -q   # dùng namespace test riêng, không đụng graph thật
```
