# Chạy baseline

Code dùng các hàm thông thường, chia file theo từng công việc. Chạy lệnh từ thư mục repo.
Baseline CLI không cần API, frontend, PostgreSQL hay Qdrant.

Cấu hình nằm trong class `BaselineSettings` ở `src/image_search/baseline/settings.py`.
Thứ tự ưu tiên: tham số CLI → biến môi trường → `.env` → mặc định trong class.
Các biến dùng tiền tố `IMAGE_SEARCH_BASELINE_`; xem `.env.example`.
Ví dụ đặt `IMAGE_SEARCH_BASELINE_TIMEOUT=30` trong `.env` để đổi timeout mặc định.

Code nằm trong package `src/image_search/baseline/`: `cli.py` điều phối lệnh,
`records.py` đọc CSV, `download.py` tải ảnh, `benchmark.py` quản lý nhãn/manifest,
`vectors.py` tạo vector và tìm kiếm, `evaluate.py` chấm điểm, `settings.py` cấu hình,
`keyword.py` tìm keyword/gộp hybrid, `utils.py` chứa các hàm dùng chung.
Có thể chạy bằng `python -m image_search.baseline`
hoặc lệnh `image-search-baseline` sau khi đồng bộ môi trường bằng uv.

## 1. Cài đặt và đọc CSV

```bash
uv sync --frozen --extra baseline
uv run --extra baseline image-search-baseline prepare data/general_10m_part_02_18-11-2026_CHIEU_To_Huy_Thong.csv
```

Chỉ lấy `approve == "yes"`. Kết quả: `var/records.jsonl` và `var/prepare.json`.
Giữ metadata nguồn, `record_id` và thứ tự record dữ liệu từ 1 (không phải dòng vật lý).
Chạy lại `prepare` sẽ ghi đè hai file này.

## 2. Tải ảnh

```bash
uv run --extra baseline image-search-baseline download --limit 20
# Sau khi kiểm tra nhóm nhỏ, tải toàn bộ:
uv run --extra baseline image-search-baseline download --workers 2
```

Mặc định: 1 worker, timeout mạng 15 giây, tối đa 10 MiB/file, thử lại 2 lần với lỗi
tạm thời, tối đa 40 triệu pixel. Có thể đổi `--timeout`, `--max-bytes`, `--retries`.
`--limit` tính theo URL duy nhất theo thứ tự CSV, gồm URL đã tải thành công.

Ảnh được đặt tên bằng SHA-256 bytes gốc, lưu một bản cho ảnh trùng chính xác.
Chạy lại sẽ kiểm tra hash/khả năng giải mã trước khi dùng lại ảnh. Không dùng proxy từ
biến môi trường; mỗi request kết nối trực tiếp IP public đã kiểm tra, kể cả redirect.

Kết quả trong `var/`:

- `images/`: ảnh hợp lệ.
- `downloaded-records.jsonl`: đủ record nguồn, kèm trạng thái success/failed/pending.
- `download-errors.jsonl`: URL lỗi; lỗi tải không được coi là câu không có đáp án.
- `download-log.jsonl`: checkpoint từng URL để chạy tiếp.
- `download-settings.json`: tham số tải thực tế.

## 3. Tạo và sửa bộ nhãn

```bash
uv run --extra baseline image-search-baseline draft --per-type 3
```

Mở `var/catalog.html` bằng trình duyệt để xem ảnh, record ID và mô tả nguồn.
Sửa `var/queries.jsonl` và `var/answers.jsonl` bằng editor. Lệnh `draft` không ghi đè
file nhãn đã có. Nếu dữ liệu chưa đủ entity/ảnh cho ba dạng ở cả hai split, tải thêm ảnh.

Một query:

```json
{"query_id":"q001","text":"Tìm ảnh sân vận động Mỹ Đình.","type":"single","split":"dev","answerable":true,"synthetic":false,"reviewed":true}
```

Một đáp án (thay ID mẫu bằng hash ảnh thực tế):

```json
{"query_id":"q001","targets":[{"image_ids":["<sha256>"],"required":1}],"evidence":[],"verification":""}
```

- Viết câu bằng lời riêng, sửa tập ảnh đúng và số lượng `required`; sau khi kiểm tra
  mới đặt `reviewed: true`. Câu mẫu tạo sẵn có `synthetic: true`; câu tự viết đặt false.
- Multi-target có ít nhất hai phần tử trong `targets`. Mỗi mục tiêu có tập ảnh và số
  ảnh yêu cầu riêng. Cả câu dùng chung danh sách kết quả tìm kiếm.
- Multi-hop cần sửa câu mẫu thành câu dùng đặc điểm của ảnh gợi ý để xác định entity,
  rồi tìm ảnh đích. `evidence` chứa `record_id`, `role` (bridge/target), `description`.
  Bridge và target phải khác ảnh, cùng entity; mọi ảnh đích phải có record bằng chứng.
  Mô tả có sẵn chỉ giúp gán nhãn, không tự chứng minh câu hỏi đã đúng.
- Câu không có đáp án: `answerable: false`, `targets: []`; ghi cách đã kiểm tra toàn kho
  trong `verification`. Không lấy lỗi tải làm bằng chứng.
- Nháp chia dev/test theo nhóm entity và ảnh trùng. Giữ các nhóm này khi thêm câu.
  Nếu phát hiện ảnh gần trùng giữa các entity, thêm cùng giá trị `split_group` vào các
  record liên quan trong `downloaded-records.jsonl`, rồi chỉnh split cho thống nhất.
  Code không tự nhận diện ảnh gần trùng hoặc tự xác minh nội dung thị giác.

Ban đầu thử vài câu mỗi loại; mở rộng khoảng 50–100 câu khi luồng đã ổn.
Baseline v2 đã chốt và chạy đủ 400 câu trong `var/benchmark-v2/` cho ba phương pháp.
Xem [kết quả v2](baseline-v2-results.md) và [thiết kế bộ câu hỏi](benchmark-design.md).
Nhãn benchmark còn ở mức ứng viên; 356 câu dương được chấm, 42 unknown không chấm.
Phải đủ single, multi-target, multi-hop có đáp án trong cả dev và test, cùng ít nhất
một câu không có đáp án đã xác minh.

## 4. Cố định benchmark

```bash
uv run --extra baseline image-search-baseline freeze --csv data/general_10m_part_02_18-11-2026_CHIEU_To_Huy_Thong.csv
```

Tạo `var/benchmark.json`: hash CSV, record, query, đáp án, danh sách ảnh và quy tắc chấm.
Lệnh kiểm tra ID, liên kết, file ảnh, trạng thái xác nhận và rò rỉ split trước khi lưu.
Những kiểm tra này không thay cho việc tự kiểm tra nội dung câu hỏi/đáp án.
Sau khi freeze, không sửa dữ liệu của phiên bản đó. Khi cần đổi dữ liệu, lưu bộ file
mới vào thư mục khác và dùng `--manifest` mới; manifest cũ sẽ báo lỗi nếu file nguồn đổi.

## 5. Tạo vector và tìm kiếm

```bash
uv run --extra baseline image-search-baseline index --batch-size 4
uv run --extra baseline image-search-baseline search "Tìm ảnh sân vận động có mái che"
```

Mặc định dùng [SigLIP 2 base patch16 224](https://huggingface.co/google/siglip2-base-patch16-224)
với revision cố định `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`, chạy CPU.
Lần đầu cần mạng để tải model vào `var/models/`. Thử kho nhỏ trước để đo RAM/thời gian.
Đây là ứng viên khởi đầu; chất lượng tiếng Việt phải được đo trên dữ liệu dự án.
Phương pháp mặc định `--method vector` không dịch câu, tách mục tiêu, dùng keyword,
graph hoặc reranker. Có thể chọn keyword/hybrid để so sánh riêng như hướng dẫn dưới.

Vector ảnh/văn bản được chuẩn hóa L2, xếp hạng cosine; bằng điểm thì theo image_id tăng dần.
`var/index/` chứa `images.npy`, danh sách ID, phiên bản thư viện và cấu hình tiền xử lý.
Chạy lại dùng index cũ nếu tương thích; đổi model/revision/benchmark cần `--index-dir` mới.
Nếu đổi model, truyền cả `--model` và `--revision` (commit SHA 40 ký tự), chọn trên dev.
`--threads` mặc định 4; giảm batch size nếu thiếu RAM.

Mở `var/search/results.html` để xem ảnh. Kết quả máy đọc được ở `predictions.jsonl`.

## 6. Chạy đánh giá

```bash
uv run --extra baseline image-search-baseline run --split dev
# Chỉ chạy test tại mốc đã chọn sau khi chốt cấu hình trên dev:
uv run --extra baseline image-search-baseline run --split test
```

Kết quả trong `var/dev/` hoặc `var/test/`: `report.md`, `report.json`, `query-scores.jsonl`,
`predictions.jsonl`, `timings.jsonl`, `run.json` và `results.html`.

Chấm Known-Recall, Known-nDCG, Hit và mức đủ mục tiêu tại K=1/5/10; bỏ ID trùng trước
khi cắt K. Lấy trung bình mục tiêu rồi query, tách split/loại câu/câu tổng hợp và không
có đáp án. Nhãn đã biết không phải toàn bộ ảnh đúng về thị giác. Baseline không có
ngưỡng từ chối nên có thể luôn trả ảnh cho câu không có đáp án.

Độ trễ gồm mã hóa câu và tìm kiếm, sau một lần warmup; chạy tuần tự ba vòng, seed 42,
không cache query/kết quả. `run.json` ghi p50/p95, RAM đỉnh toàn process, thông tin máy,
hash code, thời gian nạp model, mã hóa ảnh và dung lượng vector. RAM dùng số liệu Linux.
Kết quả HTML/ghi file không tính vào độ trễ truy vấn.

Chấm lại dự đoán đã có:

```bash
uv run --extra baseline image-search-baseline evaluate var/dev/predictions.jsonl --split dev
```

Lệnh `run` ghi đè output cùng thư mục; dùng `--output-dir` khác để giữ nhiều lần đo.
Đổi phiên bản benchmark nên dùng thư mục riêng cho toàn bộ dữ liệu sinh ra và truyền
các đường dẫn tương ứng; xem `image-search-baseline <lệnh> --help`.

## Kiểm tra code

```bash
uv run --extra baseline ruff check .
uv run --extra baseline ruff format --check .
uv run --extra baseline pytest
```

Test dùng request giả lập, ảnh tự tạo và model SigLIP rất nhỏ tạo local để kiểm tra
pipeline; không tải ảnh/model ngoài mạng và không tạo điểm chất lượng cho dữ liệu thật.
Test vector/model được skip khi không cài extra `baseline`.

## So sánh vector, keyword và hybrid

Giữ nguyên manifest/query/đáp án và vector index khi so sánh. Ví dụ với benchmark v1:

```bash
uv run --extra baseline image-search-baseline run --manifest var/benchmark-v1/benchmark.json --index-dir var/index-v1 --method vector --split dev --output-dir var/compare/dev/vector
uv run --extra baseline image-search-baseline run --manifest var/benchmark-v1/benchmark.json --index-dir var/index-v1 --method keyword --split dev --output-dir var/compare/dev/keyword
uv run --extra baseline image-search-baseline run --manifest var/benchmark-v1/benchmark.json --index-dir var/index-v1 --method hybrid --split dev --output-dir var/compare/dev/hybrid
```

Keyword dùng BM25 với `k1=1.2`, `b=0.75`, trên bốn trường nguồn: `entity_name`,
`leaf_label`, `page_title`, `mo_ta`. Một document cho mỗi image_id, gom metadata của
các record liên quan và bỏ đoạn trùng chính xác. Tokenizer chuyển chữ thường, bỏ dấu
tiếng Việt, tách chữ/số; không tách từ tiếng Việt chuyên biệt và không dùng stopword.
Document không có term trùng nhận điểm 0 và không được thêm vào kết quả keyword.
Không đưa query, đáp án, evidence hoặc tên file ảnh vào document.

Hybrid lấy tối đa `--candidates 100` từ mỗi nhánh, gộp bằng RRF chuẩn, hệ số 1:1:

```text
score = 1 / (rrf_k + vector_rank)
      + 1 / (rrf_k + keyword_rank)
```

Rank bắt đầu từ 1; ảnh vắng ở nhánh nào không nhận điểm từ nhánh đó. `rrf_k` mặc định
60, không phải số kết quả top-K. Bằng điểm thì xếp theo image_id. Câu hỏi vẫn đi nguyên
câu vào cả hai nhánh; chưa có tách mục tiêu, graph hoặc reranker.

Keyword index mặc định ở `<index-dir>/keyword/` (đổi bằng `--keyword-dir`), gồm document,
hash dữ liệu và cấu hình. Nó được tạo ở lần chạy đầu; đổi tokenizer/field/k1/b/corpus
cần thư mục keyword mới. Nhánh keyword không nạp encoder; hiện dùng cùng lệnh và vector
index đã có để kiểm tra corpus/thứ tự ID cho phép so sánh nhất quán.

Không chọn trọng số riêng cho nhánh nào; `--keyword-weight` và cấu hình môi trường
`HYBRID_KEYWORD_WEIGHT` đã được bỏ. Kết quả weighted RRF cũ trong `var/hybrid-v1/`
là lịch sử của phương pháp trước, không phải RRF chuẩn. RRF chuẩn có thứ hạng tương
đương weighted RRF 0.5:0.5, nhưng điểm số gấp đôi.
Chốt k/candidate trên dev trước khi chạy test nếu muốn thay mặc định. Lưu mỗi lần chạy
vào output riêng. Không thay nhãn hoặc corpus để nâng điểm.
`run.json` ghi fusion=rrf, hệ số cố định vector=1/keyword=1, số candidate, BM25,
tokenizer và trường metadata. Kết quả RRF chuẩn chạy trên v1 nằm ở `var/rrf-v1/`.
Vẫn đo ba vòng sau warmup, không cache query/result; index và model load tính riêng.

Keyword được thêm metadata mà vector ảnh không có. Đặc biệt, nhãn v1 cũng dựa trên
metadata này, nên mức tăng trên v1 có thể thuận lợi cho keyword. Cần bộ nhãn độc lập
trước khi khẳng định chất lượng ngoài dữ liệu hiện tại; keyword không tự giải được
quan hệ multi-hop hay bảo đảm đủ mọi mục tiêu.

Tham khảo thuật toán: [BM25 trong Elasticsearch](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity),
[RRF trong Azure AI Search](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking).


## Quy tắc dữ liệu

CSV phải có metadata bắt buộc; chỉ nhận `approve` đúng chuỗi `yes`.
Giữ nguyên nguồn và record ID để truy vết. Tải ảnh public HTTP(S) có giới hạn,
kiểm tra giải mã, dùng SHA-256 bytes làm image ID và hỗ trợ chạy tiếp.
Ảnh tải lỗi không trở thành ví dụ không có đáp án. Giữ nhãn đánh giá riêng khỏi
đầu vào retrieval; chia nhóm entity/alias/ảnh trùng trước khi chốt dev/test.
Mỗi lần thay corpus hoặc nhãn cần phiên bản benchmark mới.


## Embedding cho retrieval

Bước 3 hiện có `src/image_search/embedding/`: settings, encoder và CLI đơn giản.
Tái sử dụng `var/index-v1/images.npy`, checkpoint SigLIP2/revision và processor hash
của baseline; không tự đổi model/tiền xử lý hoặc mã hóa lại toàn kho.

- Ảnh: 1.886 vector float32, 768 chiều, chuẩn hóa L2; giữ thứ tự image ID theo index.
- Text: mã hóa `search_text` riêng cho từng bước `resolve_entity`/`retrieve_images`.
  Giữ query ID, step ID, target ID và dependency trong `steps.jsonl` để executor dùng sau.
- Câu cần làm rõ/planner lỗi được bỏ qua với lý do, không tạo vector giả.
- Batch text dùng padding/truncation giống baseline; ghi token_count/truncated cho từng bước.
  Text vượt 64 token bị cắt theo cấu hình model, cần rà trước khi đánh giá retrieval.
- Embedding chưa thực thi entity lookup, bridge, lọc ảnh, retrieval hoặc reranking.

Từ repository root sau khi cài `--extra baseline` (kèm `--extra planner` để giữ SDK):

```bash
HF_HUB_OFFLINE=1 image-search-embedding check --output-dir var/embeddings/siglip2/check-new
HF_HUB_OFFLINE=1 image-search-embedding text "ảnh mặt tiền cửa hàng" --output-dir var/embeddings/siglip2/text-new
HF_HUB_OFFLINE=1 image-search-embedding benchmark var/planner-v2/dev/predictions.jsonl --rounds 3 --output-dir var/embeddings/siglip2/benchmark-new
```

Output mới không được tồn tại. Tham số `--threads`, `--batch-size`, `--manifest`,
`--index-dir` đặt TRƯỚC subcommand; class `EmbeddingSettings` đọc namespace
`IMAGE_SEARCH_EMBEDDING_` trong `.env`. Chạy `python -m image_search.embedding` tương đương CLI.

Đã kiểm tra hash/norm/order toàn index và mã hóa lại 3 ảnh mẫu: sai số tối đa 3,28e-7.
Đã mã hóa plan v2 dev/test: 46/47 text vector, mỗi split bỏ 3 câu cần làm rõ,
không text nào bị cắt. So 3 text mỗi split với `encode_text` baseline đều khớp.

| Embedding toàn bộ bước của một plan | p50 ms | p90 ms | p95 ms |
|---|---:|---:|---:|
| Dev (27 plan) | 86,88 | 95,82 | 106,26 |
| Test (27 plan) | 91,98 | 132,78 | 135,07 |

Ba vòng sau warmup, CPU 4 threads, batch tối đa 8, OPENBLAS_NUM_THREADS=1,
không cache vector. Không gồm planner, retrieval, rerank, nạp model hoặc kiểm tra index.
Không kết luận SLO toàn pipeline từ số đo riêng này. Bộ plan tổng hợp có entity giả,
chỉ dùng kiểm tra mapping/vector và thời gian, chưa đo chất lượng tìm ảnh thật.

Artifact local: `var/embeddings/siglip2/report.md`, `verification.json`,
`check-v1/`, `planner-v2-dev/`, `planner-v2-test/`. Source CLI lúc đo giữ trong
`executed-cli.py`; source sau đó chỉ sửa xuống dòng để đạt lint.

Kiểm tra code: `pytest -q tests/unit/test_embedding.py` (test giả, không tải model).
Tài liệu model: [SigLIP2 Transformers](https://huggingface.co/docs/transformers/model_doc/siglip2).
