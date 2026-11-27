# Website local

Website dùng pipeline SigLIP2 + BM25 hiện có, RRF hai nhánh; không bật vector text thử nghiệm.
PostgreSQL giữ tài khoản, trạng thái công bố và snapshot phân trang. Vector và metadata ảnh vẫn ở
Qdrant; Neo4j phục vụ xác định nơi chứa như pipeline đã đánh giá.

## Khởi tạo

```bash
uv sync --frozen --extra baseline --extra planner
docker compose --profile graph up -d postgres qdrant neo4j
uv run alembic upgrade head
uv run image-search-admin init-key
uv run image-search-admin sync-catalog
uv run image-search-admin create-admin --email admin@example.com --name "Quản trị viên"
```

`init-key` chỉ chạy lần đầu, không ghi đè khóa có sẵn. Khóa RSA ở `var/auth/private.pem`, quyền file
0600; giữ ngoài Git và sao lưu riêng. `create-admin` nhập mật khẩu qua terminal, không có mật khẩu mặc
định. `sync-catalog` đăng ký snapshot Qdrant đã kiểm chứng, không mã hóa lại ảnh và không hồi sinh ảnh
đã gỡ. Index khác phải được chuyển qua bảo trì; lệnh từ chối chuyển ngầm.

```bash
HF_HUB_OFFLINE=1 uv run uvicorn image_search.main:app --host 127.0.0.1 --port 8000
cd frontend
npm ci
npm run dev
```

Mở http://127.0.0.1:3000. PostgreSQL giờ là dependency của website. Các lệnh benchmark vẫn có thể
chạy trực tiếp trên Qdrant/Neo4j, không phụ thuộc tài khoản website.

## Các màn hình

- `/`: tìm ảnh, lọc collection/hướng/kích thước, xem thêm kết quả. Query và filters ở URL; ảnh đã chọn
  được giữ khi đi qua đăng nhập. Mỗi mục tiêu vẫn có tối đa 20 ảnh; giao diện tải 10 ảnh mỗi trang.
- `/login`: đăng nhập bằng tài khoản được admin cấp. Không đăng ký công khai.
- `/account`: xem thông tin, đổi mật khẩu và đăng xuất.
- `/admin`: admin cấp tài khoản, đổi role, khóa/mở khóa. Không khóa/hạ quyền admin hoạt động cuối cùng.
- `/admin/images`: duyệt ảnh và gỡ khỏi kho công khai. Gỡ là tombstone SQL, không xóa file hay vector
  vật lý; ảnh bị chặn ở search, thumbnail, preview, download và các trang snapshot tiếp theo.
- `/playground`: công cụ chẩn đoán chỉ dành cho admin.

Khách tìm ảnh/xem thumbnail. Detail, preview và download đều kiểm tra bearer token ở backend. Preview
và download dùng proxy xác thực, không công khai URL file gốc; frontend tạo blob URL tạm thời để hiển
thị/tải xuống. File đã được người dùng tải về không thể thu hồi.

## Token và cấu hình

- Access JWT RS256: 15 phút, giữ trong bộ nhớ frontend.
- Refresh: cookie HttpOnly, SameSite=Strict, Path=/v1/auth; family có hạn tuyệt đối 7 ngày.
- Refresh rotate một lần; reuse thu hồi family. Logout thu hồi ngay cả access token hiện hành.
- Đổi mật khẩu/role/status thu hồi mọi family của tài khoản. PostgreSQL được kiểm tra ở mỗi API bảo vệ.
- Auth cookie endpoints kiểm tra Origin allowlist, JSON và `X-Auth-Request: 1`.
- Local HTTP dùng cookie `refresh_local`; HTTPS phải đặt `IMAGE_SEARCH_AUTH_COOKIE_SECURE=true`
  để dùng `__Secure-refresh`. Cấu hình Origin chính xác qua `IMAGE_SEARCH_AUTH_ORIGINS`.
- Khóa hiện hành có kid `local-v1`; chưa có giao diện xoay khóa. Đổi khóa làm JWT cũ mất hiệu lực.
- Giới hạn login: 10 lượt/phút/IP/process. Pilot local dùng một API process; triển khai nhiều process
  cần rate limit chung tại gateway.

Không đưa JWT vào URL hoặc localStorage. Frontend refresh single-flight trong tab và dùng Web Locks
để phối hợp các tab; không retry refresh sau timeout. Login/logout xóa cache kết quả phía trình duyệt.

## Tìm kiếm và snapshot

POST `/v1/search` nhận query + filters hoặc cursor, không nhận đồng thời. Header `X-Search-Owner` là
chuỗi ngẫu nhiên của tab, dùng ràng buộc snapshot, không dùng cấp quyền ảnh. Cursor có HMAC phía server,
TTL 15 phút; đọc trang sau không gọi planner/encoder lại. SQL lưu ID ảnh/record và thông tin nhóm;
metadata hiển thị lấy từ catalog Qdrant đã nạp. Trang sau kiểm tra lại tombstone.

Filters được áp dụng trước top-K vector/BM25, không chỉ lọc sau khi nhận 20 ảnh. Hướng/kích thước của
ảnh đích không giới hạn ảnh bằng chứng visual bridge; tombstone áp dụng cho cả hai. Collection hiện
có là “Kho ảnh đã duyệt”, không phải ACL hoặc leaf_label.

## Kiểm tra

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
RUN_AUTH_INTEGRATION=1 uv run pytest tests/integration/test_auth.py tests/integration/test_catalog.py tests/integration/test_csv_admission.py tests/integration/test_csv_publishing.py
cd frontend
npm run lint
npm run typecheck
npm run format:check
npm run build
```

Test auth tạo schema PostgreSQL riêng và dọn sau khi chạy, không sửa tài khoản/kho thật. Screenshot
kiểm tra giao diện nằm trong `var/website-review/`.

## Phạm vi còn lại

Nhập CSV qua website và worker batch đã được bổ sung theo phần hướng dẫn bên dưới.
Chưa có crawler, VLM rerank, purge vật lý hoặc giao diện maintenance.
Không coi bản website local hiện tại là hoàn tất toàn bộ FR01–FR18 của PRD hay nghiệm thu mục tiêu
100k–1M ảnh/độ trễ. Các quyết định mới về phạm vi này phải được ghi lại khi người dùng chốt.

## Nhập CSV theo batch

Trang `/admin/imports` nhận CSV UTF-8/BOM theo các cột của dataset hiện có. Chọn file, kiểm tra trước,
chọn collection, rồi bắt đầu nhập. `approve=yes` mới được xử lý. File tối đa 10 MiB/10.000 dòng;
dòng sai được giữ lại với số dòng và lỗi. Có thể đóng trình duyệt; jobs ở PostgreSQL.

Chạy worker ở process riêng:

```bash
HF_HUB_OFFLINE=1 uv run image-search-worker
# Hoặc xử lý một lượt nhập rồi thoát:
HF_HUB_OFFLINE=1 uv run image-search-worker --once
```

Worker tải URL HTTP(S) public, kiểm tra redirect/IP, tối đa 25 MiB/40 megapixel, chỉ JPEG/PNG/WebP
tĩnh. File gốc và checkpoint nằm trong storage_root/imports; thumbnail được tạo khi xử lý. Embedding
microbatch lấy IMAGE_SEARCH_EMBEDDING_BATCH_SIZE (mặc định 8). Dùng đúng model/revision/processor của
index đang phục vụ. Chỉ vector mới được encode; vector cũ sao chép trong RAM sang collection snapshot
mới. Không có file vector NumPy. Snapshot Neo4j giữ quan hệ cũ và thêm liên kết ảnh–entity; entity mới
chỉ có tên/nhãn/liên kết ảnh, không tự tạo quan hệ vị trí hoặc gọi extraction API.

Có một worker ghi tại một thời điểm, bằng PostgreSQL advisory lock. Worker crash giải phóng lock;
job running được tiếp tục ở lần chạy sau. Checkpoint ảnh và staging Qdrant tránh tải/encode lại phần
đã hoàn tất. Graph/Qdrant phải được kiểm tra trước khi đổi active search_configs trong transaction.
Backend nạp lại engine/BM25 khi thấy collection mới; snapshot phân trang cũ hết hiệu lực.

Nhập cùng request id trả lại import_id cũ. Khóa record là entity_id + image_url trong nguồn CSV hiện
hành; dòng trùng hoàn toàn trong file được bỏ qua, trùng khóa khác metadata là lỗi. Khi nhập lại,
metadata không đổi được bỏ qua; metadata đổi được thay ở snapshot mới. Nguồn URL thay byte chỉ được
phát hiện khi record được xử lý lại; CSV y hệt được coi là không đổi, không tự tải lại để kiểm tra URL.
Không hỗ trợ namespace nguồn tùy chọn trong UI ở phiên bản này.

Trang chi tiết có tiến độ từng dòng, tải errors.csv và retry phần lỗi. Lỗi validation cần sửa CSV và
nhập lượt mới. Lỗi tải tạm thời có thể chọn retry; lỗi công bố có thể chạy lại từ staging. Chưa có retry
backoff tự động. Collection snapshot/staging cũ và media checkpoint được giữ để phục hồi, chưa có
cleanup tự động; cần tính dung lượng theo số lượt nhập. Tạo snapshot hiện sao chép toàn bộ vector,
phù hợp kho local hiện tại; chưa kiểm chứng quy mô 100k–1M.

Trong lúc worker xử lý một lượt nhập, tạm chặn ghi kho ảnh mới/gỡ ảnh; các lượt CSV đã nhận vẫn nằm
trong hàng đợi. Gate ghi giữ bền trong PostgreSQL nếu worker crash và được gỡ khi worker tiếp tục
hoàn tất/thất bại có kiểm soát. Search tiếp tục đọc snapshot hiện hành; khi active config đổi, các
snapshot phân trang cũ trả SEARCH_EXPIRED. Có thể có request đang tìm nhận lỗi cần tìm lại tại cutover.

## Chuẩn bị tìm kiếm khi API khởi động

Mặc định API nạp catalog/BM25/graph và SigLIP2 vào RAM ngay khi process khởi động, rồi warmup một lượt
embedding văn bản + retrieval. Warmup không gọi planner hoặc mã hóa lại kho ảnh. Mỗi process có runtime
riêng. `/health/live` vẫn hoạt động trong lúc chuẩn bị; `/health/ready` trả 503 tới khi runtime sẵn sàng.
`/health/search` trả trạng thái `preparing`, `ready` hoặc `failed`, không lộ chi tiết nội bộ.

Website hiển thị một biểu tượng xoay khi chờ backend; chuẩn bị xong tự hiển thị giao diện mà không có
thông báo thành công. Các API search/playground trả 503 + Retry-After nếu bị gọi trước khi sẵn sàng.
Nếu chuẩn bị thất bại, readiness không báo thành công; kiểm tra cấu hình/dịch vụ và khởi động lại API
sau khi sửa nguyên nhân. `IMAGE_SEARCH_PRELOAD_SEARCH=false` chỉ dùng để tách inference khỏi test.
