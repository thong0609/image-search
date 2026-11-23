# Kế hoạch tự triển khai baseline tìm kiếm ảnh

## Trạng thái và mục tiêu

Pipeline baseline đã có CLI cho các bước dưới đây; xem [hướng dẫn chạy](baseline-usage.md).
Code dùng các hàm đơn giản, chia file theo tải ảnh, benchmark, vector và đánh giá.
Bộ nhãn thật cần được sửa và xác nhận trước khi đo; không dùng lại dữ liệu/kết quả cũ.
Mục tiêu là có một baseline vector đơn giản, tìm bằng câu tiếng Việt và đo riêng ba dạng **single**, **multi-target**, **multi-hop** trước khi thử các cải tiến.

## Dữ liệu đầu vào

Nguồn hiện có trong workspace:

```text
data/general_10m_part_02_18-11-2026_CHIEU_To_Huy_Thong.csv
```

CSV có các cột `entity_id`, `entity_name`, `leaf_label`, `image_url`, `image_width`, `image_height`, `page_url`, `page_title`, `image_domain`, `mo_ta`, `approve`. Chỉ dùng record có `approve` đúng chuỗi `yes`; đây là dữ liệu đã được duyệt, không thêm bước duyệt lại ảnh nguồn.

`data/` đã được Git bỏ qua. Giữ nguyên CSV gốc; không sử dụng lại danh sách ba CSV, số lượng ảnh/query hay điểm đánh giá của baseline cũ. Thống kê lại trên nguồn hiện tại khi thực hiện bước 1.

## Cách tổ chức đơn giản

Pipeline nằm trong package `src/image_search/baseline/`, chia module theo từng công việc.
CLI điều phối các hàm đơn giản; chưa cần thêm tầng kiến trúc hoặc bộ file trong `configs/`.

- Truyền đường dẫn CSV, thư mục output và các tham số cần thay đổi qua CLI khi triển khai.
- Giữ các giá trị mặc định ở một chỗ trong code. Ghi lại giá trị thực tế đã dùng cùng kết quả chạy để tái lập.
- Dependency/lockfile và lệnh chạy thực tế đã được bổ sung; output sinh trong `var/` khi chạy.
- Dùng `var/` cho ảnh và kết quả sinh ra; thư mục này đã được Git bỏ qua. Không commit ảnh riêng, model hoặc khóa API.

Luồng chính:

```text
CSV → lọc record → tải ảnh → tạo query/đáp án → cố định benchmark
    → mã hóa ảnh → tìm bằng câu hỏi → chấm điểm → phân tích lỗi
```

## 1. Đọc CSV và lọc record

Đọc CSV bằng thư viện `csv`, kiểm tra các cột bắt buộc, lọc chính xác `approve == "yes"`. Bỏ `.bak` và chỉ đọc file được truyền vào, không tự chọn theo thời gian sửa file.

Giữ URL ảnh, entity, mô tả, metadata gốc và vị trí record trong CSV để truy vết. Một URL có thể xuất hiện trong nhiều record; chưa gộp mất các liên kết đó. Báo rõ record sai cấu trúc hoặc giá trị không hợp lệ.

**Đầu ra đề xuất:** `var/records.jsonl`, mỗi dòng là một record đã duyệt; thống kê số record, entity và URL ảnh duy nhất. Chưa tải ảnh ở bước này.

**Kiểm tra:** chỉ record `yes` được lấy; các giá trị `no`, trống, `YES`, ` yes ` bị loại; CSV thiếu cột có thông báo lỗi rõ ràng.

## 2. Tải ảnh và gắn định danh

Từ các URL trong record đã lọc, tải thử một nhóm nhỏ trước khi chạy toàn bộ. Đặt timeout, giới hạn kích thước, số tác vụ đồng thời và số lần thử lại. Chỉ truy cập HTTP(S) public; kiểm tra cả đích redirect. Kiểm tra file giải mã được thành ảnh và ghi nhận kích thước thực tế.

Dùng SHA-256 bytes ảnh làm `image_id` và tên file để lưu một bản cho ảnh trùng chính xác. Giữ đầy đủ các liên kết record–ảnh–entity. Ghi lỗi tải riêng; URL lỗi không trở thành ví dụ “không có đáp án”. Cho phép chạy tiếp mà không tải lại file đã kiểm tra thành công.

**Đầu ra đề xuất:** ảnh trong `var/images/`; bổ sung vào record trạng thái tải, `image_id`, đường dẫn local và lỗi nếu có. Giữ bản record trước tải để truy vết.

**Kiểm tra:** ảnh hợp lệ, ảnh trùng bytes, file không phải ảnh, timeout và khả năng chạy tiếp; dùng request giả lập thay cho mạng thật trong test.

## 3. Tạo câu hỏi và đáp án chuẩn

Bắt đầu bằng vài câu mỗi dạng để kiểm tra luồng, sau đó mở rộng khoảng 50–100 câu. Có đủ ba dạng trong dev và test:

| Dạng | Ý nghĩa | Đáp án cần lưu |
| --- | --- | --- |
| Single | Một mục tiêu theo tên entity hoặc mô tả nội dung | Các `image_id` phù hợp |
| Multi-target | Nhiều mục tiêu trong cùng câu | Tập ảnh đúng và số ảnh yêu cầu cho từng mục tiêu |
| Multi-hop | Dùng bằng chứng trung gian để xác định ảnh đích | Ảnh đích và chuỗi liên kết có bằng chứng |

Ví dụ cấu trúc multi-hop: “Tìm ảnh lớp học của trường có ảnh cổng vòm cầu vồng”. Chỉ dùng khi dữ liệu hiện tại có bằng chứng: ảnh cổng → entity trường → ảnh lớp học. Không suy diễn quan hệ từ tên trường. Nhiều mục tiêu trong một câu không tự đồng nghĩa với multi-hop.

Viết câu hỏi độc lập, tránh sao chép nguyên mô tả CSV. Tạo đáp án từ các liên kết và mô tả đã duyệt; điều kiện mới cần được gán nhãn rõ ràng. Ảnh không được liệt kê trong đáp án chưa mặc nhiên là ảnh sai về thị giác.

Bổ sung một số câu không có đáp án đã xác minh trong kho; tách các câu tổng hợp thành nhóm riêng. Chia dev/test theo nhóm entity, bằng chứng và ảnh trùng/gần trùng liên quan để giảm rò rỉ nhãn. Kho ảnh tìm kiếm có thể dùng chung.

**Đầu ra đề xuất:** `var/queries.jsonl` chứa ID, câu hỏi, loại và split; `var/answers.jsonl` chứa đáp án theo từng mục tiêu và bằng chứng. Giữ đáp án riêng khỏi đầu vào retrieval.

## 4. Cố định bộ đánh giá

Trước khi đo baseline, cố định danh sách ảnh, hash CSV, câu hỏi, đáp án, split và quy tắc chấm. Có thể lưu một manifest nhỏ trong `var/`; chưa cần xây công cụ snapshot riêng hoặc sao chép thêm toàn bộ kho ảnh.

Ghi lại phạm vi thực tế của dữ liệu mới sau khi thống kê. Dùng dev chọn model/tham số/ngưỡng; chỉ đánh giá test tại các mốc đã chọn. Khi thay corpus, query hoặc nhãn, tạo phiên bản đánh giá mới và chạy lại các phương pháp cần so sánh.

**Điều kiện hoàn tất:** mọi ảnh đáp án tồn tại trong kho, không có ID trùng hoặc liên kết thiếu, mỗi query có split và thông tin answerability rõ ràng.

## 5. Tạo vector và tìm kiếm

Chọn một encoder ảnh–văn bản có thể xử lý tiếng Việt và chạy trên máy local. Chưa chốt lại model; SigLIP 2 của lần triển khai trước chỉ là một ứng viên. Thử trên nhóm ảnh nhỏ, kiểm tra RAM và thời gian trước khi tải/mã hóa toàn kho.

Cố định checkpoint/revision và tiền xử lý. Mã hóa ảnh và câu hỏi vào cùng không gian vector, chuẩn hóa L2 rồi xếp hạng bằng cosine similarity. Với tập nhỏ, bắt đầu bằng tìm kiếm chính xác; lưu thứ tự `image_id` tương ứng từng hàng vector.

Baseline nhận nguyên câu hỏi, áp dụng cùng cách tìm kiếm cho cả ba dạng. Đáp án và đường suy luận chuẩn chỉ phục vụ chấm điểm. Chưa thêm tách mục tiêu, graph, keyword hoặc reranker; dùng kết quả này làm mốc so sánh.

**Đầu ra đề xuất:** vector và danh sách ID trong `var/`; mỗi dự đoán có `query_id`, danh sách ảnh theo thứ hạng và điểm. Có cách mở ảnh kết quả để kiểm tra bằng mắt. Phát hiện cấu hình không tương thích trước khi dùng lại vector.

## 6. Đo chất lượng và hiệu năng

Chốt quy tắc trước khi chạy: top-K = 1/5/10, bỏ ID trùng trước khi cắt K, thứ tự ổn định khi bằng điểm, ID lạ hoặc thiếu query là lỗi đầu ra.

- Đo Known-Recall@K, Known-nDCG@K và Hit@K trên nhãn đã biết; không diễn giải thành Recall thị giác đầy đủ.
- Với multi-target, chấm cùng danh sách top-K cho từng mục tiêu, đo thêm tỷ lệ mục tiêu đủ số ảnh yêu cầu và tỷ lệ câu đủ tất cả mục tiêu.
- Với multi-hop, chấm ảnh đích theo toàn bộ điều kiện đã xác nhận. Chỉ chấm đường suy luận khi phương pháp có trả đường đó.
- Ca không có đáp án được chấm riêng, không đưa vào trung bình Recall/nDCG có mẫu số bằng 0. Nếu có cơ chế từ chối, chọn ngưỡng trên dev và yêu cầu kết quả rỗng rõ ràng; baseline chưa hỗ trợ thì ghi nhận giới hạn.
- Lấy trung bình theo mục tiêu trong mỗi query rồi theo query; báo cáo riêng dev/test, từng dạng câu và nhóm tổng hợp/không có đáp án.

Đo độ trễ p50/p95 sau warmup, chạy một request mỗi lần, tắt cache query/result và lặp ba vòng theo thứ tự có seed cố định. Tách thời gian tải/nạp model và lập chỉ mục khỏi thời gian truy vấn. Ghi RAM đỉnh, thời gian tạo vector, dung lượng index, phần cứng, phiên bản code/model và tham số thực tế.

**Đầu ra đề xuất:** một báo cáo tổng hợp và kết quả từng query trong `var/`, kèm lỗi điển hình. Test các tình huống đáp án rỗng, dự đoán trùng, mục tiêu thiếu và ID không hợp lệ bằng fixture cố định.

## 7. Cải tiến sau baseline

Dựa vào lỗi thực tế để lần lượt thử tách multi-target, keyword/hybrid, graph cho multi-hop hoặc reranker. Mỗi lần ghi rõ thay đổi và so sánh trên cùng bộ đánh giá, cùng điều kiện đo; không tối ưu theo điểm test.

Đã bổ sung lựa chọn `--method keyword` (BM25 metadata) và `--method hybrid`
(vector + keyword, RRF chuẩn hệ số 1:1) để thử bước cải tiến này. Phương pháp mặc định vẫn là vector.
Xem lệnh và giới hạn so sánh trong [hướng dẫn chạy](baseline-usage.md).

## Mốc hoàn tất

Baseline hoàn tất khi có ảnh tải lại từ CSV hiện tại, bộ query/đáp án cho đủ ba dạng, tìm kiếm vector chạy được và báo cáo chất lượng/hiệu năng tái lập được. Triển khai lần lượt: đọc CSV → tải ảnh → nhãn đánh giá → vector → tìm kiếm → đo; hoàn thành và kiểm tra từng bước trước khi mở rộng.
