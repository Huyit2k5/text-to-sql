# Text-to-SQL tiếng Việt cho hóa đơn điện tử

Hỏi dữ liệu hóa đơn bằng tiếng Việt, nhận lại **câu SQL ClickHouse, kết quả và lời giải thích**.
Hệ thống chạy trên database `hddt` của công ty (~14 triệu hóa đơn, ~16,5 triệu dòng hàng hóa), dùng model tự host
`SDS-AI/softdream`, và chỉ có quyền đọc.

> **Trạng thái:** sẵn sàng thí điểm nội bộ. Chưa có đăng nhập, xem [Triển khai](#triển-khai) và [Hạn chế đã biết](#hạn-chế-đã-biết).

---

## Điểm nổi bật

| | |
|---|---|
| **Hiểu nghiệp vụ hóa đơn** | Tài liệu nghiệp vụ nằm trong [schema_docs.json](datasets/hddt/schema_docs.json): `FINAL` và `is_deleted`, nghĩa các mã `Status` / `Type` / `VATRate`, quan hệ hóa đơn – dòng hàng, khái niệm "hóa đơn đã phát hành" |
| **Chỉ đọc, nhiều lớp bảo vệ** | Tài khoản chỉ có `SELECT`; kiểm tra tĩnh, kiểm tra cây cú pháp (sqlglot), phân quyền bảng và cột theo vai trò, che thông tin cá nhân, chặn truy vấn nặng trước khi chạy |
| **Tự sửa và tự soát** | Sửa SQL lỗi hoặc kết quả rỗng (tối đa 3 lần), kiểm tra hình dạng kết quả, hỏi lại khi câu mơ hồ, từ chối khi không có dữ liệu |
| **Nhanh** | Trung vị 3,9 giây mỗi câu hỏi; truy vấn ClickHouse trung vị 59 ms |
| **Đo được** | Bộ đánh giá 3 tầng (dev, held-out, diễn đạt lại), chấm theo kết quả thực thi, đo thời gian và tài nguyên từ `system.query_log` |
| **Giao diện sẵn** | Web (Streamlit) và terminal; hội thoại nhiều lượt, biểu đồ tự chọn, nút 👍/👎 ghi vào log |

## Kết quả hiện tại

Model `SDS-AI/softdream` (tắt reasoning), cấu hình `production`, chấm theo execution accuracy trên database thật.

| Bộ câu hỏi | Số câu | Đúng | Ghi chú |
|---|---|---|---|
| Dev | 63 + 3 phải từ chối | **60 / 63 (95,2%)** | từ chối đúng 3/3 |
| Held-out | 28 + 2 phải từ chối | **26 / 28 (92,9%)** | từ chối đúng 2/2 |
| Diễn đạt lại | 36 (từ 12 câu gốc) | **36 / 36** | cùng ý, đổi cách hỏi |
| Câu về nghĩa mã mới (`Status`, `Type`) | 10 | **9 / 10** | trước khi bổ sung nghĩa: 4 / 10 |

| Chỉ số | Giá trị |
|---|---|
| Thời gian một câu hỏi (cả pipeline) | trung vị **3,9 s**, p90 8,2 s |
| Truy vấn trên ClickHouse | trung vị 59 ms, p90 113 ms, p99 781 ms, lâu nhất 896 ms |
| Tài nguyên lớn nhất một truy vấn | đọc 13,5 triệu dòng, 82 MB bộ nhớ |
| SQL do model sinh so với SQL chuẩn | trung vị 1,00 lần thời gian, tối đa 1,51 lần |

> Các số trên đo trên bộ câu **do nhóm viết**, nên có thể cao hơn thực tế; bộ held-out cũng đã được dùng để chỉnh tài liệu ở các vòng trước.
> Con số đáng tin nhất sẽ là kết quả trên bộ câu thật do chuyên gia nghiệp vụ viết. Chi tiết: [báo cáo hddt](report/bao_cao_hddt.html).

## Cách hoạt động

```
câu hỏi ─► chặn yêu cầu ghi ─► viết lại câu nối tiếp ─► chọn bảng liên quan + ví dụ gần nhất
                                                                  │
            prompt = schema + mô tả + giá trị mẫu + quy tắc nghiệp vụ + ví dụ + câu hỏi
                                                                  ▼
                                      LLM ─► SQL │ CANNOT_ANSWER │ CLARIFY
                                                                  ▼
   kiểm tra tĩnh ─► kiểm tra cú pháp + quyền (sqlglot) ─► ước lượng chi phí (EXPLAIN ESTIMATE)
                                                                  ▼
                                                            ClickHouse
                                          lỗi / rỗng / kết quả đáng ngờ ──► gửi lại cho LLM (tối đa 3 lần)
                                                                  ▼
                                    che dữ liệu cá nhân ─► bảng / biểu đồ ─► log + phản hồi 👍/👎
```

| Thành phần | Mã nguồn | Vai trò |
|---|---|---|
| Pipeline | [t2sql/pipeline.py](t2sql/pipeline.py) | điều phối; mỗi cải tiến bật/tắt bằng `Config` (`baseline` … `production`) |
| Schema và tài liệu | [t2sql/schema.py](t2sql/schema.py), [datasets/hddt/](datasets/hddt/) | đọc cấu trúc bảng, ghép mô tả, giá trị mẫu, quy tắc nghiệp vụ |
| Tìm bảng và ví dụ | [t2sql/retrieval.py](t2sql/retrieval.py) | TF-IDF trên âm tiết tiếng Việt, thuần Python |
| Backend ClickHouse | [t2sql/db/clickhouse.py](t2sql/db/clickhouse.py) | kết nối chỉ đọc, giới hạn dòng và thời gian, lưu đệm schema |
| An toàn | [t2sql/safety.py](t2sql/safety.py), [t2sql/db/guard.py](t2sql/db/guard.py) | kiểm tra tĩnh, kiểm tra cây cú pháp, phân quyền, che PII |
| Kiểm tra kết quả | [t2sql/checks.py](t2sql/checks.py) | phát hiện SQL chạy được nhưng sai hình dạng kết quả |
| Model | [t2sql/llm.py](t2sql/llm.py) | model tự host (API chuẩn OpenAI) hoặc Claude |
| Chấm điểm | [t2sql/evaluation.py](t2sql/evaluation.py), [evaluate.py](evaluate.py) | so kết quả thực thi, phân nhóm lỗi |
| Giao diện | [app.py](app.py), [cli.py](cli.py) | Streamlit và terminal |

## Bắt đầu nhanh

**Yêu cầu:** Python 3.12+, một model tương thích API OpenAI (hoặc khóa Anthropic), tài khoản **chỉ đọc** vào ClickHouse.

```bash
pip install -r requirements.txt
cp .env.example .env          # điền LLM_BASE_URL, LLM_API_KEY, T2SQL_MODEL và T2SQL_DATABASE_URL

python connect_company.py     # kiểm tra kết nối, quyền ghi, giới hạn setting, EXPLAIN ESTIMATE, query_log
streamlit run app.py          # giao diện web tại http://localhost:8501
python cli.py --config production --role analyst      # hoặc dùng terminal
```

URL database có dạng `clickhouse://<tài khoản>:<mật khẩu>@<máy chủ>:8123/hddt?single_user=1`
(`clickhouses://` cho HTTPS; `single_user=1` cho mọi vai trò dùng chung một tài khoản, phân quyền do ứng dụng thực hiện).
File `.env` đã nằm trong `.gitignore`; **không đưa mật khẩu hay địa chỉ máy chủ vào mã nguồn hay báo cáo.**

### Chạy bằng Docker

```bash
docker compose up -d --build app          # mở http://localhost:8501
docker compose exec app python evaluate.py --configs production --workers 2
```

## Bảo mật và phân quyền

Hệ thống giả định model có thể sinh SQL sai hoặc bị dẫn dụ, nên không dựa vào một lớp duy nhất.

| Lớp | Biện pháp |
|---|---|
| 1. Tài khoản | Chỉ có `SELECT`. `connect_company.py` kiểm tra không ghi được |
| 2. Kiểm tra tĩnh | Đúng một câu lệnh, chỉ `SELECT` / `WITH`, cấm `INSERT`, `DROP`, `ALTER`, `ATTACH`… |
| 3. Kiểm tra cây cú pháp | Chặn table function (`url()`, `file()`, `remote()`, `numbers()`), bảng `system.*`, `SETTINGS`, `FORMAT`, `INTO OUTFILE`, `sleep*` |
| 4. Phân quyền theo vai trò | `admin`: hai bảng `VATInvoice`, `ProductInv`. `analyst`: không đọc được 15 cột cá nhân (tên, địa chỉ, điện thoại, email, ghi chú…) |
| 5. Che dữ liệu | Vai trò `analyst` thấy dữ liệu đã che (`***@…`) |
| 6. Giới hạn tài nguyên | `max_execution_time`, `max_result_rows`; chặn mềm truy vấn dự kiến đọc quá 5 triệu dòng |
| 7. Truy vết | Mọi truy vấn có `log_comment` trong `system.query_log`, kèm log ứng dụng |

> **Lưu ý quan trọng.** Tài khoản đang dùng chung nên phân quyền **cột** hiện chỉ do ứng dụng bảo đảm; database không tự chặn
> (có test ghi lại thực tế này). Muốn có bảo đảm ở tầng database, cần DBA cấp tài khoản riêng theo vai trò với quyền `SELECT` theo cột
> và profile giới hạn tài nguyên phía server.

## Cấu hình

Mọi biến nằm trong `.env` (mẫu có chú thích: [.env.example](.env.example)). Biến đặt sẵn trong shell được ưu tiên hơn `.env`.

| Biến | Ý nghĩa |
|---|---|
| `T2SQL_DATABASE_URL` | database mặc định (bắt buộc). Thêm `T2SQL_DATABASE_URL_<TÊN>` để hiện thêm database trong ô chọn |
| `LLM_BASE_URL`, `LLM_API_KEY`, `T2SQL_MODEL` | model tự host qua API chuẩn OpenAI (vLLM, Bifrost, Ollama…) |
| `ANTHROPIC_API_KEY` | dùng Claude thay cho model tự host (`T2SQL_PROVIDER=anthropic`) |
| `T2SQL_QUERY_TIMEOUT` | giới hạn thời gian mỗi truy vấn do model sinh (mặc định 30 giây) |
| `T2SQL_MAX_ESTIMATED_ROWS` | ghi đè ngưỡng chặn truy vấn nặng (mặc định lấy từ `cost_guard_rows` của bộ dữ liệu) |
| `T2SQL_SCHEMA_CACHE_HOURS` | thời gian lưu đệm schema trong `.cache/` (mặc định 24, `0` để tắt) |
| `T2SQL_WORKERS` | số câu chạy song song khi đánh giá |

Danh sách đầy đủ, các tham số theo provider và cách chọn model: [docs/thuc_nghiem_lich_su.md](docs/thuc_nghiem_lich_su.md#cấu-hình-env).

## Thêm một database khác

1. `python connect_company.py --init` tạo `datasets/<tên database>/schema_docs.json` khởi đầu từ cấu trúc bảng.
2. Điền mô tả cột, quy tắc nghiệp vụ, quan hệ giữa bảng (`relations`), phân quyền (`policies`), từ khóa tìm bảng.
3. Thêm `fewshot_pool.json` (ví dụ đã duyệt) và `eval.json` (câu hỏi kèm SQL chuẩn).
4. Đặt `T2SQL_DATABASE_URL` trỏ tới database đó; pipeline tự nạp thư mục theo tên database ([t2sql/datasets.py](t2sql/datasets.py)).

Có thể khai thác quy ước nghiệp vụ từ lịch sử truy vấn thật của analyst: `python mine_query_log.py --db-env T2SQL_DATABASE_URL --url-credentials`.

## Đánh giá và đo hiệu năng

```bash
python evaluate.py --configs production --workers 2                                   # bộ dev
python evaluate.py --configs production --dataset datasets/hddt/eval_holdout.json     # bộ held-out
python profile_clickhouse.py --db-env T2SQL_DATABASE_URL --url-credentials             # thời gian, dòng đọc, bộ nhớ từ system.query_log
```

- **Chấm theo kết quả thực thi**, không so chuỗi SQL; bỏ qua tên cột và thứ tự cột; số thực so với sai số tương đối 1e-4.
  Chế độ "nới lỏng" chấp nhận cột thừa và nhiều cách viết cùng một tháng (`2025-03`, `2025-03-01`, `3`).
- Câu phải từ chối được tính đúng khi hệ thống trả về `cannot` hoặc `refused`.
- Few-shot tách riêng khỏi các bộ đánh giá; câu đang hỏi luôn bị loại khỏi danh sách ví dụ.
- Đừng chạy quá nhiều luồng trên server dùng chung (`--workers 2`).

## Kiểm thử

```bash
python -m unittest                         # 48 test offline + 37 test chạy trên hddt thật
T2SQL_TEST_SLOW=1 python -m unittest       # thêm test chạy toàn bộ SQL chuẩn và few-shot (~35 giây)
```

- [tests/test_t2sql.py](tests/test_t2sql.py): logic offline (tách SQL, an toàn, chấm điểm, kiểm tra hình dạng, self-consistency, lưu đệm).
- [tests/test_hddt_live.py](tests/test_hddt_live.py): chạy trên `hddt` thật, chỉ đọc, LLM giả. Tự bỏ qua nếu không có `T2SQL_DATABASE_URL`.

## Cấu trúc thư mục

```
app.py, cli.py              giao diện web và terminal
evaluate.py                 chấm điểm theo cấu hình
profile_clickhouse.py       đo hiệu năng từ system.query_log
connect_company.py          kiểm tra kết nối và tạo bộ dữ liệu khởi đầu
mine_query_log.py           khai thác quy ước từ lịch sử truy vấn
t2sql/                      lõi: pipeline, schema, retrieval, an toàn, backend ClickHouse
datasets/hddt/              tài liệu nghiệp vụ, bộ đánh giá, few-shot, phiếu xác nhận nghĩa
report/                     báo cáo HTML
docs/                       nhật ký thực nghiệm chi tiết
tests/                      kiểm thử
```

## Triển khai

- **Docker:** `docker compose up -d --build app`. Ứng dụng phải chạy ở nơi nhìn thấy cả ClickHouse và model.
- **Mở cho người khác thử:** đặt sau HTTPS và **có xác thực** (reverse proxy có đăng nhập, Cloudflare Access, hoặc `ngrok --basic-auth`).
  Ứng dụng hiện **chưa có đăng nhập**; ai vào được địa chỉ đều tự chọn được vai trò `admin`.
- **Trước khi mở rộng người dùng:** thêm đăng nhập và gắn vai trò theo người, ghi tên người dùng vào log, giới hạn số câu chạy đồng thời
  (model tự host có thể chậm khi tải cao), xin DBA tài khoản riêng có giới hạn tài nguyên phía server.

## Hạn chế đã biết

- **Chưa kiểm chứng trên câu hỏi thật.** Bộ đánh giá do nhóm viết; cần bộ câu và SQL do chuyên gia nghiệp vụ duyệt.
- **Một số nghĩa dữ liệu chưa được xác nhận:** `Status` = −1, 6, 1; định nghĩa "doanh thu"; "hóa đơn" mặc định có tính hóa đơn nháp hay không.
  Danh sách cần xác nhận: [cau_hoi_can_xac_nhan.md](datasets/hddt/cau_hoi_can_xac_nhan.md).
- **Câu mơ hồ** vẫn dao động giữa các lần chạy (ví dụ h08, h20, h24).
- **Lỗi còn lại đã biết:** o12, o14 (quy tắc `Feature = 1` áp dụng quá tay), u03 (hỏi lại thay vì từ chối).
- **"Sai ngữ nghĩa"** (SQL đúng cú pháp nhưng hiểu sai ý) không phát hiện tự động được. Hệ thống giảm rủi ro bằng cách luôn hiển thị SQL,
  giải thích bằng lời (bật trên giao diện) và nhận phản hồi 👍/👎. **Nên đối chiếu số liệu với báo cáo công ty** trong giai đoạn đầu.
- Chặn yêu cầu ghi bằng từ khóa có thể từ chối nhầm câu kiểu "sản phẩm mới cập nhật"; lớp chặn thật sự vẫn là quyền chỉ đọc của tài khoản.

## Lộ trình

1. Cập nhật tài liệu nghiệp vụ theo nghĩa dữ liệu đã được xác nhận; đo lại trên bộ câu thật của chuyên gia.
2. Đối soát số liệu với báo cáo hiện có của công ty.
3. Đăng nhập, phân quyền theo người, tài khoản database riêng có giới hạn.
4. Thí điểm với nhóm nhỏ, thu phản hồi 👍/👎 và đưa câu đã duyệt vào few-shot (vòng phản hồi).
5. Khai thác `query_log` công ty để bổ sung quy ước; cân nhắc model nhỏ hơn khi đã có đủ cặp câu hỏi – SQL đã duyệt.

Lộ trình chi tiết theo mức: [text_to_sql_lo_trinh.md](text_to_sql_lo_trinh.md).

## Tài liệu liên quan

| Tài liệu | Nội dung |
|---|---|
| [report/bao_cao_hddt.html](report/bao_cao_hddt.html) | báo cáo kết quả trên `hddt`: độ chính xác, hiệu năng, khái niệm đã xác nhận, hướng thực nghiệm |
| [datasets/hddt/huong_dan_demo.md](datasets/hddt/huong_dan_demo.md) | hướng dẫn demo và câu hỏi mẫu |
| [datasets/hddt/cau_hoi_can_xac_nhan.md](datasets/hddt/cau_hoi_can_xac_nhan.md) | phiếu xác nhận nghĩa dữ liệu cho người nghiệp vụ |
| [docs/thuc_nghiem_lich_su.md](docs/thuc_nghiem_lich_su.md) | cấu hình đầy đủ, kiến trúc chi tiết, các thí nghiệm ablation và tri thức từ `query_log` |
| [report/](report/) | các báo cáo HTML cũ (`einvoice`, so sánh phương pháp) |
