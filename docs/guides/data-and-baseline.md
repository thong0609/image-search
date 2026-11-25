# Dữ liệu, index và baseline

Chạy lệnh từ gốc repository. Cần Qdrant; không cần API, frontend hoặc PostgreSQL.
Cấu hình `IMAGE_SEARCH_BASELINE_*`: tham số CLI → biến môi trường → `.env` → mặc định trong code.

```bash
uv sync --frozen --extra baseline --extra planner
docker compose up -d qdrant
```

## 1. Đọc CSV và tải ảnh

```bash
uv run image-search-baseline prepare data/<nguồn>.csv
uv run image-search-baseline download --limit 20   # thử trước
uv run image-search-baseline download --workers 2  # tải toàn bộ, chạy lại để tiếp tục
```

- Chỉ nhận `approve` đúng chuỗi `yes`; giữ metadata nguồn, `record_id` và thứ tự record.
- Ảnh đặt tên bằng SHA-256, kiểm tra giải mã; mặc định tối đa 10 MiB và 40 triệu pixel, timeout
  15 giây, thử lại 2 lần. Chỉ kết nối IP public đã kiểm tra, kể cả khi redirect.
- Kết quả ở `var/`: `records.jsonl`, `images/`, `downloaded-records.jsonl`, `download-errors.jsonl`,
  `download-log.jsonl`. `prepare` ghi đè khi chạy lại. Ảnh tải lỗi không phải ví dụ không có đáp án.

## 2. Gán nhãn và cố định benchmark

```bash
uv run image-search-baseline draft --per-type 3
uv run image-search-baseline freeze --csv data/<nguồn>.csv
```

`draft` tạo nháp `var/queries.jsonl`, `var/answers.jsonl` và `var/catalog.html` để xem ảnh; không ghi
đè nhãn đã có. Một query và một đáp án:

```json
{"query_id":"q001","text":"Tìm ảnh sân vận động Mỹ Đình.","type":"single","split":"dev","answerable":true,"synthetic":false,"reviewed":true}
{"query_id":"q001","targets":[{"image_ids":["<sha256>"],"required":1}],"evidence":[],"verification":""}
```

- Viết câu bằng lời riêng; chỉ đặt `reviewed: true` sau khi kiểm tra.
- Multi-target có từ hai `targets`. Multi-hop cần `evidence` với `record_id`, `role` (bridge/target),
  `description`; bridge và target khác ảnh, cùng entity.
- Câu không có đáp án: `answerable: false`, `targets: []`, ghi cách kiểm tra ở `verification`.
- Giữ nhóm entity và ảnh trùng trong cùng split; ảnh gần trùng dùng chung `split_group`.

`freeze` kiểm tra ID, file ảnh, rò rỉ split và lưu hash vào `var/benchmark.json`. Sau đó không sửa dữ
liệu của phiên bản; muốn đổi thì dùng thư mục và manifest mới.

## 3. Lập index Qdrant

```bash
uv run image-search-qdrant                   # mã hóa ảnh và nạp vào Qdrant
uv run image-search-qdrant --sync-metadata   # chỉ nạp lại metadata, không mã hóa ảnh
HF_HUB_OFFLINE=1 uv run image-search-qdrant --sync-text  # mã hóa tên + mô tả từng record
uv run image-search-embedding check          # mã hóa lại ảnh mẫu, so với Qdrant
```

- Model SigLIP 2 base patch16 224, revision cố định, chạy CPU; tải vào `var/models/` ở lần đầu.
  Đặt `HF_HUB_OFFLINE=1` để chỉ dùng cache local.
- Collection ảnh `image_search_siglip2_v1` (1.886 vector, 768 chiều, cosine) và collection metadata
  cùng tên thêm `_metadata`. Đổi model/revision/corpus phải dùng collection mới.
- Payload giữ record nguồn, tên entity, caption, nhãn và đường dẫn ảnh. Vector chỉ lưu ở Qdrant;
  vector câu hỏi chỉ ở RAM; BM25 dựng trong RAM từ payload.
- Nhánh text thử nghiệm dùng cùng SigLIP2, văn bản `entity_name. mo_ta`, mỗi record một vector;
  không ghép caption của nhiều nơi. Collection `<collection>_text` và `<collection>_text_metadata`
  giữ vector và định danh index. Snapshot hiện tại: 1.997 vector, 11 văn bản bị cắt ở 64 token.
  Sau khi tên/mô tả hoặc model/processor đổi, cần chạy lại `--sync-text` trước khi bật nhánh này;
  metadata không khớp sẽ báo lỗi. Các phiên bản text cũ được giữ và lọc khỏi kết quả bằng hash.
- Dashboard <http://localhost:6333/dashboard>. Dữ liệu ở volume `images-search_qdrant-data`;
  không chạy `docker compose down -v` nếu muốn giữ.

## 4. Baseline tìm cả câu

Baseline tìm nguyên câu, không dùng planner hoặc graph; là mốc so sánh cho pipeline.

```bash
uv run image-search-baseline search "Tìm ảnh sân vận động có mái che"
uv run image-search-baseline run --manifest var/benchmark-v1/benchmark.json --method hybrid --split dev --output-dir var/compare/dev/hybrid
uv run image-search-baseline evaluate var/compare/dev/hybrid/predictions.jsonl --manifest var/benchmark-v1/benchmark.json --split dev
```

- `--method vector|keyword|hybrid`, mặc định vector. Keyword là BM25 (`k1=1.2`, `b=0.75`) trên
  `entity_name`, `leaf_label`, `page_title`, `mo_ta`; tokenizer chữ thường, bỏ dấu.
- Hybrid là RRF chuẩn 1:1, `k=60`, tối đa 100 ứng viên mỗi nhánh. Bằng điểm xếp theo `image_id`.
- Chạy 3 vòng sau warmup, seed 42, không cache. Chấm Known Recall/nDCG tại 1/5/10; nhãn đã biết
  không phải toàn bộ ảnh đúng.
