# Chạy baseline

Code dùng các hàm thông thường, chia file theo từng công việc. Chạy lệnh từ thư mục repo.
Baseline CLI cần Qdrant cho vector; không cần API, frontend hoặc PostgreSQL.

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
Qdrant chứa vector, danh sách ID, phiên bản thư viện và cấu hình tiền xử lý.
Chạy lại dùng collection cũ nếu tương thích; đổi model/revision/benchmark cần `--collection` mới.
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
uv run --extra baseline image-search-baseline run --manifest var/benchmark-v1/benchmark.json --collection image_search_siglip2_v1 --method vector --split dev --output-dir var/compare/dev/vector
uv run --extra baseline image-search-baseline run --manifest var/benchmark-v1/benchmark.json --collection image_search_siglip2_v1 --method keyword --split dev --output-dir var/compare/dev/keyword
uv run --extra baseline image-search-baseline run --manifest var/benchmark-v1/benchmark.json --collection image_search_siglip2_v1 --method hybrid --split dev --output-dir var/compare/dev/hybrid
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

Keyword index mặc định ở `var/hybrid-v1/keyword-index/` (đổi bằng `--keyword-dir`), gồm document,
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

SigLIP2 dùng model/revision và processor hash từ metadata trong Qdrant.
Mỗi bước planner được mã hóa riêng; vector query chỉ ở RAM, không tạo cache trên đĩa.
CLI ghi `steps.jsonl` giữ query/step/target/dependency và báo cáo `embedding.json`.
Các bước bị cắt token hoặc có vector sai shape/norm bị từ chối trước retrieval.

```bash
HF_HUB_OFFLINE=1 image-search-embedding check --output-dir var/embedding-check
HF_HUB_OFFLINE=1 image-search-embedding text "ảnh mặt tiền cửa hàng" --output-dir var/embedding-text
```

`check` mã hóa lại ảnh mẫu và so với vector lấy từ Qdrant.
Các tham số `--threads`, `--batch-size`, `--manifest` đặt trước subcommand.


## Retrieval theo kế hoạch

`src/image_search/retrieval/` có catalog, settings, engine, runtime loader và CLI.
Không có framework agent, không gọi OpenAI khi chạy retrieval.
Dùng dependencies baseline; giữ thêm extra planner nếu còn chạy planner riêng.

```bash
uv sync --frozen --extra baseline --extra planner
HF_HUB_OFFLINE=1 image-search-retrieval var/retrieval-v1/planner/predictions.jsonl --method all --output-dir var/retrieval-v1/new-live
```

Input là JSONL kết quả planner (`query_id`, `status`, `plan`, `text` tùy chọn).
`--method` chọn vector/keyword/hybrid/all; `--rounds` mặc định 3, seed 42.
Không ghi đè output đã có. Dùng settings `IMAGE_SEARCH_EMBEDDING_` để chọn index và
`IMAGE_SEARCH_RETRIEVAL_` cho shortlist/bridge. Model và processor phải khớp image index.

- Vector cosine, BM25 và RRF chuẩn 1:1 dùng lại thuật toán baseline.
- Named entity tra tên chuẩn hóa không dấu/hoa thường/dấu câu, không substring/fuzzy.
  Có thể cấp `--aliases file.json` theo dạng alias -> list entity ID thật trong catalog.
  Không đọc đáp án benchmark để tạo alias. Tên không khớp trả entity_not_found,
  không bỏ điều kiện entity rồi tìm toàn kho.
- Lọc phạm vi entity TRƯỚC top-K. BM25 giữ IDF toàn corpus rồi lọc/cắt K.
- Mỗi mục tiêu có candidates (mặc định top-100) và results (count yêu cầu hoặc giới hạn
  hiển thị 10 nếu count=null). Thiếu ảnh chỉ báo insufficient_candidates nếu có count
  tường minh; không bù bằng ảnh của target khác. Chưa kiểm chứng điều kiện thị giác.
- Bridge tìm top-20 ảnh, giữ tối đa 3 entity giả thuyết, tối đa hai đường bằng chứng mỗi
  entity theo cấu hình executor. Không coi top-1 là đúng. Ảnh nhiều entity hoặc nguồn ghi chưa chắc chắn bị
  bỏ khỏi bước nhận diện. Đây là chính sách bảo thủ, có thể bỏ cả alias đúng cùng nơi.
- Bước phụ thuộc tìm trong các entity giả thuyết của bước trước, loại ảnh bridge đã
  dùng. Nhiều dependency lấy giao entity. Kết quả giữ bridge image ID/record ID và trace.
  Đây là traversal ứng viên qua metadata image–entity, chưa là graph facts/VLM xác nhận.
- Planner lỗi/cần làm rõ, entity mâu thuẫn hoặc không có bridge đều có trạng thái riêng.
  Không tạo vector, entity hay ảnh giả để lấp kết quả.
- Query được mã hóa khi chạy; không lưu hoặc đọc cache vector trên đĩa.
  Query bị cắt token hoặc vector sai shape/norm bị từ chối.

Output mỗi phương pháp có predictions.jsonl, timings.jsonl, report.json và results.html.
index.html ở output root dẫn tới ba trang ảnh. run.json ghi hash code/input/index/config.
Độ trễ gồm query embedding + retrieval, loại trừ
OpenAI planner, rerank và startup. Không dùng số này để kết luận SLO toàn pipeline.

Đã chạy thử 6 câu dev thật, chọn trước 2 câu canonical có nhãn dương mỗi loại từ v2.
Chỉ text được gửi planner; retrieval không đọc labels/answers. Đây là kiểm tra chức năng,
không phải benchmark chất lượng: chưa báo Recall/nDCG hoặc tuyên bố tốt hơn baseline.
Một câu dừng ở dependency_unresolved do tên entity planner không khớp catalog.

Artifact lịch sử: `var/retrieval-v1/selection.json`, `planner/`,
`results/` (cached), `results-live/` (embedding trực tiếp), `report.md`.
Bộ 60 câu planner entity giả không được dùng làm nhãn đánh giá retrieval ảnh thật.

Test: `pytest -q tests/unit/test_retrieval.py` (fixture nhỏ, không mạng/model thật).


## Executor — bước 5

`retrieval/executor.py` thực thi dependency; `retrieval/evidence.py` kiểm tra bằng chứng
metadata. Giữ API/CLI retrieval hiện tại, không gọi thêm OpenAI, VLM hay sửa planner.
Quan hệ đang hỗ trợ là ảnh thuộc entity trong catalog, chưa là graph facts tổng quát.

- Mỗi entity giữ đường bằng chứng riêng: step ID, bridge image ID, target image ID,
  record ID và URL nguồn nếu có. Chỉ ghép dependency có chung entity và không mâu thuẫn
  ảnh ở ancestor chung. Loại ảnh bridge khỏi kết quả của chính đường đó.
- Caption được đối chiếu theo cụm tường minh, giữ dấu tiếng Việt. Lưu đoạn caption/
  record hỗ trợ từng điều kiện. Thiếu cụm hoặc phủ định chưa có bằng chứng => unverified.
  Không suy thiếu từ là sai và không dùng label benchmark làm bằng chứng.
- Liên kết nhiều entity hoặc nguồn không chắc chắn bị cách ly khi cần định danh entity.
  Các ứng viên bị loại vẫn lưu lý do; không tự sửa catalog để khớp kết quả model.
- `hypotheses` chứa entity, các đường bridge, candidates/results và count_status riêng.
  Còn nhiều giả thuyết => ambiguous_entity, results cấp group rỗng; không trộn ảnh hoặc
  cộng số ảnh của entity khác nhau để đáp ứng yêu cầu. candidates cấp group chỉ để xem xét.
- `count_status` có thể là not_requested, insufficient_candidates, unverified,
  supported_by_metadata hoặc unresolved_entity. Số lượng hỗ trợ bởi metadata không
  đồng nghĩa các ảnh đã được xác minh thị giác. `visual_verification=not_performed`.
- Trạng thái toàn kế hoạch phân biệt candidate_results, partial_results, unresolved
  và needs_clarification. Thiếu entity/bridge không fallback tìm toàn kho.
- Beam mặc định 3 entity, 2 đường/entity; tối đa 64 tổ hợp khi ghép nhiều dependency.
  Đường bị giới hạn tổ hợp được gắn path_join_truncated; hết budget mà chưa ghép được
  trả path_budget_exceeded, không giả làm kết luận không có đáp án.

Cùng lệnh retrieval, thêm hai settings `IMAGE_SEARCH_RETRIEVAL_PATHS_PER_ENTITY` và
`IMAGE_SEARCH_RETRIEVAL_PATH_COMBINATION_LIMIT` nếu cần thay giới hạn.

```bash
HF_HUB_OFFLINE=1 OPENBLAS_NUM_THREADS=1 image-search-retrieval var/retrieval-v1/planner/predictions.jsonl --method all --output-dir var/executor-v1/new-live
```

Đã kiểm tra lại cùng 6 kế hoạch thật ở bước 4, giữ nguyên input/vector/prompt, không gọi
lại API. Artifact mới ở `var/executor-v1/`: `cached/`, `live/`, `index.html`, `report.md`
và `verification.json`. HTML hiển thị từng giả thuyết và các đường bằng chứng.
Phép đo tính cả kế hoạch unresolved/partial; không loại chúng để làm đẹp p90.
Chưa đánh giá chất lượng retrieval toàn tập. Xác minh thị giác/rerank thuộc bước 6.


## Lưu vector vào Qdrant

Vector ảnh và metadata index chỉ lưu trong Qdrant; không có backend NumPy hoặc
cache vector trên đĩa. Query embedding chỉ ở RAM. BM25 và RRF chuẩn 1:1 giữ nguyên.

```bash
docker compose up -d qdrant
uv sync --frozen --extra baseline --extra planner
uv run image-search-qdrant
```

Lệnh lập index trực tiếp từ ảnh; nếu collection đã có, kiểm tra và dùng lại.
Collection khác model/revision/corpus bị từ chối; dùng tên collection mới khi đổi model.

- URL: `http://localhost:6333`; Dashboard: <http://localhost:6333/dashboard>.
- Collection ảnh: `image_search_siglip2_v1`, 1.886 vector, 768 chiều, cosine.
- Collection metadata: `image_search_siglip2_v1_metadata`, một bản ghi cấu hình
  model/revision, processor, image IDs, kích thước và fingerprint index.
- Dữ liệu bền vững: Docker volume `images-search_qdrant-data`, mount `/qdrant/storage`.
- Ảnh gốc: `var/images/`; BM25 metadata: `var/hybrid-v1/keyword-index/`.

Cấu hình: `IMAGE_SEARCH_QDRANT_URL`, `IMAGE_SEARCH_RETRIEVAL_QDRANT_COLLECTION`.
Tìm cosine với `exact=True`, lọc phạm vi trước top-K; chưa đánh giá ANN/HNSW.
Qdrant không chạy hoặc thiếu dữ liệu => báo lỗi, không tự chuyển backend.
Không chạy `docker compose down -v` nếu muốn giữ dữ liệu.

Các file vector và cache cũ đã được xóa; báo cáo benchmark lịch sử vẫn được giữ
và không đại diện cho phép đo lại sau chuyển đổi. Kiểm tra live sau khi bỏ file
vector: `var/qdrant-v1/verification-live.json`, `var/qdrant-v1/live/index.html`.
