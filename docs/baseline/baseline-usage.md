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

Keyword index được dựng trong RAM từ payload Qdrant khi khởi tạo. Không đọc/ghi
keyword index trên đĩa; đã bỏ `--keyword-dir` và `IMAGE_SEARCH_RETRIEVAL_KEYWORD_DIR`.
Nhánh keyword giữ BM25/tokenizer/IDF toàn corpus và không nạp encoder.

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
Các tham số `--threads`, `--batch-size` đặt trước subcommand.


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
Không ghi đè output đã có. Dùng `IMAGE_SEARCH_RETRIEVAL_QDRANT_COLLECTION` để chọn collection,
`IMAGE_SEARCH_EMBEDDING_` cho encoder và `IMAGE_SEARCH_RETRIEVAL_` cho shortlist.
Model và processor phải khớp image index.

- Vector cosine, BM25 và RRF chuẩn 1:1 dùng lại thuật toán baseline.
- Named entity được tra qua Neo4j theo tên chuẩn hóa; Qdrant giữ metadata lọc/ảnh.
  Có thể cấp `--aliases file.json` theo dạng alias -> list entity ID thật trong catalog.
  Không đọc đáp án benchmark để tạo alias. Tên không khớp trả no_graph_match,
  không bỏ điều kiện entity rồi tìm toàn kho.
- Qdrant lọc `entity_ids` và ID ảnh graph trước vector top-K.
  BM25 giữ IDF toàn corpus; tập ID hợp lệ lấy bằng cùng filter Qdrant trước cắt K.
- Mỗi mục tiêu có candidates (mặc định top-100) và results (count yêu cầu hoặc giới hạn
  hiển thị 10 nếu count=null). Thiếu ảnh chỉ báo insufficient_candidates nếu có count
  tường minh; không bù bằng ảnh của target khác. Chưa kiểm chứng điều kiện thị giác.
- Phạm vi ảnh lấy qua DEPICTS trong Neo4j và lọc cùng Qdrant trước top-K.
- Dependency có điều kiện graph được thực thi trước khi tìm ảnh đích. Graph hỗ trợ
  LOCATED_IN/PART_OF/BRANCH_OF và visual bridge (xem dưới); quan hệ ngoài schema trả
  `unsupported_graph_relation`. Multi-target giữ các mục tiêu chạy được.
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


## Visual bridge

Bước `resolve_entity` có điều kiện thị giác (hoặc không có graph) được nhận diện qua ảnh:

1. Graph giới hạn phạm vi. `LOCATED_IN` bắc cầu (quận → tỉnh; bộ phận theo công trình), không
   lọc kind/category ở bước này. Entity chưa có vị trí nào được giữ vì chưa biết, không phải sai.
   Tên không có trong graph được giữ trong câu tìm kiếm nhưng không lọc được (`unmatched_names`),
   chỉ khi câu có mô tả nhận diện; các quan hệ khác vẫn lọc. Không có mô tả: `no_graph_match`.
   Nơi đã có tên trong câu dùng cùng quy tắc qua `identity_text`; tên có trong graph thì không nới.
2. Tìm `search_text` của bước bằng phương pháp đang chọn (hybrid: RRF 1:1) trong phạm vi đó.
3. Xếp hạng entity theo ảnh điểm cao nhất. Nơi graph xác nhận thắng nơi chưa rõ vị trí nếu kém
   điểm đầu không quá `IMAGE_SEARCH_RETRIEVAL_BRIDGE_MARGIN` (mặc định 0,1); sau đó so các ảnh
   tiếp theo. Bằng hoàn toàn thì `ambiguous_entity`, không trả ảnh.
4. Tìm ảnh đích chỉ trong entity đứng đầu, không tự mở rộng sang cha/con.

Kết quả ghi `verification_status=visual_bridge_unverified`; `trace` giữ
`IMAGE_SEARCH_RETRIEVAL_BRIDGE_HYPOTHESES` ứng viên (mặc định 3) kèm ảnh bằng chứng và
`graph_confirmed`. Chưa có ngưỡng từ chối: nơi không có trong kho vẫn có thể nhận một suy đoán.
"cùng thành phố/tỉnh…", "cách …", "chủ đầu tư" vẫn là quan hệ chưa hỗ trợ; "gần …" được coi
là mô tả nhìn thấy.

Đo 25/11/2026, hybrid, `var/visual-bridge-v1/fix-final` (plan v6 đã lưu, compile lại, không gọi
API), trung bình theo câu:

| Nhóm | Không bridge | Bridge đầu tiên | Hiện tại |
|---|---:|---:|---:|
| Multi-hop dev (19) R@10 | 0,000 | 0,789 | 0,842 |
| Multi-hop test (23) R@10 | chưa đo | 0,261 | 0,913 |
| Multi-hop test nDCG@10 | chưa đo | 0,201 | 0,775 |
| Single dev / test (29 / 18) R@10 | 0,658 / 0,792 | không đổi | 0,693 / 0,792 |
| Multi-target dev / test (18 / 12) R@10 | 0,339 / 0,506 | không đổi | không đổi |

Multi-hop test canonical lấy trung bình theo ý định: 0,933; baseline tìm cả câu: keyword 0,933,
hybrid 0,600, vector 0,333. Nơi được nhận diện đúng ở mọi câu có nhãn đã chạy bridge.
**Không phải kết quả holdout:** các sửa đổi được chọn sau khi xem lỗi trên chính tập test này.
Độ nhạy biên 0 / 0,05 / 0,1 / 0,2: test R@10 0,870 / 0,913 / 0,913 / 0,870.
Embedding + retrieval câu bridge p50/p90 359/411 ms, câu khác 162/252 ms; chưa gồm planner.

Còn trượt: q0303 (plan lỗi), q0310, q0320 (không khớp graph, plan không có mô tả nhận diện riêng),
q0053 và q0365 (planner sinh nơi chứa thừa). Rủi ro: tên thật nhưng không có trong kho, kèm mô tả,
có thể nhận một nơi khác; chưa có ngưỡng từ chối. Câu hỏi sinh từ metadata nên thuận lợi cho BM25.

## Executor — bước 5

Graph quan hệ thật đã nhập từ extraction Codex điền trực tiếp, không gọi API.
Dữ liệu ở `var/graph-manual-v1/`, gồm 1.886 Image, 319 Entity và 301 quan hệ nghiệp vụ.
`prepare`/`build` hỗ trợ điền metadata và dựng lại graph mà không gọi model.
Xem [lệnh và phạm vi rà soát](../../README.md#graph-quan-hệ-neo4j).

Planner v3 có GraphQuery: chọn loại/tên đích, AND/OR các đường quan hệ có hướng,
anchor theo tên hoặc kết quả bước trước. Neo4j trả entity đích, ánh xạ về ID nguồn
trong Qdrant; vector/BM25/RRF tìm ảnh trong cùng phạm vi. Tin liên kết metadata yes,
ảnh dùng chung không bị loại chỉ vì có nhiều entity. Không gọi model trích xuất khi search.
Các điều kiện thị giác còn được xếp hạng bằng retrieval, chưa có reranker.

Các kết quả executor-v1/source-graph-v1 cũ là lịch sử, không phải kết quả graph mới.


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
- Ảnh gốc: `var/images/`; BM25 dựng trong RAM từ payload.

Payload ảnh có `records` giữ toàn bộ metadata nguồn và provenance theo từng record,
`entity_ids`, `entity_names`, `entity_name_keys`, `captions`, `leaf_labels`, `page_titles`,
`image` (ID/đường dẫn ảnh), `metadata_schema` và fingerprint `search_metadata_sha256`.
Các tên/caption ở record riêng tránh gán nhầm entity khi một ảnh có nhiều liên kết.

Với collection đã có vector nhưng chưa có metadata đầy đủ:

```bash
uv run image-search-qdrant --sync-metadata
```

Lệnh đọc nguồn đã pin một lần khi nhập, kiểm tra corpus/hash, cập nhật payload bằng
`set_payload` (không encode hoặc ghi lại vector), kiểm tra đủ ảnh/snapshot rồi lưu
fingerprint trong collection metadata. Có thể chạy lại cùng nguồn.
Runtime tra entity/quan hệ qua Neo4j, lọc metadata và tìm ảnh qua Qdrant; không đọc
CSV, JSONL nguồn, benchmark manifest hoặc keyword index local. File nguồn vẫn giữ
cho nhập dữ liệu/đánh giá; ảnh/model vẫn ở local. Alias truyền tường minh qua CLI
là cấu hình bổ sung, không phải fallback về file metadata.

Cấu hình: `IMAGE_SEARCH_QDRANT_URL`, `IMAGE_SEARCH_RETRIEVAL_QDRANT_COLLECTION`.
Tìm cosine với `exact=True`, lọc phạm vi trước top-K; chưa đánh giá ANN/HNSW.
Qdrant không chạy hoặc thiếu dữ liệu => báo lỗi, không tự chuyển backend.
Không chạy `docker compose down -v` nếu muốn giữ dữ liệu.

Các file vector và cache cũ đã được xóa; báo cáo benchmark lịch sử vẫn được giữ
và không đại diện cho phép đo lại sau chuyển đổi. Kiểm tra live sau khi bỏ file
vector: `var/qdrant-v1/verification-live.json`, `var/qdrant-v1/live/index.html`.


Kiểm tra metadata: `var/qdrant-metadata-v1/verification.json`;
6 kế hoạch thật (2 câu mỗi loại), vector/keyword/hybrid:
`var/qdrant-metadata-v1/live/index.html`. Đây là kiểm tra tích hợp, chưa chạy lại
benchmark 400 câu hoặc thay chính sách entity/multi-hop/reranking.
Tham khảo [Qdrant filtering](https://qdrant.tech/documentation/search/filtering/).
