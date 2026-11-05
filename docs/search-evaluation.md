# Thiết kế tìm kiếm và kế hoạch đánh giá

Trạng thái: đề xuất, chưa có số đo. Liên quan FR01–FR04, NFR01–NFR04. FR07 feedback đã bỏ; bộ nhãn benchmark offline vẫn cần thiết và không tạo tính năng feedback.

## 1. Baseline và các cấu hình so sánh

Baseline A: metadata keyword nếu có dữ liệu. Baseline B: image embeddings với text query encoder tương thích, không yêu cầu caption. Cấu hình C: hybrid B + keyword bằng RRF nếu baseline cho thấy bỏ sót tên riêng/mã hàng. Các cấu hình dùng cùng dataset, filters và tập truy vấn.

So sánh checkpoint CLIP và SigLIP 2 phù hợp tài nguyên; ghi revision chính xác, processor, dimension và normalization. Đây là ứng viên thử nghiệm, không phải lựa chọn model đã chốt. Đa ngôn ngữ phải được đo bằng truy vấn Việt thực tế; không suy diễn chất lượng từ tên model.

Qdrant là vector store đã chọn và giữ search metadata. Benchmark dùng chọn model, query/index configuration và topology; DB quan hệ không chạy nhánh tìm trên bản sao title/tags. Nhánh keyword nếu bật dùng khả năng lexical được cấu hình rõ trên Qdrant, không coi text filter là lexical ranker.

Nguồn tham khảo: [Sentence Transformers image search](https://www.sbert.net/examples/sentence_transformer/applications/image-search/README.html), [SigLIP 2](https://arxiv.org/abs/2502.14786), [Google model card](https://huggingface.co/google/siglip2-base-patch16-224), [Qdrant indexing](https://qdrant.tech/documentation/manage-data/indexing/), [Qdrant fusion](https://qdrant.tech/documentation/hybrid-queries/).

## 2. Query và retrieval

Chuẩn hóa Unicode NFC, trim khoảng trắng, giữ dấu và bản gốc; kiểm tra tokenizer trước inference. Không tự dịch hoặc mở rộng query trong baseline. Nếu thử dịch Việt→Anh, đánh giá như một cấu hình riêng với độ trễ và lỗi tên riêng.

Filters do API validate chuyển thành predicates phía server. Truy vấn vector tìm toàn kho đã công bố; collection chỉ là filter tùy chọn, không dựa trên user/role. Recheck catalog/pointer trước trả response. Nếu ANN trả thiếu do filter, có thể tăng search effort có giới hạn hoặc exact trên tập nhỏ theo query plan đã đo, không bỏ filter để có đủ số lượng.

Lấy 200 ứng viên cho snapshot là cấu hình đề xuất đầu; khi hybrid, thử lấy 200 mỗi nhánh trước fusion và cắt còn 200. Cần tăng retrieval effort phù hợp nếu dedup/threshold làm thiếu ứng viên. Limit UI không đồng nghĩa số ứng viên nội bộ.

RRF baseline: score(d) = tổng 1/(k + rank(d)), với rank bắt đầu từ 1 và k=60 là giá trị thử nghiệm ban đầu, không dựa vào default của thư viện. Lưu k và trọng số vào ranking_version. Không cộng cosine với lexical score chưa hiệu chỉnh.

Chỉ dedup theo image_id trong MVP bắt buộc; gộp ảnh gần giống cần nhãn kiểm chứng vì có thể che mất sản phẩm/phiên bản quan trọng.

## 3. Query không có đáp án

Nearest-neighbor vẫn trả ảnh gần nhất dù không phù hợp. Tạo riêng tập truy vấn không có đáp án trong phạm vi collection/filter. Khi chưa hiệu chỉnh được abstention, UI dùng “kết quả gần nhất” và không tuyên bố đã tìm đúng; rỗng chắc chắn khi không có ứng viên hợp lệ.

Nếu thêm score threshold, chọn trên tập development, đo tỷ lệ chấp nhận sai và từ chối sai trên tập test; threshold gắn với model/ranking profile. Không dùng chung threshold cho model mới hoặc coi cosine là xác suất. Ngưỡng semantic nghiệm thu chờ Q08.

## 4. Dữ liệu đánh giá và nhãn

Bắt đầu với 100–200 truy vấn thật, tăng khi phạm vi ảnh đa dạng. Lấy mẫu theo nhóm: đối tượng/cảnh, thuộc tính kết hợp, tên/mã, chữ trong ảnh, phong cách nếu có nhu cầu, phủ định/đếm/quan hệ, không dấu, ngoài miền và không có đáp án. Đánh dấu truy vấn đòi khả năng ngoài phạm vi để phân tích riêng.

Mỗi query có query_id, text, language, filters, intent_group, answerability, annotator_notes. Mỗi judgment có query_id, image_id, content_version, label, annotator_id và timestamp. Nhãn 0=sai, 1=một phần, 2=phù hợp. Annotator dùng dataset đã được phép xử lý; nhãn nằm trong bộ đánh giá offline, không có bảng/API feedback trong sản phẩm.

Pool ứng viên từ tất cả cấu hình được so sánh; randomize thứ tự khi gán nhãn để giảm thiên lệch. Hai người gán nhãn một phần dữ liệu và xử lý bất đồng trước khi mở rộng. Lưu version tập dữ liệu; không commit ảnh riêng hoặc query có dữ liệu nhạy cảm vào Git.

Chia development/test trước tuning; query cùng ý định hoặc diễn đạt gần nhau phải cùng phía để giảm leakage. Chỉ dùng development để chọn model, RRF, threshold. Nếu dùng test để sửa cấu hình nhiều lần, cần tập holdout mới cho kết luận cuối.

## 5. Chỉ số và cách diễn giải

| Chỉ số | Định nghĩa phục vụ báo cáo |
| --- | --- |
| Precision@10 | Số nhãn 2 trong 10 vị trí chia 10; nếu trả dưới 10, vị trí thiếu tính không phù hợp; báo thêm số kết quả trung bình |
| nDCG@10 | Gain 2^label−1, discount log2(rank+1); tính trên pool đã gán nhãn, ghi rõ độ phủ nhãn |
| Success@K | Có ít nhất một nhãn 2 trong K vị trí đầu |
| ANN Recall@100 | Giao ID với exact top-100 chia số exact neighbors hợp lệ; cùng vector, metric và filters; nếu tập exact rỗng thì báo riêng |
| No-answer false acceptance | Tỷ lệ query không có đáp án vẫn trả kết quả được hệ thống coi là đủ phù hợp |
| Answerable false rejection | Tỷ lệ query có đáp án bị hệ thống từ chối toàn bộ |

Query không có nhãn phù hợp không có IDCG dương: báo riêng, không gán nDCG=0 rồi trộn âm thầm. Báo kết quả theo nhóm và tổng macro-average; kết quả dựa trên pooled judgments không phải recall toàn kho.

Ties trong exact/ANN được xử lý bằng quy tắc ID ổn định hoặc báo tie-aware recall nhất quán. Không so ANN với exact trên tập không filter rồi kết luận chất lượng cho query có filter.

## 6. Hiệu năng và nghiệm thu

Hai mốc 100k/1M ảnh đại diện. Tải khám phá 1/5/20 QPS, filters có tỷ lệ match khoảng 50%/10%/1%; thay bằng tải mục tiêu khi Q03 chốt. Chạy warm/cold riêng, import bật/tắt riêng, ghi thời lượng và số request; mỗi kịch bản warm đề xuất 5 phút ổn định rồi đo 15 phút, điều chỉnh để đủ mẫu p95/p99 đáng tin.

Ghi p50/p95/p99, throughput thực, timeout/error rate, encode/Qdrant/catalog recheck timings, RAM/VRAM, CPU, disk I/O, payload index size và index build time. Đo outbox lag, tỷ lệ candidate cũ/chưa công bố bị loại, thời gian sync/purge và ảnh hưởng của batch writes. Load generator không được thành nút thắt. Không dùng vector nhân bản để thay cho kho ảnh đa dạng khi nghiệm thu.

Mục tiêu đề xuất: p95 warm < 2 giây và ANN Recall@100 ≥ 95%. Phải báo kèm QPS/phần cứng/filters; semantic quality, error budget và mức chênh lệch chấp nhận giữa các nhóm chờ chốt. Chưa thể tuyên bố MVP đạt yêu cầu khi các mục này còn trống.

## 7. Báo cáo thử nghiệm chuẩn

Mỗi lần chạy lưu experiment_id, dataset revision, query/judgment revision, model/processor revision, generation, ranking config, dependency versions, hardware, load config, raw measurements, summary và phân tích lỗi. Ghi cả cấu hình thất bại để tránh chọn lọc kết quả.

Phân loại lỗi: thiếu dữ liệu, sai ngữ nghĩa, sai OCR/tên, tokenizer/ngôn ngữ, filter/authorization, ANN miss, duplicate, stale version, timeout. Chỉ đề xuất OCR, reranker hoặc fine-tune sau khi xác định nhóm lỗi và chi phí cải thiện.
