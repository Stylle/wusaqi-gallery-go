"""lolis-gallery 后端。

v2：权限门控 + 流量防御（限流→webhook 告警→封禁）+ 站点信息后台可配。
v3：用户体系（账号密码登录 / 配额 / 每人压缩参数 / 图片归属）+ 标签筛选 +
    图片重命名与删除 + 按日期分目录存储 + 分享基址。
设计约定：新增配置项只需在 db.DEFAULT_SETTINGS 加键 + 在 main.py 的
PUBLIC_SETTING_KEYS / put_settings 规则里声明，前后端自动生效。
"""
import ipaddress
import json
import math
import os
import secrets
import threading
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from PIL import Image

from . import auth, compress, config, db, notify, perf, util


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动即建表/迁移，并把管理员配置摘要打到日志里（不含密码）。"""
    db.get_conn()
    db.purge_visits()
    threading.Thread(target=notify.report_worker, daemon=True).start()
    admin = db.get_admin()
    token_state = "启用" if (config.ALLOW_ADMIN_TOKEN and config.ADMIN_TOKEN) else "关闭"
    lines = [f"[lolis-gallery] 数据目录 {config.DATA_DIR}",
             f"[lolis-gallery] 管理员用户名 {admin['username'] if admin else '(未创建)'}",
             f"[lolis-gallery] ADMIN_TOKEN 直登 {token_state}"]
    if config.ADMIN_PASSWORD == "changeme":
        lines.append("[lolis-gallery] ⚠️  管理员密码为默认值 changeme，请设置 "
                     "ADMIN_PASSWORD 环境变量，并设 ADMIN_SYNC=1 同步到已有账号")
    lines.append(f"[lolis-gallery] {perf.describe()}")
    print("\n".join(lines), flush=True)
    yield


app = FastAPI(title="lolis-gallery", docs_url=None, redoc_url=None, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"],
)

for d in (config.UPLOADS_DIR, config.THUMBS_DIR, config.COMPRESSED_DIR):
    os.makedirs(d, exist_ok=True)

# 静态图片兜底：生产环境由 nginx 直接伺服（命中不到才会到这），本地开发/裸跑时由后端承担
app.mount("/files", StaticFiles(directory=config.UPLOADS_DIR), name="files")
app.mount("/thumbs", StaticFiles(directory=config.THUMBS_DIR), name="thumbs")
app.mount("/compressed", StaticFiles(directory=config.COMPRESSED_DIR), name="compressed")

# ---------- 防御状态（内存态，重启清零） ----------
bans: dict[str, list] = {}            # ip -> [until_ts, reason]
_rate_windows: dict[str, list[float]] = defaultdict(list)  # ip -> [timestamps]
_auth_fails: dict[str, list[float]] = defaultdict(list)    # ip -> [fail timestamps]


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else "?")


def is_banned(ip: str) -> tuple[bool, str]:
    entry = bans.get(ip)
    if entry and entry[0] > time.time():
        return True, entry[1]
    bans.pop(ip, None)
    return False, ""


def ban_ip(ip: str, minutes: int, reason: str) -> None:
    bans[ip] = [time.time() + minutes * 60, reason]


def fire_webhook(event: str, message: str = "", **fields) -> None:
    """按后台「通知」配置异步投递（见 notify.py）。"""
    notify.fire(event, message or event, fields)


def note_fail(ip: str) -> None:
    """登录失败计数，超阈值封禁（防爆破）。"""
    now = time.time()
    fails = [t for t in _auth_fails[ip] if now - t < 600]
    fails.append(now)
    _auth_fails[ip] = fails
    s = db.get_settings()
    if len(fails) >= max(1, int(s.get("auth_max_fails", "10"))):
        minutes = max(1, int(s.get("auth_ban_minutes", "10")))
        ban_ip(ip, minutes, "auth brute force")
        _auth_fails.pop(ip, None)
        fire_webhook("auth_brute_force", ip=ip, fails=len(fails), ban_minutes=minutes)
        raise HTTPException(429, f"too many failures, banned {minutes}min")


# ---------- 限流中间件（随机图接口） ----------
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    ip = client_ip(request)
    banned, reason = is_banned(ip)
    if banned:
        return JSONResponse(
            {"error": f"banned until {datetime.fromtimestamp(bans[ip][0], timezone.utc).isoformat()} ({reason})"},
            status_code=429)
    s = db.get_settings()
    limit = int(s.get("rate_limit", "0") or 0)
    if request.url.path.startswith("/api/random") and limit > 0:
        now = time.time()
        window = [t for t in _rate_windows[ip] if now - t < 60]
        if len(window) >= limit:
            ban_minutes = max(1, int(s.get("rate_ban_minutes", "10")))
            ban_ip(ip, ban_minutes, "rate limit exceeded")
            _rate_windows.pop(ip, None)
            fire_webhook("rate_limit", ip=ip, path=request.url.path,
                         limit_per_minute=limit, ban_minutes=ban_minutes)
            return JSONResponse({"error": f"rate limited, banned {ban_minutes}min"},
                                status_code=429)
        window.append(now)
        _rate_windows[ip] = window
        if len(_rate_windows) > 10000:
            _rate_windows.clear()
    response = await call_next(request)
    # 访问统计：只记 API 请求（静态图由 nginx/静态目录直接出，量大且无分析价值）
    try:
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            db.record_visit(ip, path, response.status_code)
    except Exception:
        pass  # 统计失败不影响请求
    return response


# ---------- 鉴权 ----------
def _bearer(authorization: str) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def current_user(request: Request, authorization: str = Header(default="")) -> dict | None:
    ip = client_ip(request)
    banned, reason = is_banned(ip)
    if banned:
        raise HTTPException(429, f"banned ({reason})")
    return auth.resolve_token(_bearer(authorization))


def require_user(request: Request, authorization: str = Header(default="")) -> dict:
    u = current_user(request, authorization)
    if not u:
        raise HTTPException(401, "login required")
    return u


def require_admin(request: Request, authorization: str = Header(default="")) -> dict:
    u = require_user(request, authorization)
    if u["role"] != "admin":
        raise HTTPException(403, "admin only")
    return u


# ---------- 序列化 ----------
def item_json(row: dict, viewer: dict | None = None) -> dict:
    return {
        "id": row["id"],
        "key": row["key"],
        "url": f"/files/{row['key']}",
        "thumb": f"/thumbs/{row['key']}.webp",
        "compressed": (f"/compressed/{row['c_key']}" if row.get("c_key") else None),
        "width": row["width"], "height": row["height"],
        "mimeType": row["mime"], "size": row["size"],
        "compressedSize": row.get("c_size"),
        "createdAt": row["created_at"],
        "tag": row.get("tag") or "",
        "filename": os.path.basename(row["key"]),
        "origName": row.get("orig_name") or "",
        "ownerId": row.get("owner_id") or "",
        "owner": row.get("owner_name") or "",
        "mine": bool(viewer and row.get("owner_id") == viewer["id"]),
        "canEdit": bool(viewer and (viewer["role"] == "admin"
                                    or row.get("owner_id") == viewer["id"])),
    }


def limits_for(user: dict) -> dict:
    """用户级覆盖 > 当前压缩方案（自动探测档位或自定义）。"""
    s = db.get_settings()
    eff = perf.effective(s)
    fmt = user.get("comp_format") or eff["format"]
    quality = user.get("comp_quality")
    max_w = user.get("comp_max_width")
    return {
        "max_upload_mb": (int(user.get("max_upload_mb") or 0)
                          or int(s.get("upload_max_mb") or 0) or 5),
        "quota_bytes": int(user.get("quota_mb") or 0) * 1024 * 1024,
        "format": fmt if fmt in config.COMP_FORMATS else "webp",
        "quality": max(1, min(100, int(quality if quality is not None else eff["quality"]))),
        "max_width": max(0, int(max_w if max_w is not None else eff["maxWidth"])),
        "method": eff["method"],
        "max_pixels": eff["maxPixels"],
        "concurrency": eff["concurrency"],
        "thumb_quality": eff["thumbQuality"],
        "thumb_method": eff["thumbMethod"],
    }


def _check_pixels(width: int, height: int, lim: dict) -> None:
    """解码前按当前方案拦超大图（1G 机器解一张 100MP 图会直接 OOM）。"""
    mp = lim.get("max_pixels") or 0
    if not mp or not width or not height:
        return
    if width * height > mp * 1_000_000:
        raise ValueError(
            f"图片分辨率 {width}×{height}（约 {width * height / 1_000_000:.0f} MP）"
            f"超过当前压缩方案上限 {mp} MP，请先缩小图片或改用「自定义」方案放宽")


_UPLOAD_WINDOWS = (
    ("daily_limit", "day", "今日（24 小时内）"),
    ("weekly_limit", "week", "本周（7 天内）"),
    ("monthly_limit", "month", "本月（30 天内）"),
)


def _check_upload_limits(user: dict) -> None:
    """上传张数限制：管理员不受限，普通用户按日/周/月滑动窗口。"""
    if user.get("role") == "admin":
        return
    limits = [(k, w, label) for k, w, label in _UPLOAD_WINDOWS
              if int(user.get(k) or 0) > 0]
    if not limits:
        return
    counts = db.user_upload_counts(user["id"])
    for key, window, label in limits:
        cap = int(user.get(key) or 0)
        if counts[window] >= cap:
            raise ValueError(f"{label}上传已达上限 {cap} 张，请稍后再试或联系管理员")


def save_one(data: bytes, filename: str, user: dict, tag: str = "") -> dict:
    """落盘原图 + 生成缩略图/压缩版 + 写库，返回图片记录。"""
    lim = limits_for(user)
    is_admin = user.get("role") == "admin"
    # 单图上限：管理员不限；普通用户 用户级覆盖 > 全局设置（默认 5MB）
    if not is_admin and lim["max_upload_mb"] and len(data) > lim["max_upload_mb"] * 1024 * 1024:
        raise ValueError(f"超过单图上限 {lim['max_upload_mb']}MB")
    _check_upload_limits(user)
    if not is_admin and lim["quota_bytes"]:
        used = db.user_usage(user["id"])["used"]
        if used + len(data) > lim["quota_bytes"]:
            left = max(0, lim["quota_bytes"] - used)
            raise ValueError(f"quota exceeded (left {left // 1024} KB)")

    info = compress.read_info(data)  # 只读头部；解不开直接抛异常
    _check_pixels(info["width"], info["height"], lim)

    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in config.ALLOWED_EXT:
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
               "image/gif": "gif", "image/avif": "avif", "image/bmp": "bmp",
               }.get(info["mime"], "jpg")

    key = util.new_key(ext)
    while db.key_exists(key):
        key = util.new_key(ext)

    orig_path = os.path.join(config.UPLOADS_DIR, key)
    os.makedirs(os.path.dirname(orig_path), exist_ok=True)
    with open(orig_path, "wb") as f:
        f.write(data)

    width, height = info["width"], info["height"]

    c_rel, c_meta = None, {}
    # 压缩/缩略图是 CPU 与内存大户：低配机器由并发槽排成一路做完
    with perf.pool.slot(lim["concurrency"]):
        compress.make_thumb(data, key, lim["thumb_quality"], lim["thumb_method"])
        if info["format"] != "GIF":  # GIF 不压缩，保留动图
            try:
                c_rel, c_meta = compress.make_compressed(
                    data, os.path.splitext(key)[0], fmt=lim["format"],
                    quality=lim["quality"], max_width=lim["max_width"],
                    method=lim["method"])
            except Exception:
                c_rel, c_meta = None, {}

    row = {
        "id": util.short_id(),
        "key": key,
        "owner_id": user["id"],
        "tag": (tag or "").strip()[:40],
        "orig_name": os.path.basename(filename)[:120],
        "mime": info["mime"], "width": width, "height": height, "size": len(data),
        "c_key": c_rel, "c_mime": c_meta.get("c_mime"),
        "c_width": c_meta.get("c_width"), "c_height": c_meta.get("c_height"),
        "c_size": c_meta.get("c_size"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    while db.get_image(row["id"]):
        row["id"] = util.short_id()
    db.insert_image(row)
    return item_json(row, user)


# ---------- 公开接口 ----------
PUBLIC_SETTING_KEYS = ("site_title", "site_icon", "site_tags", "site_footer",
                       "random_public", "share_base_url", "upload_default_tags",
                       "theme_style")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/public/settings")
def public_settings():
    s = db.get_settings()
    out = {k: s.get(k, "") for k in PUBLIC_SETTING_KEYS}
    # 前端据此决定是否显示「用管理员 Token 登录」入口（非 DB 配置，来自环境变量）
    out["token_login"] = "1" if (config.ALLOW_ADMIN_TOKEN and config.ADMIN_TOKEN) else "0"
    # 上传面板的提示信息：单图上限与可用格式（后台设置为准，默认 5MB）
    out["upload_max_mb"] = str(int(s.get("upload_max_mb") or 0) or 5)
    out["upload_formats"] = "jpg,jpeg,png,webp,avif,gif,bmp"
    return out


@app.get("/api/images")
def images(request: Request, page: int = 1, limit: int = 24, sort: str = "latest",
           tag: str = "", mine: int = 0, authorization: str = Header(default="")):
    page = max(1, page)
    limit = max(1, min(100, limit))
    owner_id = None
    viewer = auth.resolve_token(_bearer(authorization))
    if mine:
        if not viewer:
            raise HTTPException(401, "login required for mine filter")
        owner_id = viewer["id"]
    items, total = db.list_images(page, limit,
                                  sort if sort in ("latest", "random") else "latest",
                                  tag=(tag or "").strip() or None, owner_id=owner_id)
    out = []
    for r in items:
        d = item_json(r, viewer)
        out.append(d)
    return {"items": out, "page": page, "limit": limit, "total": total,
            "hasMore": page * limit < total}


@app.get("/api/tags")
def tags():
    s = db.get_settings()
    counted = db.tag_counts()
    order = [t.strip() for t in (s.get("site_tags") or "").split(",") if t.strip()]
    seen, out = set(), []
    for t in order:
        out.append({"name": t, "count": counted.get(t, 0)})
        seen.add(t)
    for t, n in sorted(counted.items(), key=lambda kv: -kv[1]):
        if t not in seen:
            out.append({"name": t, "count": n})
    return {"tags": out}


def _random_row(variant: str) -> tuple[dict, str]:
    row = db.random_image()
    if not row:
        raise HTTPException(404, "no images")
    if variant == "original" or not row["c_key"]:
        return row, f"/files/{row['key']}"
    return row, f"/compressed/{row['c_key']}"


def random_guard(request: Request, authorization: str = Header(default="")):
    """随机图默认仅登录可用；后台开启 random_public 后对游客开放（外链场景）。"""
    if db.get_settings().get("random_public") == "1":
        return None
    return require_user(request, authorization)


@app.get("/api/random")
def random_json(variant: str = "compressed", redirect: bool = False,
                __=Depends(random_guard)):
    row, path = _random_row(variant)
    if redirect:
        return RedirectResponse(path, status_code=302)
    return item_json(row)


@app.get("/api/random/image")
def random_image(variant: str = "compressed", __=Depends(random_guard)):
    _row, path = _random_row(variant)
    return RedirectResponse(path, status_code=302)


# ---------- 登录 / 会话 ----------
@app.post("/api/auth/login")
def login(payload: dict, request: Request):
    ip = client_ip(request)
    banned, reason = is_banned(ip)
    if banned:
        raise HTTPException(429, f"banned ({reason})")
    user = auth.authenticate(payload.get("username", ""), payload.get("password", ""))
    if not user:
        note_fail(ip)
        raise HTTPException(401, "用户名或密码错误")
    _auth_fails.pop(ip, None)
    db.purge_expired_sessions()
    if user.get("role") == "admin" and db.get_setting("notify_admin_login") == "1":
        fire_webhook("admin_login", f"管理员 {user['username']} 刚刚登录了后台",
                     ip=ip, username=user["username"])
    return auth.make_session(user, bool(payload.get("remember")))


@app.post("/api/auth/logout")
def logout(request: Request, authorization: str = Header(default="")):
    tok = _bearer(authorization)
    is_root_token = (config.ALLOW_ADMIN_TOKEN and config.ADMIN_TOKEN
                     and secrets.compare_digest(tok, config.ADMIN_TOKEN))
    if tok and not is_root_token:
        db.delete_session(tok)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(require_user)):
    return auth.public_user(user)


@app.post("/api/auth/password")
def change_password(payload: dict, user: dict = Depends(require_user)):
    new = (payload.get("new") or "").strip()
    if len(new) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    if not auth.change_password(user, payload.get("old", ""), new):
        raise HTTPException(401, "原密码错误")
    return {"ok": True}


# ---------- 用户管理（管理员） ----------
def _clean_user_payload(p: dict, partial: bool = False) -> dict:
    out = {}
    if "username" in p or not partial:
        name = str(p.get("username", "")).strip()
        if not (3 <= len(name) <= 32) or not all(c.isalnum() or c in "_-." for c in name):
            raise HTTPException(400, "用户名 3-32 位，仅字母数字 _ - .")
        out["username"] = name
    if "role" in p or not partial:
        role = p.get("role", "user")
        if role not in ("admin", "user"):
            raise HTTPException(400, "role 必须是 admin 或 user")
        out["role"] = role
    # 配额按 MB 存整数：小数向上取整，避免 0.5MB 被截断成 0（0 = 不限量，静默放开配额）
    if "quota_mb" in p:
        try:
            v = float(p["quota_mb"] or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "quota_mb 必须是数字")
        out["quota_mb"] = max(0, math.ceil(v))
    for k in ("max_upload_mb", "daily_limit", "weekly_limit", "monthly_limit"):
        if k in p:
            out[k] = max(0, int(p[k] or 0))
    if "comp_quality" in p:
        v = p["comp_quality"]
        out["comp_quality"] = None if v in (None, "") else max(1, min(100, int(v)))
    if "comp_format" in p:
        v = p["comp_format"]
        out["comp_format"] = v if v in config.COMP_FORMATS else None
    if "enabled" in p:
        out["enabled"] = 1 if p["enabled"] in (1, True, "1", "true") else 0
    return out


@app.get("/api/users")
def list_users(_: dict = Depends(require_admin)):
    return {"users": [
        {**u, "remainingBytes": (-1 if not u["quota_mb"]
                                 else max(0, u["quota_mb"] * 1024 * 1024 - u["used"]))}
        for u in db.list_users()]}


@app.post("/api/users")
def create_user(payload: dict, _: dict = Depends(require_admin)):
    fields = _clean_user_payload(payload)
    pwd = (payload.get("password") or "").strip()
    if len(pwd) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if db.get_user_by_name(fields["username"]):
        raise HTTPException(409, "用户名已存在")
    # 未显式指定的额度 → 用后台「新建用户默认额度」
    s = db.get_settings()
    for key, skey, fallback in (
            ("quota_mb", "new_user_quota_mb", 500),
            ("max_upload_mb", "new_user_max_upload_mb", 5),
            ("daily_limit", "new_user_daily", 30),
            ("weekly_limit", "new_user_weekly", 100),
            ("monthly_limit", "new_user_monthly", 250)):
        if key not in fields:
            try:
                fields[key] = int(s.get(skey) or fallback)
            except (TypeError, ValueError):
                fields[key] = fallback
    u = db.create_user(
        fields["username"], pwd, fields.get("role", "user"),
        fields.get("quota_mb", 0), fields.get("max_upload_mb", 0),
        fields.get("comp_format"), fields.get("comp_quality"),
        None,
        fields.get("daily_limit", 0), fields.get("weekly_limit", 0),
        fields.get("monthly_limit", 0))
    return {"ok": True, "user": auth.public_user(u)}


@app.patch("/api/users/{user_id}")
def patch_user(user_id: str, payload: dict, admin: dict = Depends(require_admin)):
    target = db.get_user(user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    fields = _clean_user_payload(payload, partial=True)
    if "username" in fields and fields["username"] != target["username"]:
        if db.get_user_by_name(fields["username"]):
            raise HTTPException(409, "用户名已存在")
    if target["role"] == "admin" and fields.get("role") == "user":
        if sum(1 for u in db.list_users() if u["role"] == "admin") <= 1:
            raise HTTPException(400, "不能取消最后一个管理员的角色")
    if user_id == admin["id"] and fields.get("enabled") == 0:
        raise HTTPException(400, "不能停用自己")
    pwd = (payload.get("password") or "").strip()
    if pwd:
        if len(pwd) < 6:
            raise HTTPException(400, "密码至少 6 位")
        fields["pwd"] = util.hash_password(pwd)
    db.update_user(user_id, fields)
    return {"ok": True, "user": auth.public_user(db.get_user(user_id))}


@app.delete("/api/users/{user_id}")
def remove_user(user_id: str, purge: bool = False, admin: dict = Depends(require_admin)):
    target = db.get_user(user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if user_id == admin["id"]:
        raise HTTPException(400, "不能删除自己")
    if target["role"] == "admin" and sum(1 for u in db.list_users()
                                         if u["role"] == "admin") <= 1:
        raise HTTPException(400, "不能删除最后一个管理员")
    removed = db.delete_user(user_id, purge)
    return {"ok": True, "removedImages": removed}


# ---------- 上传 ----------
def _do_upload(files: list[UploadFile], tag: str, user: dict) -> dict:
    results = []
    for f in files:
        name = f.filename or "unnamed"
        try:
            data = f.file.read()
            results.append({"name": name, "ok": True,
                            "item": save_one(data, name, user, tag)})
        except Exception as e:
            results.append({"name": name, "ok": False, "error": str(e)})
        finally:
            f.file.close()
    return {"results": results,
            "usage": auth.public_user(user)}


@app.post("/api/upload")
def upload(files: list[UploadFile] = File(...), tag: str = Form(default=""),
           user: dict = Depends(require_user)):
    return _do_upload(files, tag, user)


@app.post("/api/admin/upload")
def upload_compat(files: list[UploadFile] = File(...), tag: str = Form(default=""),
                  user: dict = Depends(require_user)):
    """v2 路径兼容。"""
    return _do_upload(files, tag, user)


# ---------- 图片重命名 / 删除 ----------
def _assert_can_edit(user: dict, img: dict) -> None:
    if user["role"] != "admin" and img.get("owner_id") != user["id"]:
        raise HTTPException(403, "只能操作自己上传的图片")


def _move_file(root: str, old_rel: str, new_rel: str) -> bool:
    """在同一数据卷内移动文件（root 为 uploads/thumbs/compressed 根目录）。"""
    src = os.path.join(root, old_rel)
    if not os.path.exists(src):
        return False
    dst = os.path.join(root, new_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(src, dst)
    return True


@app.patch("/api/images/{image_id}")
def patch_image(image_id: str, payload: dict, user: dict = Depends(require_user)):
    img = db.get_image(image_id)
    if not img:
        raise HTTPException(404, "图片不存在")
    _assert_can_edit(user, img)

    fields: dict = {}
    if "tag" in payload:
        fields["tag"] = str(payload["tag"] or "").strip()[:40]

    filename = (payload.get("filename") or "").strip()
    if filename:
        old_key = img["key"]
        d = os.path.dirname(old_key)
        ext = os.path.splitext(old_key)[1]
        stem = util.safe_stem(filename, fallback=os.path.splitext(os.path.basename(old_key))[0])
        if stem.lower().endswith(ext.lower().lstrip(".")):
            stem = stem[: -len(ext.lstrip("."))].rstrip(" .-") or stem
        new_key = f"{d}/{stem}{ext}"
        if new_key != old_key:
            if db.key_exists(new_key):
                raise HTTPException(409, "该文件名已存在")
            _move_file(config.UPLOADS_DIR, old_key, new_key)                  # 原图
            _move_file(config.THUMBS_DIR, old_key + ".webp", new_key + ".webp")  # 缩略图
            fields["key"] = new_key
            fields["orig_name"] = stem + ext
            if img.get("c_key"):
                c_ext = os.path.splitext(img["c_key"])[1]
                new_c = f"{os.path.dirname(img['c_key'])}/{stem}{c_ext}"
                _move_file(config.COMPRESSED_DIR, img["c_key"], new_c)         # 压缩图
                fields["c_key"] = new_c

    if fields:
        db.update_image(image_id, fields)
    return item_json(db.get_image(image_id), user)


@app.delete("/api/images/{image_id}")
def delete_image(image_id: str, user: dict = Depends(require_user)):
    img = db.get_image(image_id)
    if not img:
        raise HTTPException(404, "图片不存在")
    _assert_can_edit(user, img)
    for path in (os.path.join(config.UPLOADS_DIR, img["key"]),
                 os.path.join(config.THUMBS_DIR, img["key"] + ".webp"),
                 os.path.join(config.COMPRESSED_DIR, img["c_key"]) if img.get("c_key") else None):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    db.delete_image(image_id)
    return {"ok": True, "id": image_id}


# ---------- 后台配置 ----------
@app.post("/api/admin/verify")
def verify(user: dict = Depends(require_user)):
    return {"ok": True, "user": auth.public_user(user)}


@app.get("/api/admin/settings")
def get_settings(_: dict = Depends(require_admin)):
    return db.get_settings()


@app.put("/api/admin/settings")
def put_settings(patch: dict, _: dict = Depends(require_admin)):
    """通用配置更新：只接受 DEFAULT_SETTINGS 里声明的键，按类型夹紧。"""
    defaults = db.DEFAULT_SETTINGS
    zero_ok = {"comp_max_width", "comp_max_pixels", "comp_concurrency",
               "upload_max_mb", "new_user_quota_mb", "new_user_max_upload_mb",
               "new_user_daily", "new_user_weekly", "new_user_monthly", "rate_limit"}
    switches = ("random_public", "notify_admin_login", "notify_daily",
                "notify_weekly", "notify_monthly")
    clean = {}
    for k, v in (patch or {}).items():
        if k not in defaults:
            continue
        if k == "comp_profile":
            if v in perf.MODES:
                clean[k] = v
        elif k == "comp_format":
            if v in config.COMP_FORMATS:
                clean[k] = v
        elif k == "comp_quality":
            clean[k] = max(1, min(100, int(v)))
        elif k == "comp_method":
            clean[k] = max(0, min(6, int(v)))
        elif k in zero_ok:
            clean[k] = max(0, int(v))
        elif k in ("rate_ban_minutes", "auth_max_fails", "auth_ban_minutes",
                   "session_hours", "remember_days"):
            clean[k] = max(1, int(v))
        elif k in switches:
            clean[k] = "1" if (v is True or str(v).lower() in ("1", "true", "on")) else "0"
        elif k == "notify_method":
            if v in ("POST", "PUT", "GET"):
                clean[k] = v
        elif k == "notify_body_type":
            if v in ("json", "text"):
                clean[k] = v
        elif k == "theme_style":
            if v in ("gradient", "solid"):
                clean[k] = v
        elif k == "notify_daily_time":
            t = str(v).strip()
            clean[k] = t if len(t) == 5 and t[:2].isdigit() and t[3:].isdigit() else "09:00"
        elif k in ("notify_headers", "notify_body_tpl"):
            clean[k] = str(v).strip()[:2000]
        else:  # 文本类
            clean[k] = str(v).strip()[:500]
    if not clean:
        raise HTTPException(400, "no valid fields")
    db.update_settings(clean)
    return db.get_settings()


@app.get("/api/admin/system")
def admin_system(_: dict = Depends(require_admin)):
    """压缩方案运行态：自动探测结果、当前生效参数、可选档位与支持格式。"""
    s = db.get_settings()
    return {
        "perf": perf.effective(s),
        "profiles": [{"name": k, **v} for k, v in perf.PROFILES.items()],
        "formats": compress.INPUT_FORMATS,
        "pool": perf.pool.state,
    }


# ---------- 本地图库（扫描导入 / 补压缩） ----------
# 场景：把图片直接丢进 data/uploads（或从旧图床迁移过来），不经上传接口，
# 由后台扫描入库，归属管理员；缺压缩版的一次性补齐。全部按全局压缩配置执行。

def _local_pending(known: set[str]) -> tuple[int, list[dict]]:
    """遍历 uploads，返回 (扫描文件数, 未入库文件列表)。只读文件头，不整图解码，省 CPU。"""
    scanned, pending = 0, []
    for root, _dirs, names in os.walk(config.UPLOADS_DIR):
        for name in names:
            scanned += 1
            full = os.path.join(root, name)
            rel = os.path.relpath(full, config.UPLOADS_DIR).replace("\\", "/")
            if rel in known:
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            item = {"key": rel, "size": os.path.getsize(full),
                    "ok": True, "error": "", "width": None, "height": None}
            if ext not in config.ALLOWED_EXT:
                item["ok"], item["error"] = False, "不支持的扩展名"
            else:
                try:
                    with Image.open(full) as im:      # 懒加载：只读头部
                        item["width"], item["height"] = im.size
                        item["format"] = (im.format or "").upper()
                except Exception:
                    item["ok"], item["error"] = False, "无法解析为图片"
            pending.append(item)
    pending.sort(key=lambda x: x["key"])
    return scanned, pending


def _import_one(full: str, rel: str, user: dict, lim: dict) -> dict:
    """把已存在于 uploads 的原图登记入库（key 保持不变），并补缩略图/压缩版。

    本地扫描导入不走上传链路：不检查单图大小上限（磁盘上已有的文件没有拦截意义）。
    """
    size = os.path.getsize(full)
    with open(full, "rb") as fh:
        data = fh.read()
    info = compress.read_info(data)
    _check_pixels(info["width"], info["height"], lim)
    width, height = info["width"], info["height"]

    c_rel, c_meta = None, {}
    with perf.pool.slot(lim["concurrency"]):
        compress.make_thumb(data, rel, lim["thumb_quality"], lim["thumb_method"])
        if info["format"] != "GIF":                   # GIF 保留动图不压缩
            try:
                c_rel, c_meta = compress.make_compressed(
                    data, os.path.splitext(rel)[0], fmt=lim["format"],
                    quality=lim["quality"], max_width=lim["max_width"],
                    method=lim["method"])
            except Exception:
                c_rel, c_meta = None, {}

    row = {
        "id": util.short_id(), "key": rel, "owner_id": user["id"], "tag": "",
        "orig_name": os.path.basename(full)[:120],
        "mime": info["mime"], "width": width, "height": height, "size": size,
        "c_key": c_rel, "c_mime": c_meta.get("c_mime"),
        "c_width": c_meta.get("c_width"), "c_height": c_meta.get("c_height"),
        "c_size": c_meta.get("c_size"),
        # 本地文件用修改时间，画廊排序更接近真实拍摄/落地时间
        "created_at": datetime.fromtimestamp(
            os.path.getmtime(full), timezone.utc).isoformat(timespec="seconds"),
    }
    while db.get_image(row["id"]):
        row["id"] = util.short_id()
    db.insert_image(row)
    return item_json(db.get_image(row["id"]), user)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


@app.get("/api/admin/local/scan")
def local_scan(dry_run: bool = True, limit: int = 50,
               admin: dict = Depends(require_admin)):
    """扫描 data/uploads：库里没有的原图 → 导入并归属管理员。

    dry_run=true（默认）只预览不写库；dry_run=false 按 limit 分批导入，可反复调用。
    """
    limit = _clamp(limit, 1, 200)
    known = db.all_keys()
    scanned, pending = _local_pending(known)
    ok_items = [p for p in pending if p["ok"]]
    bad_items = [p for p in pending if not p["ok"]]

    imported, failed = 0, []
    if not dry_run:
        lim = limits_for(admin)
        for p in ok_items[:limit]:
            try:
                _import_one(os.path.join(config.UPLOADS_DIR, p["key"]), p["key"], admin, lim)
                imported += 1
            except Exception as e:
                failed.append({"key": p["key"], "error": str(e)})

    return {
        "dryRun": dry_run,
        "scanned": scanned,                 # 目录里文件总数
        "indexed": len(known),              # 已在库
        "pendingCount": len(ok_items),      # 待导入（可导入）
        "invalidCount": len(bad_items),     # 无法导入（非图片等）
        "pending": ok_items[:limit],
        "invalid": bad_items[:limit],
        "imported": imported,
        "failed": failed,
        "remaining": max(0, len(ok_items) - imported),
    }


@app.post("/api/admin/local/compress")
def local_compress(dry_run: bool = True, limit: int = 5,
                   admin: dict = Depends(require_admin)):
    """给缺压缩版/缩略图的图片补生成（按全局压缩配置）。

    limit 控制单次处理张数 —— 低配 VPS 建议 3~5，反复点几次即可，避免 CPU 打满。
    """
    limit = _clamp(limit, 1, 50)
    s = db.get_settings()
    eff = perf.effective(s)
    fmt = eff["format"]
    quality = eff["quality"]
    max_width = eff["maxWidth"]

    todo = []
    for r in db.all_images():
        c_path = os.path.join(config.COMPRESSED_DIR, r["c_key"]) if r.get("c_key") else None
        need_c = not c_path or not os.path.exists(c_path)
        need_t = not os.path.exists(os.path.join(config.THUMBS_DIR, r["key"] + ".webp"))
        if need_c or need_t:
            todo.append({"row": r, "compressed": need_c, "thumb": need_t})

    batch = todo[:limit]
    done, failed = 0, []
    if not dry_run:
        for t in batch:
            r = t["row"]
            full = os.path.join(config.UPLOADS_DIR, r["key"])
            if not os.path.exists(full):
                failed.append({"key": r["key"], "error": "原图文件不存在"})
                continue
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
                with perf.pool.slot(eff["concurrency"]):
                    if t["thumb"]:
                        compress.make_thumb(data, r["key"], eff["thumbQuality"],
                                            eff["thumbMethod"])
                    if t["compressed"]:
                        c_rel, meta = compress.make_compressed(
                            data, os.path.splitext(r["key"])[0], fmt, quality,
                            max_width, method=eff["method"])
                        old = r.get("c_key")
                        if old and old != c_rel:      # 格式变了：清掉旧压缩文件
                            try:
                                os.remove(os.path.join(config.COMPRESSED_DIR, old))
                            except OSError:
                                pass
                        db.update_image(r["id"], {"c_key": c_rel, **meta})
                done += 1
            except Exception as e:
                failed.append({"key": r["key"], "error": str(e)})
    return {
        "dryRun": dry_run,
        "todoCount": len(todo),
        "done": done,
        "remaining": max(0, len(todo) - done),
        "settings": {"format": fmt, "quality": quality, "maxWidth": max_width,
                     "profile": eff["profile"], "label": eff["label"],
                     "concurrency": eff["concurrency"]},
        "items": [{"key": t["row"]["key"], "filename": os.path.basename(t["row"]["key"]),
                   "compressed": t["compressed"], "thumb": t["thumb"],
                   "size": t["row"]["size"]} for t in batch],
        "failed": failed,
    }


@app.post("/api/admin/reindex")
def reindex(admin: dict = Depends(require_admin)):
    """v4 兼容别名：等价于「本地图库导入」全量执行一次。"""
    limit = 100000
    known = db.all_keys()
    scanned, pending = _local_pending(known)
    lim = limits_for(admin)
    added = 0
    for p in pending:
        if not p["ok"]:
            continue
        try:
            _import_one(os.path.join(config.UPLOADS_DIR, p["key"]), p["key"], admin, lim)
            added += 1
        except Exception:
            continue
    return {"scanned": scanned, "added": added}


@app.get("/api/admin/bans")
def list_bans(_: dict = Depends(require_admin)):
    """当前封禁列表（后台可观察防御状态）。"""
    now = time.time()
    return {"bans": [{"ip": ip, "reason": r,
                      "until": datetime.fromtimestamp(t, timezone.utc).isoformat()}
                     for ip, (t, r) in bans.items() if t > now]}


# ---------- 访问统计 ----------

def geo_lookup(ip: str) -> str:
    """IP 归属地：本机/局域网直接标注，公网查 ip-api.com 并缓存 7 天。"""
    if not ip or ip == "?":
        return "未知"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "未知"
    if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
        return "局域网 / 本机"
    cached = db.geo_get(ip)
    if cached:
        return cached
    try:
        url = (f"http://ip-api.com/json/{ip}"
               "?fields=status,country,regionName,city&lang=zh-CN")
        with urllib.request.urlopen(url, timeout=4) as r:
            d = json.loads(r.read(65536))
        if d.get("status") == "success":
            loc = " ".join(x for x in (d.get("country", ""), d.get("regionName", ""),
                                       d.get("city", "")) if x).strip() or "未知"
            db.geo_put(ip, loc)
            return loc
    except Exception:
        pass
    return "未知"


@app.get("/api/admin/stats")
def admin_stats(_: dict = Depends(require_admin)):
    """访问统计：最近 3 天 PV/UV、Top IP（含归属地）、热门接口、今日上传。"""
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    today_iso = midnight.astimezone(timezone.utc).isoformat(timespec="seconds")
    yday_iso = (midnight - timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds")
    top_ips = db.stats_top_ips(3, 20)
    for t in top_ips:
        t["geo"] = geo_lookup(t["ip"])
    return {
        "days": db.stats_days(3),
        "summary": db.stats_summary(3),
        "today": {"uploads": db.uploads_since(today_iso)["count"],
                  "uploadBytes": db.uploads_since(today_iso)["bytes"]},
        "yesterday": {"uploads": db.uploads_since(yday_iso)["count"]},
        "topIps": top_ips,
        "topPaths": db.stats_top_paths(3, 10),
        "library": {"count": db.get_conn().execute(
            "SELECT COUNT(*) AS n FROM images").fetchone()["n"]},
    }


# ---------- 通知测试 ----------
@app.post("/api/admin/notify/test")
def notify_test(_: dict = Depends(require_admin)):
    ok, err = notify.send("test", "这是一条来自 lolis-gallery 的测试通知 ✅")
    return {"ok": ok, "error": err}
