# Thiết kế tài khoản, access token và refresh token

Cập nhật 06/11/2026 theo C13: chỉ dùng users và refresh_tokens cho auth; root token row thay bảng family riêng. Đã chốt: dùng access token + refresh token, không dùng session đăng nhập; vai trò visitor/user/admin; search/thumbnail public, detail/download cần đăng nhập; không ACL theo ảnh/collection và không feedback. Định dạng token, TTL và cookie transport dưới đây là đề xuất triển khai.

## 1. Phạm vi và vai trò

Tất cả mọi người tìm trên cùng kho đã công bố. Collection chỉ phân loại/filter, không chứa grants theo tài khoản. Sau login, quay lại ảnh đã chọn qua returnTo nội bộ đã kiểm tra.

| Chức năng | visitor | user | admin |
| --- | --- | --- | --- |
| Tìm/lọc, xem danh sách/thumbnail | Có | Có | Có |
| Detail/preview/download | Chuyển login | Có, toàn kho | Có, toàn kho |
| Me, đổi mật khẩu, logout | Không | Có | Có |
| Import/sửa/xóa ảnh, xem/retry jobs | Không | Không | Có |
| Quản trị tài khoản/role/status | Không | Không | Có |

Visitor là trạng thái chưa xác thực, không có users record. users.role chỉ nhận user/admin, mặc định user. Self-signup/SSO/recovery chờ Q12; admin cấp tài khoản là phương án đề xuất hiện tại.

## 2. Cặp token và nơi lưu

| Thành phần | Đề xuất | Sử dụng |
| --- | --- | --- |
| Access token | JWT ký, TTL 15 phút | Frontend giữ trong memory, gửi Authorization: Bearer trên API cần xác thực |
| Refresh token | Opaque random, entropy tối thiểu 256 bit; dùng một lần rồi rotate | Browser giữ cookie HttpOnly; chỉ auth endpoints đọc |
| Refresh family | Một chuỗi token cho mỗi lần login, hạn tuyệt đối đề xuất 7 ngày | Root row trong refresh_tokens giữ chủ sở hữu, auth_version, deadline và trạng thái thu hồi chung |
| Refresh token record | Hash token, user_id, family_id, parent_id, auth_version, expiry/consumed/revoked | Phát hiện reuse và retry/race; không chứa raw token |

Family là khái niệm nhóm token, không là bảng riêng: root có family_id=id, parent_id=null; token mới cùng family_id và parent_id trỏ token trước. Root đã consumed vẫn đại diện nhóm active nếu chưa revoked/hết hạn. Không có auth_sessions hoặc cookie session ID. Refresh registry phục vụ rotation/revocation, không thay access token làm credential cho detail/admin. Thiết kế có kiểm tra trạng thái thu hồi phía server để logout có hiệu lực ngay; không tuyên bố JWT hoàn toàn stateless.

JWT đề xuất RS256, pin thuật toán và public keys theo kid nội bộ. Validate chữ ký, typ access token, iss, aud, sub, iat/nbf/exp, jti, token_use=access, family_id và auth_version. Không lấy thuật toán/URL key tùy ý từ token; không đưa thông tin nhạy cảm vào payload. Tham khảo [RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html).

Protected request phải kiểm tra JWT rồi đọc user active/auth_version và root row của family_id đúng user, chưa revoked/hết hạn trong refresh_tokens; không kiểm tra consumed_at của root cho access JWT; role hiện hành quyết định admin. Nếu registry/DB lỗi thì fail closed, không âm thầm bỏ kiểm tra. Access token hết hạn nhưng refresh còn hợp lệ có thể gọi refresh; refresh token không được dùng như access token.

## 3. Transport cho web

Access token chỉ ở memory, không lưu vào URL/localStorage. Đề xuất refresh cookie `__Secure-refresh`, Secure, HttpOnly, SameSite=Strict, Path=/v1/auth, không Domain. Cookie này chứa refresh token, không phải session ID; server lưu hash. Browser login/refresh nhận access token trong JSON và refresh token qua Set-Cookie; không trả raw refresh token trong JSON của web API.

Auth responses Cache-Control: no-store. Cookie-auth endpoints login/refresh/logout yêu cầu Origin chính xác trong allowlist, Content-Type application/json và custom header `X-Auth-Request: 1`, từ chối origin thiếu/không hợp lệ cho browser contract này. CORS chỉ allowlist origin/header cụ thể với credentials, không wildcard; không chấp nhận form-urlencoded/text/plain cho các endpoints đó. Đây là lớp chống CSRF cho refresh cookie; không có GET /auth/csrf hoặc synchronizer token gắn session.

Protected APIs chỉ nhận access token từ Authorization, không nhận từ cookie/query string, kể cả khi browser còn refresh cookie. Client gửi credentials cho auth endpoints; các header/token không được log. Nếu có native app hoặc SSO sau này, thiết kế transport riêng, không tự thêm đường refresh từ body song song với cookie.

## 4. Login và refresh

Login: validate và rate limit → kiểm tra email/password/user active → transaction khóa user, tạo root refresh_tokens row với family_id=id, token_hash, deadline tuyệt đối và auth_version hiện tại → trả access token và refresh cookie sau commit. Mật khẩu hash Argon2id qua thư viện duy trì, không log/lưu thô; tham khảo [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Sai email/password hoặc disabled trả cùng INVALID_CREDENTIALS.

Refresh: đọc cookie/hash → transaction khóa user, root token rồi token được trình theo thứ tự cố định, không khóa lặp khi token chính là root → xác minh user active/auth_version, root đúng user/family chưa revoked/hết hạn và token được trình chưa consumed/revoked → đánh dấu consumed, thêm token row mới với parent_id và cùng family_id/user_id/auth_version/deadline, tạo access JWT cùng family → commit → Set-Cookie token mới. Token mới không kéo dài deadline tuyệt đối 7 ngày của family. Mỗi lần login tạo family mới; không dùng client-supplied family ID.

Token đã consumed được dùng lại: đặt revoked_at/revoke_reason trên root để thu hồi toàn family, commit rồi trả 401 TOKEN_REUSE_DETECTED và xóa cookie. Hai request refresh đồng thời chỉ có một rotation hợp lệ; request dùng lại token cũ có thể thu hồi cả chuỗi. Frontend cần single-flight refresh và phối hợp giữa tabs; không tự retry mù refresh sau timeout. Nếu response mất sau commit, phương án MVP là login lại, không có grace window nhận token cũ. Rotation/reuse lấy nguyên tắc tham khảo từ [RFC 9700 §4.14](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14); đây là login first-party, không tuyên bố triển khai đầy đủ OAuth server.

Khi API trả ACCESS_TOKEN_EXPIRED, frontend refresh một lần rồi retry request an toàn với Idempotency-Key nếu cần. 401 revoked/invalid/disabled không tạo vòng lặp refresh. Bootstrap sau reload gọi refresh để lấy access token; không có refresh cookie hợp lệ thì về visitor.

## 5. Logout, mật khẩu và role

Logout hiện tại nhận refresh cookie, tra row theo token_hash rồi thu hồi root tương ứng và xóa cookie; frontend xóa access token khỏi memory. Token đã consumed nhưng còn trong registry vẫn xác định được family để logout. Thiếu/không tồn tại refresh token trả 200 idempotent; nếu không thể ghi thu hồi do DB lỗi trả 503, không giả thành server đã revoke. Client vẫn có thể xóa memory và chặn UI local trong lúc retry logout.

Logout-all hoặc đổi mật khẩu tăng users.auth_version và thu hồi mọi root token row; đổi mật khẩu yêu cầu mật khẩu hiện tại. Admin đổi role/status cũng tăng auth_version và revoke mọi root token row trong cùng transaction. Vì protected request kiểm tra version/family, access token đã phát hành bị từ chối ngay ở request sau commit, không đợi đủ 15 phút.

Admin active cuối cùng không được khóa/hạ role; transaction phải chống race. Bootstrap admin riêng, không có default password. Logout/khóa tài khoản vẫn cho phép dùng search/thumbnail dưới vai trò visitor. Các URL media đã cấp trước logout vẫn tuân TTL riêng, không tự bị JWT revoke.

## 6. Snapshot tìm kiếm và media

`search_sessions` chỉ là snapshot phân trang 15 phút, không phải cơ chế login. Owner key là giá trị ngẫu nhiên tối thiểu 128 bit do client giữ trong memory và gửi `X-Search-Owner` khi tạo/đọc snapshot; server chỉ lưu hash, dùng để chống cursor bị dùng nhầm. Không dựa vào auth session hoặc cookie khách; không dùng key để cấp quyền ảnh. Thay access token qua refresh không làm đổi snapshot; login/logout bắt đầu snapshot mới. Client reload mất owner key thì tìm lại.

Search chỉ trả thumbnail, không có original/preview/download URL hoặc object_key. Detail/download cần JWT access hợp lệ và kiểm tra trạng thái catalog; API cấp URL media ký ngắn hạn hoặc stream qua proxy đã xác thực. Signed URL là bearer capability có thể chia sẻ tới hết TTL; Q05 quyết định có cần proxy kiểm tra access token mỗi lượt đọc. Thumbnail có thể được người xem lưu lại.

## 7. Kiểm thử khi triển khai

Login sai/disabled và rate limit; JWT sai signature/alg/kid/iss/aud/type/expiry; refresh token bị gửi như bearer; rotation một lần, reuse và hai-tab race; crash/response loss giữa commit/Set-Cookie; token family expiry; logout không thể refresh tiếp và access bị từ chối; logout-all/password/role/status đổi vô hiệu hóa token cũ; DB lỗi fail closed.

Kiểm tra cookie flags, auth Origin/custom header/CORS, refresh không lộ JSON/logs, access token không lưu bền; visitor search/thumbnail thành công nhưng detail/download 401; user không gọi được admin; admin quản trị ảnh/tài khoản; mọi user dùng cùng toàn kho; snapshot vẫn tách khỏi auth và không có feedback/grants schema.

Ràng buộc schema tối giản: unique token_hash và parent_id khác null; parent/root phải cùng user/family, token chỉ có một successor; mọi rotation/revoke khóa user trước nên không race giữa thêm token và logout. Giữ root và toàn bộ token history đến family deadline cộng access TTL/clock skew để phát hiện reuse và nhận diện logout bằng token cũ. Không ghi đè hash token hiện tại để thay cho lịch sử. Cleanup cả nhóm khi đủ điều kiện, không xóa root sớm. Chi tiết 9 bảng ở [data-model.md](data-model.md).
