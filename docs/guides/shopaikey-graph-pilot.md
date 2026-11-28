# Thử extraction qua ShopAIKey

Pilot riêng, không thay planner website hoặc ghi graph. Điền key riêng vào `.env`:

```dotenv
SHOPAIKEY_API_KEY=your-shopaikey-key
SHOPAIKEY_BASE_URL=https://api.shopaikey.com/v1
SHOPAIKEY_MODEL=gpt-6-luna
```

`gpt-6-luna` là ID dự kiến theo yêu cầu Luna 6, chưa được xác nhận. Lấy ID chính xác:

```bash
uv run --with jsonschema python scripts/shopaikey_graph_pilot.py --list-models
```

Đặt SHOPAIKEY_MODEL đúng ID Luna mà /models trả về, rồi thử một nhóm:

```bash
uv run --with jsonschema python scripts/shopaikey_graph_pilot.py
```

Mặc định dùng `var/kaggle-graph-pilot/{inputs.json,prompt.txt,schema.json,run_pilot.py}`
của gói GPU đã chuẩn bị. Đường dẫn khác truyền bằng --data-dir. Artifact đầu ra nằm ở
`var/shopaikey-graph-pilot/`. Cùng cấu hình sẽ dùng lại response đã lưu; cấu hình khác
phải chọn --output-dir mới. Dùng --limit 3 để thử ba nhóm, --limit 0 cho cả mẫu 50 record.

Không tự retry hoặc hạ từ json_schema sang JSON tự do nếu provider báo lỗi; cần xem
khả năng tương thích trước khi đổi cấu hình và phát sinh thêm lượt gọi. Không tự gửi
reasoning_effort hoặc temperature vì chưa xác nhận Luna hỗ trợ các tham số đó.

Lưu usage nguyên bản, thời gian, output gốc, output chuẩn hóa, các sửa tham chiếu và lỗi.
Chưa áp giá OpenAI cho provider này; summary để cost=null tới khi có giá tính thực tế.
Chỉ khớp tên/alias duy nhất mới sửa thành key; không tự tạo node thiếu. Qua validator
không chứng minh graph đúng ngữ nghĩa. Key không ghi vào artifact hoặc lấy từ OPENAI_API_KEY.

Endpoint tham chiếu: https://shopaikey.com/ (mục Endpoint API).
