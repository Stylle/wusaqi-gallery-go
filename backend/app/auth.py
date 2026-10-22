"""账号 / 会话 / 权限。

登录规则对齐常规站点：
  勾「记住我」→ token 存 localStorage，有效期 remember_days（默认 30 天）
  不勾       → token 存 sessionStorage，有效期 session_hours（默认 12 小时）
鉴权只认账号密码换来的会话 token，无任何万能凭据。
"""
import secrets
from datetime import datetime, timedelta, timezone

from . import db, util


def _now() -> datetime:
    return datetime.now(timezone.utc)


def public_user(u: dict) -> dict:
    usage = db.user_usage(u["id"])
    quota_mb = int(u.get("quota_mb") or 0)
    remaining = -1 if quota_mb == 0 else max(0, quota_mb * 1024 * 1024 - usage["used"])
    s = db.get_settings()
    is_admin = u.get("role") == "admin"
    # 单图上限：管理员不限；普通用户 用户覆盖 > 全局设置（默认 5MB）
    max_upload = 0 if is_admin else (int(u.get("max_upload_mb") or 0)
                                     or int(s.get("upload_max_mb") or 0) or 5)
    limits = {"daily": int(u.get("daily_limit") or 0),
              "weekly": int(u.get("weekly_limit") or 0),
              "monthly": int(u.get("monthly_limit") or 0)}
    if is_admin:                          # 管理员默认无限制
        limits = {k: 0 for k in limits}
    return {
        "id": u["id"],
        "username": u["username"],
        "role": u["role"],
        "quotaMb": quota_mb,
        "usedBytes": usage["used"],
        "imageCount": usage["count"],
        "remainingBytes": remaining,      # -1 = 不限
        "maxUploadMb": max_upload,
        "uploadLimits": limits,           # 0 = 不限（管理员恒为 0）
        "uploadCounts": db.user_upload_counts(u["id"]),
        "compFormat": u.get("comp_format"),
        "compQuality": u.get("comp_quality"),
        "compMaxWidth": u.get("comp_max_width"),
        "enabled": int(u.get("enabled", 1)),
        "createdAt": u.get("created_at"),
    }


def authenticate(username: str, password: str) -> dict | None:
    u = db.get_user_by_name((username or "").strip())
    if not u or not int(u.get("enabled", 1)):
        return None
    if not util.verify_password(password or "", u["pwd"]):
        return None
    return u


def make_session(user: dict, remember: bool) -> dict:
    s = db.get_settings()
    if remember:
        days = max(1, int(s.get("remember_days", "30") or 30))
        ttl = timedelta(days=days)
    else:
        hours = max(1, int(s.get("session_hours", "12") or 12))
        ttl = timedelta(hours=hours)
    token = secrets.token_urlsafe(32)
    expires = (_now() + ttl)
    db.create_session(token, user["id"], expires.isoformat(timespec="seconds"), remember)
    return {
        "token": token,
        "remember": bool(remember),
        "expiresAt": expires.isoformat(timespec="seconds"),
        "user": public_user(user),
    }


def resolve_token(tok: str) -> dict | None:
    """会话 token → user（过期/停用返回 None）。"""
    if not tok:
        return None
    sess = db.get_session(tok)
    if not sess:
        return None
    u = db.get_user(sess["user_id"])
    if not u or not int(u.get("enabled", 1)):
        return None
    return u


def change_password(user: dict, old: str, new: str) -> bool:
    if not util.verify_password(old or "", user["pwd"]):
        return False
    db.update_user(user["id"], {"pwd": util.hash_password(new)})
    return True
