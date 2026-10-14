"""Xác thực và giới hạn tải cho máy chủ MCP (ask_data).

Kho token (ngoài git): mỗi người một token ngẫu nhiên, chỉ lưu bản băm SHA-256, nhãn, ngày tạo, hạn dùng.
Server đọc lại kho theo thời gian sửa file nên thu hồi có hiệu lực ngay, không cần khởi động lại.
Giới hạn tải: tối đa N câu chạy đồng thời toàn server, M câu cho mỗi người, và K lệnh mỗi phút cho mỗi người.
Hết chỗ thì từ chối ngay (không xếp hàng) để không vượt hạn chót của client.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.Lock()
_LABEL_RE = re.compile(r"^[A-Za-z0-9._@ -]{1,60}$")      # chỉ ASCII: nhãn đi qua header HTTP
_cache = {"key": None, "data": None}


def tokens_path() -> str:
    return os.environ.get("T2SQL_MCP_TOKENS_FILE") or os.path.join(ROOT, ".cache", "mcp_tokens.json")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load() -> dict:
    """Đọc kho token; chỉ đọc lại khi file đổi (so theo mtime và kích thước), nên thu hồi có hiệu lực ngay."""
    path = tokens_path()
    try:
        st = os.stat(path)
    except OSError:
        _cache.update(key=None, data={"tokens": {}})
        return _cache["data"]
    key = (path, st.st_mtime_ns, st.st_size)
    if _cache["key"] != key:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data.setdefault("tokens", {})
        _cache.update(key=key, data=data)
    return _cache["data"]


def _save(data: dict):
    path = tokens_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)           # ghi atomic: CLI và server cùng đụng vào file
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    _cache["key"] = None


def create_token(label: str, days: float = 30) -> str:
    """Tạo token mới cho một người (nhãn duy nhất). Token chỉ trả về một lần."""
    label = (label or "").strip()
    if not _LABEL_RE.match(label):
        raise ValueError("Nhãn gồm 1 đến 60 ký tự: chữ cái và số không dấu, dấu cách, . _ @ -")
    token = secrets.token_urlsafe(32)
    with _lock:
        data = dict(_load())
        data["tokens"] = dict(data["tokens"])
        if any(v["label"] == label for v in data["tokens"].values()):
            raise ValueError(f"Đã có token cho nhãn '{label}'. Thu hồi trước khi tạo lại.")
        now = time.time()
        data["tokens"][_hash(token)] = {"label": label, "created": now, "expires": now + days * 86400}
        _save(data)
    return token


def verify_token(token: str | None) -> dict | None:
    """Trả {label, expires} nếu token hợp lệ và chưa hết hạn, ngược lại None."""
    if not token:
        return None
    h = _hash(token)
    entry = None
    for stored, v in _load()["tokens"].items():
        if hmac.compare_digest(stored, h):
            entry = v
    if not entry or entry["expires"] <= time.time():
        return None
    return {"label": entry["label"], "expires": entry["expires"]}


def list_tokens() -> list[dict]:
    """Thông tin công khai (không có token): nhãn, ngày tạo, hạn, còn hiệu lực không."""
    now = time.time()
    out = [{"label": v["label"], "created": v["created"], "expires": v["expires"], "active": v["expires"] > now}
           for v in _load()["tokens"].values()]
    return sorted(out, key=lambda x: x["label"])


def revoke_token(label: str) -> bool:
    with _lock:
        data = dict(_load())
        keep = {h: v for h, v in data["tokens"].items() if v["label"] != label}
        if len(keep) == len(data["tokens"]):
            return False
        data["tokens"] = keep
        _save(data)
    return True


def token_from_headers(headers) -> str | None:
    """Token nằm ở `Authorization: Bearer <token>`, `X-API-Key: <token>` (WeKnora gửi kiểu này),
    hoặc `Authorization: Basic base64(tên:token)` (mật khẩu là token; tên chỉ để dễ đọc).
    Thứ tự ưu tiên: Bearer, X-API-Key, Basic."""
    if not headers:
        return None
    get = headers.get
    auth = get("authorization") or get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    key = (get("x-api-key") or get("X-API-Key") or "").strip()
    if key:
        return key
    if auth[:6].lower() == "basic ":
        try:
            user, sep, password = base64.b64decode(auth[6:].strip(), validate=True).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        return (password if sep else user).strip() or None       # "token" hoặc "token:" cũng được
    return None


class Limiter:
    """Giới hạn không chờ: acquire() trả ngay (ok, lý do, số giây nên chờ)."""

    def __init__(self, max_global: int = 2, max_per_user: int = 1, per_minute: int = 20, clock=time.monotonic):
        self.max_global, self.max_per_user, self.per_minute, self.clock = max_global, max_per_user, per_minute, clock
        self._lock = threading.Lock()
        self._running = defaultdict(int)
        self._calls = defaultdict(deque)

    def acquire(self, user: str) -> tuple[bool, str | None, int]:
        with self._lock:
            now = self.clock()
            calls = self._calls[user]
            while calls and now - calls[0] >= 60:
                calls.popleft()
            if len(calls) >= self.per_minute:
                wait = int(60 - (now - calls[0])) + 1
                return False, f"Bạn đã gửi quá {self.per_minute} lệnh trong một phút.", wait
            if self._running[user] >= self.max_per_user:
                return False, "Bạn đang có một câu hỏi chạy dở.", 5
            if sum(self._running.values()) >= self.max_global:
                return False, "Máy chủ đang bận.", 10
            self._running[user] += 1
            calls.append(now)
            return True, None, 0

    def release(self, user: str):
        with self._lock:
            if self._running[user] > 0:
                self._running[user] -= 1
