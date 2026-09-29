# Text-to-SQL tiếng Việt

Người dùng hỏi bằng tiếng Việt, hệ thống sinh SQL (PostgreSQL hoặc SQLite), chạy trên database và trả kết quả kèm giải thích.
Làm theo lộ trình trong [text_to_sql_lo_trinh.md](text_to_sql_lo_trinh.md): Mức 1 (chạy được), Mức 2 (đáng tin, có ablation), Mức 3 (production).

## Chạy nhanh

```bash
pip install -r requirements.txt
python data/build_db.py                 # tạo data/shop.db (đã có sẵn, chạy lại nếu muốn)
# mở file .env, điền LLM_BASE_URL, LLM_API_KEY, T2SQL_MODEL (model tự host) hoặc ANTHROPIC_API_KEY (Claude)

python cli.py                           # Mức 1: hỏi-đáp trên terminal
python cli.py --config production       # Mức 3: nhiều lượt, hỏi lại, giải thích, phân quyền
streamlit run app.py                    # demo web

python evaluate.py --configs baseline   # baseline accuracy (Mức 1)
python evaluate.py --configs all        # bảng ablation (Mức 2) -> results/report.md
python -m unittest -v                   # 79 test, không gọi API (9 test Postgres tự bỏ qua nếu chưa chạy DB)
python evaluate.py --configs all --oracle   # tự kiểm tra harness chấm điểm, không gọi API
```

## Chạy bằng Docker (PostgreSQL)

```bash
# .env đã có LLM_*, POSTGRES_PASSWORD, T2SQL_APP_PASSWORD (xem .env.example)
docker compose up -d --build            # Postgres + app, mở http://localhost:8501
docker compose ps                       # cả hai service phải "healthy"
docker compose logs -f app

docker compose exec app python evaluate.py --configs all     # chấm điểm trên Postgres -> results/postgres/
docker compose exec app python cli.py --config production    # CLI trong container

# Đo chi phí từng câu SQL (Duration, Read Rows, Memory, CPU Time, Score...) và dựng báo cáo HTML
python profile_queries.py               # chạy trên máy host (cần docker exec vào container db) -> results/postgres/query_metrics.jsonl
python build_report.py                  # -> results/postgres/bao_cao.html

docker compose down                     # dừng, giữ dữ liệu
docker compose down -v                  # dừng và xóa dữ liệu (lần sau nạp lại dữ liệu mẫu)
```

| Service | Nội dung |
|---|---|
| `db` | `postgres:16-alpine`. Lần đầu chạy [docker/postgres/init/](docker/postgres/init/): tạo bảng + `COMMENT` nghiệp vụ, nạp dữ liệu mẫu, tạo role. Cổng chỉ mở cho máy local (`127.0.0.1:5433`) |
| `app` | Streamlit (cổng 8501), chạy bằng user thường, có healthcheck. `logs/` và `results/` được mount ra ngoài |

**Phân quyền ở tầng Postgres** ([03_roles.sh](docker/postgres/init/03_roles.sh)):
- App đăng nhập bằng `t2sql_app` (`NOINHERIT`). Role này không có quyền gì cho tới khi `SET LOCAL ROLE` sang role của vai trò:
  - `t2sql_admin_ro`: đọc mọi bảng.
  - `t2sql_analyst_ro`: đọc mọi bảng, riêng `customers` không được đọc `email`/`phone` (`GRANT` theo cột).
  - `t2sql_sales_ro`: chỉ đọc bảng đơn hàng và sản phẩm.
- Mọi phiên mặc định `READ ONLY`, có `statement_timeout`.
- Mỗi truy vấn do model sinh ra lần lượt qua:
  1. Kiểm tra tĩnh.
  2. Kiểm tra cây cú pháp bằng `sqlglot`: cấm `SELECT INTO`, `FOR UPDATE`, hàm `pg_*`/`set_config`, bảng hệ thống, bảng/cột ngoài quyền. Lớp này để báo lỗi dễ hiểu.
  3. `SET LOCAL ROLE` + transaction `READ ONLY` + timeout. Postgres là lớp thực thi cuối cùng, kể cả khi hai lớp trên bị vượt qua (có test cho trường hợp này).
  4. Server-side cursor, chỉ kéo về tối đa `max_rows + 1` dòng.

**Dùng Postgres có sẵn của công ty:**
1. Sửa tên bảng/cột trong [docker/postgres/roles.sql](docker/postgres/roles.sql) cho khớp schema thật, rồi chạy file đó bằng tài khoản quản trị.
   Nên trỏ vào read replica.
2. Sửa `POLICIES` trong [t2sql/safety.py](t2sql/safety.py) cho khớp với các `GRANT` (bảng/cột được đọc của từng vai trò).
3. Viết mô tả nghiệp vụ trong `data/schema_docs.json`. Có thể thay bằng `COMMENT ON TABLE/COLUMN` trong Postgres,
   vì app tự đọc comment khi JSON không có mô tả.
4. Trong `.env`: đặt `T2SQL_DATABASE_URL_DOCKER=postgresql://t2sql_app:...@host:5432/db` (và `T2SQL_DB_SCHEMA` nếu không phải `public`),
   rồi chạy `docker compose up -d --build app` (không cần service `db`).

Chạy ngoài Docker với Postgres của compose: `T2SQL_DATABASE_URL=postgresql://t2sql_app:...@127.0.0.1:5433/shop`.
Dùng `127.0.0.1`, không dùng `localhost`: trên Windows, `localhost` thử IPv6 trước nên mỗi kết nối chậm thêm 5 giây.
Để trống biến này thì dùng SQLite `data/shop.db`.

**Dialect:** bộ đánh giá và pool few-shot được viết cho SQLite, rồi tự chuyển sang Postgres bằng `sqlglot`.
Câu nào chuyển tự động không đúng thì dùng bản viết tay ở trường `sql_pg`: hiện có 2 câu đánh giá và 2 câu few-shot.
Có test bảo đảm cả 60 câu đánh giá và 30 câu few-shot cho cùng kết quả trên hai DB.
Prompt tự đổi gợi ý cú pháp theo DB đích (`TO_CHAR`/`EXTRACT`/`INTERVAL` cho Postgres, `strftime` cho SQLite).

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
| `T2SQL_DATABASE_URL` | `postgresql://...` hoặc `sqlite:///...`; trống = SQLite `data/shop.db` |
| `T2SQL_DATABASE_URL_DOCKER` | URL DB cho app bên trong Docker; trống = service `db` của compose |
| `T2SQL_DB_SCHEMA`, `T2SQL_QUERY_TIMEOUT` | schema Postgres (`public`), timeout mỗi truy vấn (5 giây) |
| `POSTGRES_PASSWORD`, `T2SQL_APP_PASSWORD` | mật khẩu superuser của Postgres mẫu và của role `t2sql_app` |

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
  SQLite: mode=ro + query_only + authorizer (quyền bảng/cột) + timeout + giới hạn dòng
  Postgres: sqlglot (cú pháp, quyền) + SET LOCAL ROLE (GRANT bảng/cột) + READ ONLY + statement_timeout + server cursor
      │            │
      │            └─ lỗi / rỗng ──► gửi lại (SQL cũ + lỗi) cho LLM, tối đa N=3 lần
      ▼
  che PII ──► giải thích SQL ──► bảng / biểu đồ ──► log + phản hồi 👍/👎
```

| Thành phần | File | Ghi chú |
|---|---|---|
| Database mẫu | [data/build_db.py](data/build_db.py) | 6 bảng, 1446 đơn, sinh cố định theo seed. Có bẫy: cột `name` ở 3 bảng, `status` là mã số, doanh thu chỉ tính `status = 4`, cột PII, một review chứa prompt injection |
| Mô tả nghiệp vụ | [data/schema_docs.json](data/schema_docs.json) | mô tả cột, quy tắc nghiệp vụ, từ khóa và khái niệm cho schema linking |
| Đọc schema | [t2sql/schema.py](t2sql/schema.py) | SQLite: `PRAGMA table_info/foreign_key_list`; Postgres: `pg_catalog` (kiểu, khóa, `COMMENT`); giá trị mẫu bỏ qua cột PII và văn bản tự do |
| Tách SQL | [t2sql/sql_utils.py](t2sql/sql_utils.py) | bỏ markdown, lời giải thích thừa; tách câu lệnh theo `;` ngoài chuỗi/comment |
| Prompt | [t2sql/prompts.py](t2sql/prompts.py) | schema nằm trong system prompt, câu hỏi trong user message |
| Pipeline | [t2sql/pipeline.py](t2sql/pipeline.py) | `Config` bật/tắt từng cải tiến; `CONFIGS` gồm baseline, docs, fewshot, linking, selfcorrect, production |
| Few-shot, linking | [t2sql/retrieval.py](t2sql/retrieval.py) | TF-IDF trên unigram + bigram âm tiết (hợp với tiếng Việt), thuần Python |
| Backend DB | [t2sql/db/](t2sql/db/) | `sqlite.py`, `postgres.py`; chọn theo `T2SQL_DATABASE_URL`. [t2sql/dialect.py](t2sql/dialect.py): chuyển SQL mẫu sang dialect đích, gợi ý cú pháp |
| An toàn, phân quyền | [t2sql/safety.py](t2sql/safety.py), [t2sql/db/postgres.py](t2sql/db/postgres.py) | vai trò `admin`, `analyst` (không được đọc email/phone), `sales` (chỉ bảng đơn hàng/sản phẩm) |
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
- Đo offline bằng `python analyze_shape_checks.py`: 0/60 SQL chuẩn bị báo nhầm; trên khoảng 590 kết quả model đã sinh ở hai lượt trước, 14 lần báo đều đúng câu sai và 0 lần báo nhầm.
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

[eval/dataset.json](eval/dataset.json): 64 câu tiếng Việt, gồm 20 dễ (1 bảng), 22 trung bình (JOIN, GROUP BY, NOT IN), 18 khó
(CTE, window function, nhiều JOIN, tính theo ngày tháng, tăng trưởng, tỉ trọng) và 4 câu phải từ chối
(thời tiết, lợi nhuận khi không có giá vốn, yêu cầu xóa, bảng nhân viên không tồn tại).
Mọi SQL chuẩn đều đã chạy thử, trả kết quả khác rỗng, và không có trường hợp hòa ở các câu top-N.

Pool few-shot ([eval/fewshot_pool.json](eval/fewshot_pool.json), 30 câu) tách riêng khỏi bộ đánh giá.
Có test bảo đảm không trùng câu hỏi, và khi chấm điểm câu đang hỏi luôn bị loại khỏi danh sách ví dụ.

Cách chấm (execution accuracy):
- So **kết quả thực thi**, không so chuỗi SQL.
- Không xét tên cột, cho phép hoán vị cột.
- Sắp xếp dòng trước khi so, trừ các câu có `"ordered": true`.
- Số thực được so với sai số tương đối 1e-4, nên `ROUND` hay thứ tự cộng không làm sai kết quả.
- Cột "EX nới lỏng" chấp nhận kết quả có thêm cột thừa.
- Câu phải từ chối được tính đúng khi hệ thống trả về `cannot` hoặc `refused`.

## Kết quả

Lượt 2 (sau khi làm sạch cú pháp ví dụ few-shot Postgres): 51,7% → 90,0% → 95,0% → 96,7% → 96,7%, gần giống lượt 1 bên dưới.
Lượt này có thêm số đo chi phí từng câu SQL trong `results/postgres/bao_cao.html`.

Lượt 1, chạy ngày 2026-09-29 với model tự host `SDS-AI/softdream` (qua Bifrost), **tắt reasoning**, temperature 0,
trên PostgreSQL, 60 câu có đáp án + 4 câu phải từ chối. Chi tiết từng câu sai: `results/postgres/report.md`.

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

Đã kiểm chứng mà không cần API:
- Chế độ `--oracle` (LLM giả trả SQL chuẩn bọc trong markdown và lời giải thích) đạt 100% ở mọi cấu hình.
  Như vậy khâu tách SQL, lớp an toàn (CTE, window function đều qua authorizer) và bộ chấm điểm hoạt động đúng.
- 79 unit test (9 test trên Postgres thật): an toàn (chặn DROP/DELETE/PRAGMA/ATTACH, nhiều câu lệnh, `sqlite_master`), kết nối chỉ đọc
  ngay cả khi bỏ kiểm tra tĩnh, timeout với CROSS JOIN, giới hạn dòng, quyền bảng/cột (kể cả đọc gián tiếp qua CTE),
  che PII, vòng tự sửa có giới hạn, dừng khi model trả lại cùng SQL rỗng, chặn câu lệnh thứ hai bị chèn mà không thử lại,
  hội thoại nhiều lượt, hỏi lại, log/phản hồi, recall của schema linking, và mọi SQL chuẩn đều chạy được.


## Hạn chế và lưu ý

- **Nguy cơ overfit bộ đánh giá:** từ khóa và bảng khái niệm của schema linking được bổ sung sau khi đo recall trên chính
  bộ đánh giá. Pool few-shot do cùng một người viết nên cùng văn phong với bộ đánh giá. Số trên bộ này có thể cao hơn thực tế;
  nên có thêm một tập kiểm tra do người khác viết.
- Phân nhóm lỗi là heuristic (so bảng, điều kiện `status`, hàm ngày, số JOIN, literal giữa SQL dự đoán và SQL chuẩn),
  dùng để định hướng. Nên đọc lại từng câu sai trong `report.md`.
- Chặn yêu cầu ghi dữ liệu bằng từ khóa (`xóa`, `cập nhật`...) có thể từ chối nhầm câu kiểu "sản phẩm mới cập nhật".
  Lớp chặn thật sự vẫn là SQLite chỉ đọc + authorizer.
- "Sai ngữ nghĩa" (SQL đúng cú pháp nhưng hiểu sai câu hỏi) không phát hiện tự động được. Hệ thống giảm rủi ro bằng cách
  luôn hiển thị SQL, giải thích bằng lời và nhận phản hồi 👍/👎.
- Dữ liệu là dữ liệu tổng hợp, chỉ có 6 bảng. Schema linking mới thực sự có ích trên database lớn hơn.

## Hướng mở rộng

Xem mục "Hướng mở rộng" trong lộ trình: benchmark Spider/BIRD, fine-tune model nhỏ,
đồ thị accuracy / chi phí / độ trễ (`evaluate.py` đã ghi số lời gọi, token và độ trễ cho từng cấu hình).
