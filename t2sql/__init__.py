"""Text-to-SQL: câu hỏi tiếng Việt -> SQL (ClickHouse) -> kết quả + giải thích."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = "2025-06-30"      # ngày cố định của các bộ đánh giá (câu "tháng trước", "gần đây"... được chấm theo ngày này)


def today() -> str:
    """Ngày "hôm nay" đưa vào prompt. Mặc định cố định như TODAY để kết quả đánh giá lặp lại được.
    T2SQL_TODAY=real lấy ngày thật (máy chủ MCP dùng khi phục vụ người dùng), hoặc đặt YYYY-MM-DD cụ thể."""
    v = (os.environ.get("T2SQL_TODAY") or "").strip()
    if v.lower() == "real":
        import datetime
        return datetime.date.today().isoformat()
    return v or TODAY


def load_dotenv(path: str = os.path.join(ROOT, ".env")) -> None:
    """Nạp KEY=VALUE từ .env vào os.environ. Không ghi đè biến đã có; bỏ qua giá trị rỗng."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].strip()
            if key and value and key not in os.environ:
                os.environ[key] = value


load_dotenv()
