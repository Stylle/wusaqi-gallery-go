"""lolis-gallery 后端。

v2：权限门控（游客仅画廊）+ 流量防御（限流→webhook 告警→封禁）
    + 防爆破（鉴权失败计数封禁）+ 站点信息/外观全部后台可配。
设计约定：新增配置项只需在 db.DEFAULT_SETTINGS 加键 + 在 main.py 的
PUBLIC_SETTING_KEYS / SETTING_RULES 声明规则，前后端自动生效，方便后续扩展插件。
"""
import io
import json
import os
import secrets
import threading
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import compress, config, db, util

app = FastAPI(title="lolis-gallery", docs_url=None, redoc_url=None)

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


def fire_webhook(event: str, **fields) -> None:
    """异步尽力投递 webhook 告警（参考 cf-server-monitor 的通知形态）。"""
    url = db.get_settings().get("webhook_url") or ""
    if not url.startswith(("http://", "https://")):
        return
    payload = json.dumps({
        "event": event, "site": db.get_settings().get("site_title", "lolis-gallery"),
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields,
    }).encode()

    def _post():
        try:
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # 告警失败不影响主流程
    threading.Thread(target=_post, daemon=True).start()


# ---------- 限流中间件（随机图接口） ----------
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    ip = client_ip(request)
    banned, reason = is_banned(ip)
    if banned:
        return JSONResponse({"error": f"banned until {datetime.fromtimestamp(bans[ip][0], timezone.utc).isoformat()} ({reason})"},
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
    return await call_next(request)


# ---------- 鉴权（带防爆破） ----------
def client_ip_dep(request: Request) -> str:
    return client_ip(request)


def require_admin(request: Request, authorization: str = Header(default="")) -> str:
    ip = client_ip(request)
    banned, reason = is_banned(ip)
    if banned:
        raise HTTPException(429, f"banned ({reason})")

    token = authorization.removeprefix("Bearer ").strip()
    if token and secrets.compare_digest(token, config.ADMIN_TOKEN):
        _auth_fails.pop(ip, None)  # 成功即清零
        return token

    now = time.time()
    fails = [t for t in _auth_fails[ip] if now - t < 600]
    fails.append(now)
    _auth_fails[ip] = fails
    s = db.get_settings()
    max_fails = max(1, int(s.get("auth_max_fails", "10")))
    if len(fails) >= max_fails:
        ban_minutes = max(1, int(s.get("auth_ban_minutes", "10")))
        ban_ip(ip, ban_minutes, "auth brute force")
        _auth_fails.pop(ip, None)
        fire_webhook("auth_brute_force", ip=ip, fails=len(fails), ban_minutes=ban_minutes)
        raise HTTPException(429, f"too many failures, banned {ban_minutes}min")
    raise HTTPException(401, "invalid token")


# ---------- 序列化与上传 ----------
def item_json(row: dict) -> dict:
    return {
        "id": row["id"],
        "key": row["key"],
        "url": f"/files/{row['key']}",                       # 原始图
        "thumb": f"/thumbs/{row['key']}.webp",               # 缩略图
        "compressed": (f"/compressed/{row['c_key']}"          # 压缩版
                       if row.get("c_key") else None),
        "width": row["width"], "height": row["height"],
        "mimeType": row["mime"], "size": row["size"],
        "compressedSize": row.get("c_size"),
        "createdAt": row["created_at"],
    }


def save_one(data: bytes, filename: str) -> dict:
    """落盘原图 + 生成缩略图/压缩版 + 写库，返回图片记录。"""
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"exceeds {config.MAX_UPLOAD_MB}MB limit")

    info = compress.read_info(data)  # 解不开直接抛异常
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

    with Image.open(io.BytesIO(data)) as img:
        img.load()
        width, height = img.size

    compress.make_thumb(data, key)

    s = db.get_settings()
    c_rel = None
    c_meta = {}
    if info["format"] != "GIF":  # GIF 不压缩，保留动图
        try:
            c_rel, c_meta = compress.make_compressed(
                data, os.path.splitext(key)[0],
                fmt=s["comp_format"] if s["comp_format"] in config.COMP_FORMATS else "webp",
                quality=max(1, min(100, int(s["comp_quality"]))),
                max_width=max(0, int(s["comp_max_width"])))
        except Exception:
            c_rel, c_meta = None, {}

    row = {
        "id": util.short_id(), "key": key,
        "mime": info["mime"], "width": width, "height": height, "size": len(data),
        "c_key": c_rel, "c_mime": c_meta.get("c_mime"),
        "c_width": c_meta.get("c_width"), "c_height": c_meta.get("c_height"),
        "c_size": c_meta.get("c_size"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    db.insert_image(row)
    return item_json(row)


# ---------- 公开接口（游客可用：画廊浏览 + 站点信息） ----------
PUBLIC_SETTING_KEYS = ("site_title", "site_icon", "site_tags", "site_footer", "random_public")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/public/settings")
def public_settings():
    s = db.get_settings()
    return {k: s.get(k, "") for k in PUBLIC_SETTING_KEYS}


@app.get("/api/images")
def images(page: int = 1, limit: int = 24, sort: str = "latest"):
    page = max(1, page)
    limit = max(1, min(100, limit))
    items, total = db.list_images(page, limit, sort if sort in ("latest", "random") else "latest")
    return {"items": [item_json(r) for r in items],
            "page": page, "limit": limit, "total": total,
            "hasMore": page * limit < total}


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
    return require_admin(request, authorization)


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


# ---------- 管理接口 ----------

@app.post("/api/admin/verify")
def verify(_: str = Depends(require_admin)):
    return {"ok": True}


@app.get("/api/admin/settings")
def get_settings(_: str = Depends(require_admin)):
    return db.get_settings()


@app.put("/api/admin/settings")
def put_settings(patch: dict, _: str = Depends(require_admin)):
    """通用配置更新：只接受 DEFAULT_SETTINGS 里声明的键，按类型夹紧。"""
    defaults = db.DEFAULT_SETTINGS
    clean = {}
    for k, v in (patch or {}).items():
        if k not in defaults:
            continue
        if k in ("comp_format",):
            if v in config.COMP_FORMATS:
                clean[k] = v
        elif k in ("comp_quality",):
            clean[k] = max(1, min(100, int(v)))
        elif k in ("comp_max_width", "rate_limit", "rate_ban_minutes",
                   "auth_max_fails", "auth_ban_minutes"):
            clean[k] = max(0, int(v))
        elif k in ("random_public",):
            clean[k] = "1" if (v is True or str(v).lower() in ("1", "true", "on")) else "0"
        else:  # 文本类：site_title / site_icon / site_tags / site_footer / webhook_url
            clean[k] = str(v).strip()[:500]
    if not clean:
        raise HTTPException(400, "no valid fields")
    db.update_settings(clean)
    return db.get_settings()


@app.post("/api/admin/upload")
def upload(request: Request, files: list[UploadFile] = File(...),
           _: str = Depends(require_admin)):
    results = []
    for f in files:
        name = f.filename or "unnamed"
        try:
            data = f.file.read()
            results.append({"name": name, "ok": True, "item": save_one(data, name)})
        except Exception as e:
            results.append({"name": name, "ok": False, "error": str(e)})
        finally:
            f.file.close()
    return {"results": results}


@app.post("/api/admin/reindex")
def reindex(_: str = Depends(require_admin)):
    """扫描 uploads 目录，把缺记录的图片补进索引（顺带补缩略图/压缩版）。"""
    added, scanned = 0, 0
    known = db.all_keys()
    for root, _dirs, names in os.walk(config.UPLOADS_DIR):
        for name in names:
            scanned += 1
            full = os.path.join(root, name)
            rel = os.path.relpath(full, config.UPLOADS_DIR).replace("\\", "/")
            if rel in known:
                continue
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
                save_one(data, name)
                added += 1
            except Exception:
                continue
    return {"scanned": scanned, "added": added}


@app.get("/api/admin/bans")
def list_bans(_: str = Depends(require_admin)):
    """当前封禁列表（后台可观察防御状态）。"""
    now = time.time()
    return {"bans": [{"ip": ip, "reason": r, "until": datetime.fromtimestamp(t, timezone.utc).isoformat()}
                     for ip, (t, r) in bans.items() if t > now]}
