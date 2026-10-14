"""Hồ sơ model (LLM qua MCP) và link mời để người khác tự điền cấu hình.

Lưu trong file JSON ngoài git (mặc định .cache/llm_profiles.json, đổi bằng T2SQL_PROFILES_FILE). File chứa token của người khác:
không in ra log, không hiển thị lại trên giao diện. Link mời chỉ lưu bản băm, có hạn dùng và bị vô hiệu sau khi lưu thành công.
"""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.Lock()
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


def _path():
    return os.environ.get("T2SQL_PROFILES_FILE") or os.path.join(ROOT, ".cache", "llm_profiles.json")


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("profiles", {})
    data.setdefault("invites", {})
    return data


def _save(data: dict):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)   # không có tác dụng đầy đủ trên Windows
    except OSError:
        pass


# --- hồ sơ ---
def list_profiles() -> list[dict]:
    """Thông tin công khai (không có token): name, url, tool, updated_at."""
    with _lock:
        profs = _load()["profiles"]
    return [{"name": n, "url": p["url"], "tool": p["tool"], "updated_at": p.get("updated_at", 0)} for n, p in sorted(profs.items())]


def get_profile(name: str) -> dict | None:
    with _lock:
        p = _load()["profiles"].get(name)
    return dict(p, name=name) if p else None


def save_profile(name: str, profile: dict):
    if not NAME_RE.match(name or ""):
        raise ValueError("Tên hồ sơ chỉ gồm chữ, số, dấu gạch, tối đa 40 ký tự.")
    with _lock:
        data = _load()
        data["profiles"][name] = dict(profile, updated_at=time.time())
        _save(data)


def delete_profile(name: str) -> bool:
    with _lock:
        data = _load()
        existed = data["profiles"].pop(name, None) is not None
        _save(data)
    return existed


# --- link mời ---
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invite(hours: float = 24, label: str = "") -> str:
    """Tạo mã mời (chỉ trả về một lần; file chỉ lưu bản băm)."""
    token = secrets.token_urlsafe(24)
    with _lock:
        data = _load()
        now = time.time()
        data["invites"] = {h: v for h, v in data["invites"].items() if v["expires"] > now and not v.get("used")}
        data["invites"][_hash(token)] = {"expires": now + hours * 3600, "label": label[:60], "used": False}
        _save(data)
    return token


def check_invite(token: str) -> bool:
    if not token:
        return False
    with _lock:
        v = _load()["invites"].get(_hash(token))
    return bool(v and not v.get("used") and v["expires"] > time.time())


def consume_invite(token: str):
    with _lock:
        data = _load()
        v = data["invites"].get(_hash(token))
        if v:
            v["used"] = True
            _save(data)


# --- kiểm tra địa chỉ do người ngoài nhập (tránh bắt máy mình gọi vào chỗ nguy hiểm) ---
def validate_url(url: str) -> str | None:
    """Trả về lý do từ chối, hoặc None nếu hợp lệ.

    Chỉ http/https. Luôn chặn địa chỉ link-local (169.254.x.x, nơi đặt metadata đám mây). Chặn loopback trừ khi
    T2SQL_MCP_ALLOW_LOCAL=1. Nếu đặt T2SQL_MCP_ALLOWED_HOSTS (danh sách host, cách nhau dấu phẩy) thì chỉ chấp nhận các host đó.
    http (không mã hóa) chỉ cho địa chỉ riêng/nội bộ; địa chỉ công khai phải là https.
    """
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return "Địa chỉ phải bắt đầu bằng http:// hoặc https://."
    allowed = [h.strip().lower() for h in os.environ.get("T2SQL_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if allowed and u.hostname.lower() not in allowed:
        return "Host này không nằm trong danh sách cho phép."
    try:
        infos = {i[4][0] for i in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))}
    except OSError:
        return "Không phân giải được tên miền."
    allow_local = os.environ.get("T2SQL_MCP_ALLOW_LOCAL") == "1"
    private = False
    for raw in infos:
        ip = ipaddress.ip_address(raw.split("%")[0])
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return "Địa chỉ này không được phép."
        if ip.is_loopback:
            if not allow_local:
                return "Địa chỉ loopback không được phép."
            private = True
        elif ip.is_private:
            private = True
    if u.scheme == "http" and not private:
        return "Địa chỉ công khai phải dùng https."
    return None
