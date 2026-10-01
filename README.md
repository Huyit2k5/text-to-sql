# Text-to-SQL tiếng Việt cho ClickHouse

Người dùng hỏi bằng tiếng Việt, hệ thống sinh SQL ClickHouse, chạy trên database và trả kết quả kèm giải thích.
Làm theo lộ trình trong [text_to_sql_lo_trinh.md](text_to_sql_lo_trinh.md): Mức 1 (chạy được), Mức 2 (đáng tin, có ablation), Mức 3 (production).
Chỉ hỗ trợ ClickHouse (các backend SQLite và PostgreSQL đã được gỡ; xem lịch sử git nếu cần).

## Chạy nhanh

```bash
pip install -r requirements.txt
# mở file .env, điền LLM_BASE_URL, LLM_API_KEY, T2SQL_MODEL (model tự host) hoặc ANTHROPIC_API_KEY (Claude),
# T2SQL_DATABASE_URL_CONGTY và T2SQL_DATABASE_URL (ClickHouse của công ty, database hddt; xem .env.example)
python connect_company.py               # kiểm tra kết nối, quyền, giới hạn; --init tạo datasets/<database>/ cho database mới

python cli.py                           # Mức 1: hỏi-đáp trên terminal
python cli.py --config production       # Mức 3: nhiều lượt, hỏi lại, giải thích, phân quyền
streamlit run app.py                    # demo web

python evaluate.py --configs baseline   # baseline accuracy (Mức 1)
python evaluate.py --configs all        # bảng ablation (Mức 2) -> results/clickhouse*/report.md
python -m unittest -v                   # 48 test offline + 37 test chạy trên hddt thật (tests/test_hddt_live.py, chỉ đọc, LLM giả)
python evaluate.py --configs all --oracle   # tự kiểm tra harness chấm điểm, không gọi API
```

## Chạy bằng Docker

```bash
docker compose up -d --build app        # app nối tới ClickHouse công ty (T2SQL_DATABASE_URL_DOCKER hoặc _CONGTY), mở http://localhost:8501
docker compose ps                       # service app phải "healthy"
docker compose logs -f app

docker compose exec app python evaluate.py --configs all     # chấm điểm trên database mặc định
docker compose exec app python cli.py --config production    # CLI trong container

python profile_clickhouse.py            # đo Duration, Read Rows, Memory, CPU từ system.query_log (chạy trên máy host)

docker compose down                     # dừng
```

| Service | Nội dung |
|---|---|
| `app` | Streamlit (cổng 8501), chạy bằng user thường, có healthcheck. `logs/` và `results/` được mount ra ngoài. Ô "Database" trong sidebar chọn giữa các `T2SQL_DATABASE_URL*` |

## ClickHouse

Backend: [t2sql/db/clickhouse.py](t2sql/db/clickhouse.py), driver `clickhouse-connect` (HTTP, cổng 8123).
URL `clickhouse://t2sql:<mật khẩu>@127.0.0.1:8123/<database>`; `clickhouses://` cho HTTPS.
Dùng `127.0.0.1`, không dùng `localhost`: trên Windows, `localhost` thử IPv6 trước nên mỗi kết nối chậm thêm 5 giây.

**An toàn.** ClickHouse không có transaction nên không `ROLLBACK` được; an toàn dựa vào quyền của tài khoản và các lớp kiểm tra phía app:
1. Tài khoản kết nối chỉ có quyền `SELECT`. URL có `?single_user=1` nên mọi vai trò trong app dùng chung một tài khoản; phân quyền theo vai trò (`admin` / `analyst`, che 15 cột cá nhân) do app thực hiện, định nghĩa trong mục `policies` của `schema_docs.json`.
2. Khi tài khoản ở chế độ `readonly=1` (không đổi được setting), backend không gửi setting và đọc kết quả dạng luồng, dừng sau `max_rows` dòng.
3. Nên xin DBA một profile giới hạn phía server (`max_execution_time`, `max_memory_usage`, `max_rows_to_read`); hiện chặn tải chủ yếu ở phía app (`cost_guard` dùng `EXPLAIN ESTIMATE`).
4. Phía app, mỗi câu SQL do model sinh ra lần lượt qua kiểm tra tĩnh (một câu lệnh, chỉ SELECT, cấm từ khóa ghi) rồi kiểm tra cây cú pháp bằng `sqlglot`, chặn thêm:
   - table function (kể cả `numbers()`);
   - bảng `system.*`;
   - mệnh đề `SETTINGS` / `FORMAT`, `INTO OUTFILE`;
   - `sleep*`, `dictGet*`;
   - bảng / cột ngoài quyền của vai trò (để báo lỗi dễ hiểu).
   Có test cho trường hợp tắt hẳn lớp này: ClickHouse vẫn tự chặn.

**Điểm riêng của ClickHouse cần biết:**
- **`LEFT JOIN` không khớp trả `0` / `''` thay vì `NULL`**, trừ khi bật `join_use_nulls=1`. Profile `t2sql_ro` đã bật sẵn.
  Nếu không bật, các câu kiểu "khách chưa có đơn" (`WHERE o.order_id IS NULL`) vẫn chạy nhưng ra sai mà không báo lỗi.
- **Không có khóa ngoại.** Quan hệ giữa các bảng khai báo ở mục `relations` trong `schema_docs.json` của bộ dữ liệu.
  Schema linking cần mục này để kéo thêm bảng trung gian.
- `GROUP BY` phải liệt kê mọi cột không gộp (không có ngoại lệ cho khóa chính).
- Phép chia `/` luôn ra số thực. Top N mỗi nhóm có cú pháp riêng `LIMIT N BY nhom`; prompt đã gợi ý cú pháp này.
- Tiền lưu `Float64`, không dùng `Decimal`: ClickHouse báo lỗi khi trộn `Decimal` với số thực, model sẽ vấp liên tục.
- Mọi SQL mẫu và SQL chuẩn của các bộ dữ liệu viết thẳng bằng ClickHouse (trường `sql`); không còn bước chuyển dialect.

**Dùng ClickHouse thật của công ty:**
1. Xin tài khoản chỉ đọc, nên trỏ vào read replica. `python connect_company.py` kiểm tra kết nối, quyền ghi, giới hạn setting và `query_log`; `--init` tạo `datasets/<db>/schema_docs.json` khởi đầu.
2. Tạo thư mục `datasets/<tên database>/` với `schema_docs.json` (quan hệ, mô tả, quy tắc nghiệp vụ, phân quyền theo vai trò). Nếu JSON không có mô tả, app đọc `COMMENT` của bảng / cột.
3. Đặt `T2SQL_DATABASE_URL` (hoặc `T2SQL_DATABASE_URL_DOCKER` khi chạy trong Docker).
4. Với bảng lớn, chỉnh `max_rows_to_read` / `max_memory_usage` trong profile cho vừa cluster.

## Database thật của công ty: `hddt`

Bộ dữ liệu nằm ở [datasets/hddt/](datasets/hddt/): `schema_docs.json` (mô tả cột, quy tắc nghiệp vụ, phân quyền `admin` / `analyst`),
`eval.json` (66 câu: 63 trả lời được + 3 phải từ chối), `eval_holdout.json` (30 câu), `eval_paraphrase.json` (36 câu diễn đạt lại), `fewshot_pool.json` (17 ví dụ), [huong_dan_demo.md](datasets/hddt/huong_dan_demo.md) và
[cau_hoi_can_xac_nhan.md](datasets/hddt/cau_hoi_can_xac_nhan.md) (những điều cần người hiểu dữ liệu xác nhận).
Database giả lập `einvoice` cũ (mã sinh dữ liệu, bộ đánh giá, container demo) đã bị xóa khỏi mã nguồn; lấy lại từ commit `f446b6a` nếu cần. Các báo cáo cũ vẫn giữ trong [report/](report/) và `results/`.

```bash
python evaluate.py --configs production --workers 2            # chấm điểm trên database mặc định (hddt); đừng chạy quá nhiều luồng trên server dùng chung
python evaluate.py --configs production --dataset datasets/hddt/eval_holdout.json
```

**Thêm một database khác theo cùng cách:** tạo thư mục `datasets/<tên database>/` gồm `schema_docs.json`, `fewshot_pool.json` và `eval.json`.
Pipeline tự nạp thư mục này theo tên database trong URL ([t2sql/datasets.py](t2sql/datasets.py)).
Trong `schema_docs.json` có thể khai báo `sql_dialect`, `policies`, `requires`, `relations`, `no_sample_columns`, `example_questions`.

## Tri thức từ lịch sử truy vấn (system.query_log)

Ý tưởng theo BIRD-History và hệ thống của LinkedIn: câu SQL analyst đã chạy chứa quy ước nghiệp vụ mà schema không có.
Thay vì viết tay từng quy tắc, thống kê chúng từ `system.query_log` rồi đưa vào prompt ([t2sql/history.py](t2sql/history.py)).

```bash
python mine_query_log.py --db-env T2SQL_DATABASE_URL --url-credentials   # đọc system.query_log -> datasets/hddt/query_history.jsonl (không đưa lên git) + in tri thức khai thác được
```

Khai thác được (chỉ giữ quy ước mà >= 60% truy vấn tuân theo và có >= 8 mẫu, nên nhiễu 12% bị bỏ qua):
- bảng nào luôn đọc bằng `FINAL` (485/519 truy vấn với `invoices`);
- điều kiện lọc phổ biến của một cột (trạng thái hợp lệ);
- cột giờ nào thường được bọc `toTimeZone(...)`;
- công thức của một đại lượng (`doanh_thu` = `sum((total_before_tax - total_discount) * exchange_rate)`);
- điều kiện JOIN hay dùng, và vài truy vấn lịch sử liên quan (chỉ lấy câu tuân theo các quy ước trên).

**Kết quả** (2 lượt, reasoning tắt; "khởi đầu lạnh" = không quy tắc nghiệp vụ viết tay, không few-shot):

| Cấu hình | Bộ dev | Bộ held-out |
|---|---|---|
| Khởi đầu lạnh | 56,9% | 65,0% |
| + chỉ thống kê quy ước | 82,8% | 85,0% |
| + chỉ truy vấn lịch sử minh họa | 78,4% | 82,5% |
| **+ cả hai** | **83,6%** | **86,2%** |
| Đủ quy tắc viết tay (tham chiếu) | 91,4% | 91,3% |
| Có few-shot, không quy tắc, không lịch sử | 89,7% | 86,2% |
| Có few-shot, không quy tắc, có lịch sử | 89,7% | 90,0% |

- Trong tình huống khởi đầu lạnh, lịch sử thay được khoảng 3/4 khoảng cách tới bộ quy tắc viết tay (+27 điểm ở dev, +21 ở held-out).
  Phần lớn cải thiện đến từ thống kê quy ước, không phải từ chép câu SQL mẫu.
- Khi đã có few-shot đã duyệt, lịch sử chỉ cải thiện ít (0 điểm ở dev, +3,8 ở held-out, tương đương 1-2 câu): few-shot đã mang sẵn các quy ước.
- Vẫn kém bộ quy tắc viết tay 8 điểm ở dev, 5 điểm ở held-out. Đây là cách để **giảm việc viết tay khi mới triển khai**, không thay hẳn được.
- **Hạn chế quan trọng:** lịch sử ở đây do chính chúng tôi sinh (700 câu, có 12% câu "cẩu thả" và 24 câu lỗi) và cùng người viết bộ đánh giá,
  nên quy ước trong lịch sử khớp với quy ước của bộ đánh giá. Chỉ 1/58 câu dev và 1/40 câu held-out có câu lịch sử cùng cấu trúc (khác hằng số),
  nhưng vẫn cùng loại tác vụ. Thí nghiệm chứng minh cơ chế hoạt động, chưa chứng minh mức cải thiện trên log thật.
  Log thật lộn xộn hơn, nhiều analyst viết khác nhau, và nhiều quy ước không nhất quán.



## Cấu hình (`.env`)

Mọi entrypoint (CLI, `evaluate.py`, Streamlit) tự nạp file `.env` ở thư mục gốc. Mẫu có chú thích nằm ở
[.env.example](.env.example). Biến đã đặt sẵn trong shell được ưu tiên hơn `.env`, còn dòng để trống thì dùng mặc định.
`.env` đã được thêm vào `.gitignore`.

| Biến | Ý nghĩa |
|---|---|
| `T2SQL_PROVIDER` | `openai` = model tự host qua API chuẩn OpenAI (vLLM, Bifrost, Ollama...); `anthropic` = Claude; trống = tự chọn theo tên model |
| `LLM_BASE_URL`, `LLM_API_KEY` | URL (có/không `/v1` đều được) và key của server tự host |
| `T2SQL_MODEL` | tên model, ví dụ `SDS-AI/softdream` hoặc `claude-opus-5-5` |
| `T2SQL_TEMPERATURE`, `T2SQL_MAX_TOKENS` | mặc định 0 và 8192 (gồm cả phần suy nghĩ; vượt context của model thì tự giảm dần) |
| `T2SQL_STREAM` | 1 = streaming (mặc định, hợp với model suy nghĩ lâu), 0 = chờ một phản hồi duy nhất |
| `T2SQL_TIMEOUT`, `T2SQL_MAX_WAIT` | số giây chờ token đầu tiên / giữa hai token (600) và tổng thời gian tối đa một lời gọi (1800) |
| `T2SQL_RETRIES` | số lần thử lại khi timeout/429/5xx (1) |
| `T2SQL_WORKERS` | số câu chạy song song trong `evaluate.py` (4) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `T2SQL_EFFORT`, `T2SQL_FALLBACKS` | chỉ dùng khi provider là `anthropic` |
| `T2SQL_DATABASE_URL` | database mặc định, bắt buộc: `clickhouse://<tiền tố user>:<mật khẩu>@host:8123/<database>`. Các biến `T2SQL_DATABASE_URL_*` khác hiện trong ô chọn Database của app |
| `T2SQL_DATABASE_URL_DOCKER` | URL ClickHouse cho app bên trong Docker; trống = service `clickhouse` của compose |
| `T2SQL_QUERY_TIMEOUT`, `T2SQL_CH_USER_TEMPLATE` | timeout mỗi truy vấn (30 giây); mẫu tên user theo vai trò (`{user}_{role}`) |
| `CLICKHOUSE_PASSWORD`, `T2SQL_CH_PASSWORD` | mật khẩu user quản trị của ClickHouse mẫu và của ba user chỉ đọc `t2sql_*` |

Với model tự host:
- Phần suy nghĩ (`<think>…</think>` hoặc `reasoning_content`) được tự bỏ trước khi tách SQL.
- Web app hiển thị tiến độ "đang suy nghĩ… N token · M giây".
- Có thể tắt "Giải thích SQL bằng lời" ở sidebar để bớt một lần gọi model mỗi câu hỏi.

`evaluate.py` in tiến độ từng câu và ghi kết quả ngay khi mỗi câu xong. Nếu bị dừng giữa chừng, chạy lại cùng lệnh kèm
`--resume` để chỉ chạy các câu còn thiếu hoặc bị lỗi LLM. Với model chậm, nên chạy thử baseline trước:
`python evaluate.py --configs baseline --limit 10`.

Với Claude, tham số tự điều chỉnh theo model:
- `effort` bị bỏ với model không hỗ trợ (Haiku 4.5, Sonnet 4.5...). Mức `xhigh` được hạ xuống `high` trên Opus 4.5/4.6 và Sonnet 4.6.
- `fallbacks` chỉ gửi với các model Claude mới.
- Nếu gateway trả lỗi 400, hệ thống bỏ `effort`/`fallbacks` và gửi lại một lần.

Để so sánh model, chạy cùng bộ đánh giá với model khác. `report.md` ghi rõ model đã dùng:
`$env:T2SQL_MODEL="claude-sonnet-5-5"; python evaluate.py --configs all --out results/sonnet-5-5`.

## Kiến trúc

```
câu hỏi ──► [chặn yêu cầu ghi] ──► [viết lại câu hỏi nối tiếp] ──► [few-shot k ví dụ gần nhất]
                                                                         │
      ┌──────────────────────────────── [schema linking] ◄───────────────┘
      ▼
  prompt = schema (+ mô tả, giá trị mẫu, quy tắc nghiệp vụ) + ví dụ + câu hỏi
      │
      ▼
   LLM (tự host / Claude) ──► SQL | CANNOT_ANSWER | CLARIFY
      │
      ▼
  lớp an toàn: 1 câu lệnh, chỉ SELECT/WITH, cấm từ khóa ghi
      │
      ▼
  ClickHouse: sqlglot (cú pháp, quyền) + user riêng theo vai trò (GRANT bảng/cột, readonly=2) + max_execution_time + max_result_rows
      │            │
      │            └─ lỗi / rỗng ──► gửi lại (SQL cũ + lỗi) cho LLM, tối đa N=3 lần
      ▼
  che PII ──► giải thích SQL ──► bảng / biểu đồ ──► log + phản hồi 👍/👎
```

| Thành phần | File | Ghi chú |
|---|---|---|
| Dữ liệu | ClickHouse công ty, database `hddt` | `VATInvoice` (~14,1 triệu dòng) và `ProductInv` (~16,5 triệu dòng); phải dùng `FINAL` và `is_deleted = 0`, xem [huong_dan_demo.md](datasets/hddt/huong_dan_demo.md) |
| Mô tả nghiệp vụ | [datasets/hddt/schema_docs.json](datasets/hddt/schema_docs.json) | mô tả cột, quy tắc nghiệp vụ, quan hệ, phân quyền theo vai trò, từ khóa và khái niệm cho schema linking |
| Đọc schema | [t2sql/schema.py](t2sql/schema.py), [t2sql/db/clickhouse.py](t2sql/db/clickhouse.py) | `system.tables` / `system.columns` (kiểu, `COMMENT`); quan hệ lấy từ mục `relations` trong `schema_docs.json`; giá trị mẫu bỏ qua cột PII và văn bản tự do |
| Tách SQL | [t2sql/sql_utils.py](t2sql/sql_utils.py) | bỏ markdown, lời giải thích thừa; tách câu lệnh theo `;` ngoài chuỗi/comment |
| Prompt | [t2sql/prompts.py](t2sql/prompts.py) | schema nằm trong system prompt, câu hỏi trong user message |
| Pipeline | [t2sql/pipeline.py](t2sql/pipeline.py) | `Config` bật/tắt từng cải tiến; `CONFIGS` gồm baseline, docs, fewshot, linking, selfcorrect, production |
| Few-shot, linking | [t2sql/retrieval.py](t2sql/retrieval.py) | TF-IDF trên unigram + bigram âm tiết (hợp với tiếng Việt), thuần Python |
| Backend DB | [t2sql/db/](t2sql/db/) | `clickhouse.py` (chọn theo `T2SQL_DATABASE_URL`), `guard.py`: kiểm tra AST bằng sqlglot. [t2sql/dialect.py](t2sql/dialect.py): gợi ý cú pháp ClickHouse cho prompt |
| An toàn, phân quyền | [t2sql/safety.py](t2sql/safety.py), [t2sql/db/guard.py](t2sql/db/guard.py), [t2sql/db/clickhouse.py](t2sql/db/clickhouse.py) | vai trò `admin`, `analyst` (không được đọc email/phone), che 15 cột cá nhân |
| Chấm điểm | [t2sql/evaluation.py](t2sql/evaluation.py), [evaluate.py](evaluate.py) | execution accuracy + phân nhóm lỗi |
| Giao diện | [cli.py](cli.py), [app.py](app.py) | terminal và Streamlit |
| Log | [t2sql/logstore.py](t2sql/logstore.py) | `logs/queries.jsonl`: câu hỏi, SQL, lỗi, độ trễ, phản hồi; câu được 👍 có thể bổ sung vào few-shot |

## Bắt lỗi "chạy được nhưng sai logic"

Vòng tự sửa lỗi chỉ kích hoạt khi SQL lỗi hoặc trả về rỗng. Hai cơ chế dưới đây bắt những câu SQL chạy bình thường nhưng trả lời sai câu hỏi.
Cả hai là tùy chọn trong `Config`.

**Kiểm tra hình dạng kết quả** ([t2sql/checks.py](t2sql/checks.py), `shape_check=True`):
- Đọc dấu hiệu trong câu hỏi rồi so với hình dạng kết quả:
  - R1: "bao nhiêu" (không nhóm) thì phải ra 1 dòng.
  - R2: "mỗi X … nhất" thì cột X không được lặp.
  - R3: gộp theo nhóm thì cột nhóm không được lặp nhiều.
  - R4: "top N" thì tối đa N dòng.
  - R5: "… nào … nhất" thì 1 dòng.
  - R6: phần trăm phải đúng đơn vị, và tỉ trọng các nhóm phải cộng lại khoảng 100.
  - R7: kết quả không được toàn NULL.
- Khi có nghi vấn, hệ thống gửi mô tả cụ thể cho model tự kiểm tra lại. Nếu model giữ nguyên SQL thì chấp nhận.
- Khi kết quả hợp lệ thì không tốn thêm lần gọi model nào.
- Đo offline trên bộ `einvoice` cũ (script đã xóa): 0/60 SQL chuẩn bị báo nhầm; trên khoảng 590 kết quả model đã sinh ở hai lượt trước, 14 lần báo đều đúng câu sai và 0 lần báo nhầm.
- Có test bảo đảm SQL chuẩn không bao giờ bị báo nhầm.

**Self-consistency** (`n_candidates=3`):
- Sinh 1 câu SQL với temperature 0 và 2 câu lấy mẫu với temperature 0,7. Các lần gọi chạy song song.
- Chạy tất cả, gom theo kết quả thực thi, chọn nhóm đông nhất. Phương án lỗi hoặc có nghi vấn hình dạng bị loại khỏi vòng bỏ phiếu.
- `early_stop`: nếu 2 phương án đầu đã khớp thì bỏ phương án thứ 3.
- Mức đồng thuận (ví dụ `3/3`, `2/3`) được lưu trong log và hiển thị trên app làm tín hiệu độ tin cậy.
- Với Claude, tham số temperature bị bỏ qua (các model mới trả lỗi 400), nên các phương án ít đa dạng hơn.

Cấu hình để so sánh: `shapecheck`, `consistency`, `robust` (cả hai), đều dựa trên `selfcorrect`. Cấu hình `production` bật sẵn kiểm tra hình dạng;
app có nút bật self-consistency.

Kết quả (Postgres, reasoning tắt, 2 lượt, `results/robust_r1/`, `results/robust_r2/`):

| Cấu hình | Lượt 1 | Lượt 2 | Câu sai | Lời gọi model / lượt | Độ trễ p50 / p95 |
|---|---|---|---|---|---|
| + Tự sửa lỗi (mốc) | 96,7% | 96,7% | h06, h11 | 65 | 2,3s / 4,0s |
| + Kiểm tra hình dạng | **98,3%** | **98,3%** | h11 | 66 | 2,1s / 4,0s |
| + Self-consistency | 96,7% | 98,3% | h06, h11 (mỗi lượt sai 1 câu khác nhau) | 134 | 3,3s / 7,1s |
| + Hình dạng + Self-consistency | **98,3%** | **98,3%** | h11 | 134 | 3,3s / 7,8s |

- **Kiểm tra hình dạng đáng bật mặc định:** sửa được h06 ở cả hai lượt (quy tắc R2 báo nghi vấn, model sửa lại đúng). Không báo nhầm lần nào, và chỉ tốn thêm khoảng 1,5% số lần gọi model.
- **Self-consistency tốn gấp đôi lần gọi model mà không tăng accuracy ổn định:** ở lượt 2 nó sửa được h11, nhưng ở lượt 1 thì không.
  Nó không sửa được lỗi có hệ thống: ở lượt 2, cả hai phương án đều sai h06 theo cùng một kiểu, nên bỏ phiếu vẫn chọn kết quả sai.
- **Giá trị chính của self-consistency là tín hiệu độ tin cậy:** khi mọi phương án khớp nhau, 99,6% câu đúng (242/243);
  khi các phương án không thống nhất, chỉ 69,2% câu đúng (9/13). Nên dùng làm tùy chọn khi cần cảnh báo người dùng, không bật mặc định.
- Câu h11 (trung bình theo khách nhưng tính lặp 2 khách) vẫn sai, vì kết quả đúng hình dạng (1 dòng) và chỉ lệch khoảng 1%.

## Bộ đánh giá

Bộ dev [eval.json](datasets/hddt/eval.json): 66 câu (63 trả lời được + 3 phải từ chối). Bộ held-out
[eval_holdout.json](datasets/hddt/eval_holdout.json): 30 câu (28 + 2). [eval_paraphrase.json](datasets/hddt/eval_paraphrase.json): 36 câu diễn đạt lại từ 12 câu gốc.
Mọi SQL chuẩn đều đã chạy thử trên `hddt`. Bộ held-out đã được dùng để chỉnh docs ở các vòng trước nên không còn sạch hoàn toàn.

Pool few-shot ([fewshot_pool.json](datasets/hddt/fewshot_pool.json), 17 ví dụ) tách riêng khỏi các bộ đánh giá.
Có test bảo đảm không trùng câu hỏi, và khi chấm điểm câu đang hỏi luôn bị loại khỏi danh sách ví dụ.

Cách chấm (execution accuracy):
- So **kết quả thực thi**, không so chuỗi SQL.
- Không xét tên cột, cho phép hoán vị cột.
- Sắp xếp dòng trước khi so, trừ các câu có `"ordered": true`.
- Số thực được so với sai số tương đối 1e-4, nên `ROUND` hay thứ tự cộng không làm sai kết quả.
- Cột "EX nới lỏng" chấp nhận kết quả có thêm cột thừa.
- Câu phải từ chối được tính đúng khi hệ thống trả về `cannot` hoặc `refused`.

## Kết quả

> Hai bảng đầu tiên (Postgres) và bảng "ClickHouse (1 lượt...)" là kết quả **lịch sử** trên bộ `shop` (đã xóa) và backend PostgreSQL (đã gỡ), giữ lại để tham khảo;
> bản tóm tắt còn trong `results/postgres*` và `results/clickhouse/` (file `.jsonl` thô đã xóa). Phần "Hóa đơn điện tử `einvoice`" bên dưới cũng là kết quả lịch sử (database giả lập đã xóa). Kết quả hiện hành trên `hddt` nằm ở [report/bao_cao_hddt.html](report/bao_cao_hddt.html).

Lượt 2 (sau khi làm sạch cú pháp ví dụ few-shot Postgres): 51,7% → 90,0% → 95,0% → 96,7% → 96,7%, gần giống lượt 1 bên dưới.
Lượt này có thêm số đo chi phí từng câu SQL (báo cáo cũ nằm trong `results/postgres/`).

Lượt 1, chạy ngày 2026-09-29 với model tự host `SDS-AI/softdream` (qua Bifrost), **tắt reasoning**, temperature 0,
trên PostgreSQL (lúc đó), 60 câu có đáp án + 4 câu phải từ chối. Chi tiết từng câu sai: `results/postgres/report.md`.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Token vào | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|
| Baseline (Mức 1) | **50.0%** | 90% | 32% | 28% | 75% | 42k | 2.1s | chỉ tên bảng/cột/kiểu/khóa |
| + Mô tả cột | **88.3%** | 95% | 95% | 72% | 100% | 114k | 7.4s | mô tả, giá trị mẫu, quy tắc nghiệp vụ |
| + Few-shot | **96.7%** | 100% | 100% | 89% | 100% | 136k | 3.4s | 4 ví dụ gần nhất |
| + Schema linking | **95.0%** | 100% | 100% | 83% | 100% | 98k | 2.9s | bớt 28% token so với dòng trên |
| + Tự sửa lỗi | **96.7%** | 100% | 100% | 89% | 100% | 98k | 3.5s | vòng sửa không được kích hoạt lần nào |

Đọc bảng:
- **Mô tả nghiệp vụ là cải tiến lớn nhất (+38 điểm).** Ở baseline, 14/31 câu sai do hiểu sai nghiệp vụ
  (không biết doanh thu chỉ tính `status = 4` và phải trừ `discount`), 7 câu chọn sai bảng.
- **Few-shot thêm +8 điểm**, chủ yếu ở câu khó (72% → 89%).
- **Chênh lệch ±1.7 điểm ở hai dòng cuối là nhiễu, không phải tác dụng thật.** Đó chỉ là 1 câu (h10) mà model sinh
  lúc đúng lúc sai giữa hai lần chạy, dù temperature = 0 (vLLM gộp nhiều request xử lý cùng lúc nên kết quả không hoàn toàn cố định).
  Vòng tự sửa không chạy lần nào (0 câu có lượt sửa), vì ở lần chạy đó không câu nào lỗi hay rỗng.
  Tác dụng thật của schema linking là **bớt 28% token và giảm độ trễ**, accuracy giữ nguyên.
- Còn 2 câu sai ở cấu hình cuối, đều là lỗi suy luận thật của model:
  - h06 "sản phẩm doanh thu cao nhất trong mỗi danh mục": model liệt kê mọi sản phẩm, không lọc top 1 mỗi nhóm.
  - h11 "số ngày từ lúc đăng ký đến đơn đầu tiên": model coi `order_id` nhỏ nhất là đơn đầu tiên, thay vì ngày đặt sớm nhất.
- **Phát hiện phụ:** ví dụ few-shot được chuyển tự động sang Postgres có cú pháp rườm rà
  (`TO_CHAR(CAST(x AS TIMESTAMP), 'MM')`, `/ NULLIF(3, 0)`, `NULLS LAST`), và model bắt chước kiểu viết này.
  Câu h10 lỗi cú pháp ở lần chạy linking chính là do chép sai mẫu đó. Nên làm sạch cách chuyển hoặc viết tay ví dụ Postgres.
- Các con số này có thể cao hơn thực tế (xem "Hạn chế": nguy cơ overfit bộ đánh giá).

### ClickHouse (1 lượt, reasoning tắt, cùng model)

| Cấu hình | ClickHouse | Postgres (lượt 1 / 2) | Lời gọi LLM (ClickHouse) |
|---|---|---|---|
| Baseline | 51,7% | 50,0 / 51,7% | 64 |
| + Mô tả cột | 90,0% | 88,3 / 90,0% | 64 |
| + Few-shot | 91,7% | 96,7 / 95,0% | 64 |
| + Schema linking | 95,0% | 95,0 / 96,7% | 64 |
| + Tự sửa lỗi | 98,3% | 96,7 / 96,7% | 64 |
| + Kiểm tra hình dạng | 98,3% | 98,3 / 98,3% | 64 |
| + Hình dạng + Self-consistency | 98,3% | 98,3 / 98,3% | 133 |

- Nhìn chung ngang Postgres. Dòng few-shot thấp hơn Postgres 3–5 điểm. Từ dòng linking trở đi thì ngang hoặc cao hơn.
  ClickHouse mới chạy 1 lượt, nên chênh lệch vài điểm giữa các dòng chưa chắc có ý nghĩa: dòng "tự sửa lỗi" không có lần sửa nào
  mà vẫn cao hơn dòng linking 3,3 điểm, tức là do dao động giữa các lần chạy.
- Câu sai duy nhất ở 3 cấu hình cuối là m07 "doanh thu theo từng tháng năm 2025": model trả số tháng `1..6`, còn SQL chuẩn trả `'2025-01'`.
  Hai kết quả mang cùng nội dung; bộ chấm nghiêm nên tính là sai.
- Hiệu năng (`profile_clickhouse.py`, 448 lượt chạy, 257 câu SQL khác nhau): trung vị 2,8 ms, chậm nhất 8,1 ms, đọc khoảng 1.600 dòng
  và dùng khoảng 4 MiB bộ nhớ mỗi câu. Không câu nào bị đánh dấu "Chậm". Với dữ liệu nhỏ, ClickHouse chậm hơn Postgres (1,3 ms)
  vì chi phí cố định mỗi truy vấn; lợi thế của ClickHouse chỉ thấy rõ trên bảng hàng triệu dòng trở lên.

### Hóa đơn điện tử `einvoice` (ClickHouse, ~100 triệu dòng, 2 lượt, reasoning tắt)

| Cấu hình | Lượt 1 | Lượt 2 | Dễ / TB / Khó (lượt 2) | Lời gọi LLM |
|---|---|---|---|---|
| Baseline | 36,2% | 36,2% | 56 / 41 / 15% | 62 |
| + Mô tả cột + quy tắc nghiệp vụ | 75,9% | 79,3% | 94 / 86 / 60% | 62 |
| + Few-shot | 86,2% | 87,9% | 100 / 100 / 65% | 62 |
| + Schema linking | 87,9% | 87,9% | 100 / 100 / 65% | 62 |
| + Tự sửa lỗi | 89,7% | 89,7% | 100 / 100 / 70% | 66 |
| + Kiểm tra hình dạng | 86,2% | 91,4% | 100 / 100 / 75% | 67 |

- **Tài liệu nghiệp vụ là đòn bẩy lớn:** thêm mô tả cột và quy tắc nghiệp vụ tăng +40 đến +43 điểm.
  Ở baseline, 24 câu đọc `invoices` không có `FINAL`, và 9 câu lọc log UTC mà không đổi múi giờ.
  Khi đã có quy tắc trong prompt, model gần như luôn dùng `FINAL`, `toTimeZone` và `exchange_rate` đúng chỗ.
- **Few-shot tăng thêm +9 đến +10 điểm**, chủ yếu ở câu khó. Schema linking gần như không đổi accuracy nhưng bớt khoảng 43% token vào.
- **Lượt 1 dòng "kiểm tra hình dạng" thấp hơn dòng "tự sửa lỗi"** là do dao động giữa hai lần chạy, không phải do quy tắc kiểm tra:
  - h15 lúc đúng lúc sai vì có thêm cột thừa (EX nới lỏng vẫn tính đúng).
  - m11 có một lần model trả `SELECT count() AS ...` **không có `FROM`**. ClickHouse vẫn chạy câu này (đọc `system.one`) và trả về 1, tức là sai mà không báo lỗi.
    Sau lần đó đã thêm quy tắc R0: SQL không đọc bảng nào thì bị trả lại cho model sửa.
  - Lượt 2 chạy sau khi sửa R0 và làm rõ câu h11.
- **5 câu vẫn sai ở lượt 2**, đều là lỗi nghiệp vụ hoặc logic, không phải lỗi cú pháp:
  - h04: dùng bảng tổng hợp nhưng nhóm theo ngày thay vì tháng. Kiểm tra hình dạng có phát hiện (R3), nhưng model không sửa được.
  - h10: lồng hàm gộp trong hàm gộp, và tự sửa lỗi không gỡ được.
  - h12: tìm "hóa đơn lớn nhất" nhưng lại cộng tổng theo doanh nghiệp.
  - h16: model tự đoán mã tỉnh Đà Nẵng là `78` (đúng là `48`) thay vì JOIN `provinces` theo tên.
  - h17: ước lượng phần thuế được giảm bằng 25% tổng thuế, thay vì chỉ tính trên các dòng 8%.
- **Hiệu năng** (`profile_clickhouse.py`, đọc `system.query_log`):
  - SQL chuẩn: trung vị 71 ms, chậm nhất 2,3 giây, đọc tối đa 39 triệu dòng.
  - SQL của cấu hình cuối: trung vị 90 ms.
  - Có 5 câu đúng kết quả nhưng tốn hơn SQL chuẩn từ 3 đến 17 lần. Ví dụ h11 mất 3,3 giây so với 0,19 giây; m11 đọc 58 triệu dòng so với 17 triệu dòng
    vì đếm lại từ `invoice_items` thay vì dùng cột `item_count`.
    Trên cluster thật, nên chặn loại truy vấn này bằng `EXPLAIN ESTIMATE` trước khi chạy.

Đã kiểm chứng mà không cần API:
- Chế độ `--oracle` (LLM giả trả SQL chuẩn bọc trong markdown và lời giải thích) đạt 100% ở mọi cấu hình.
  Như vậy khâu tách SQL, lớp an toàn (CTE, window function đều qua kiểm tra cú pháp) và bộ chấm điểm hoạt động đúng.
- 47 unit test chạy offline (không cần database): an toàn (chặn DROP / DELETE / ATTACH, nhiều câu lệnh, bảng `system.*`, table function `url()` / `file()`), kết nối chỉ đọc ngay cả khi bỏ kiểm tra cú pháp phía app, timeout với CROSS JOIN, giới hạn dòng, quyền bảng / cột (kể cả đọc gián tiếp qua CTE), che PII, vòng tự sửa có giới hạn, dừng khi model trả lại cùng SQL rỗng, chặn câu lệnh thứ hai bị chèn mà không thử lại, hội thoại nhiều lượt, hỏi lại, log / phản hồi, recall của schema linking (100% trên cả hai bộ đánh giá), và SQL chuẩn không bị kiểm tra hình dạng báo nhầm.


## Hạn chế và lưu ý

- **Nguy cơ overfit bộ đánh giá:** từ khóa và bảng khái niệm của schema linking được bổ sung sau khi đo recall trên chính
  bộ đánh giá. Pool few-shot do cùng một người viết nên cùng văn phong với bộ đánh giá. Số trên bộ này có thể cao hơn thực tế;
  nên có thêm một tập kiểm tra do người khác viết.
- Phân nhóm lỗi là heuristic (so bảng, điều kiện `status`, hàm ngày, số JOIN, literal giữa SQL dự đoán và SQL chuẩn),
  dùng để định hướng. Nên đọc lại từng câu sai trong `report.md`.
- Chặn yêu cầu ghi dữ liệu bằng từ khóa (`xóa`, `cập nhật`...) có thể từ chối nhầm câu kiểu "sản phẩm mới cập nhật".
  Lớp chặn thật sự vẫn là quyền chỉ đọc của user ClickHouse.
- "Sai ngữ nghĩa" (SQL đúng cú pháp nhưng hiểu sai câu hỏi) không phát hiện tự động được. Hệ thống giảm rủi ro bằng cách
  luôn hiển thị SQL, giải thích bằng lời và nhận phản hồi 👍/👎.
- Dữ liệu là dữ liệu tổng hợp, 15 bảng. Schema linking mới thực sự có ích trên database có hàng trăm bảng.

## Hướng mở rộng

Xem mục "Hướng mở rộng" trong lộ trình: benchmark Spider/BIRD, fine-tune model nhỏ,
đồ thị accuracy / chi phí / độ trễ (`evaluate.py` đã ghi số lời gọi, token và độ trễ cho từng cấu hình).
