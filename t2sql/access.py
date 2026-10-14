"""Chọn vai trò được hiển thị trên giao diện: vai trò đặc quyền (không che dữ liệu, không chặn cột) bị ẩn trừ khi được mở khóa.

Ứng dụng chưa có đăng nhập theo người dùng, nên đây chỉ là rào chắn đơn giản cho giai đoạn thử nghiệm:
  * không đặt gì: chỉ thấy các vai trò hạn chế (ví dụ analyst);
  * T2SQL_ADMIN_PASSWORD: nhập đúng mật khẩu ở thanh bên thì thấy thêm vai trò đặc quyền;
  * T2SQL_ALLOW_ADMIN=1: luôn hiện mọi vai trò (chỉ dùng khi chạy trên máy cá nhân).
"""
import hmac
import os

from .safety import Policy


def is_privileged(policy: Policy) -> bool:
    """Vai trò không che PII và không chặn cột nào (ví dụ admin)."""
    return not policy.mask_pii and not policy.denied_columns


def admin_always_allowed() -> bool:
    return (os.environ.get("T2SQL_ALLOW_ADMIN") or "").strip().lower() in ("1", "true", "yes")


def admin_password() -> str:
    return os.environ.get("T2SQL_ADMIN_PASSWORD") or ""


def password_matches(given: str) -> bool:
    expected = admin_password()
    return bool(expected) and hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def selectable_roles(policies: dict, unlocked: bool = False) -> list[str]:
    """Danh sách vai trò hiện cho người dùng. unlocked = đã nhập đúng mật khẩu quản trị."""
    if unlocked or admin_always_allowed():
        return list(policies)
    return [name for name, pol in policies.items() if not is_privileged(pol)]
