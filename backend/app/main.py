"""lolis-gallery 后端：复刻 lolis.im 的画廊 + 随机图 API，双 URL 流量优化策略。"""
import io
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
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


# ---------- 限流（只挡 /api/random*，省流量第一道闸） ----------
_buckets: dict[str, list[float]] = defaultdict(list)


@app.middleware("http")
async def rate_limit(request, call_next):
    if config.RATE_LIMIT > 0 and request.url.path.startswith("/api/random"):
        ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client else "?")
        now = time.time()
        window = [t for t in _buckets[ip] if now - t < 60]
        if len(window) >= config.RATE_LIMIT:
            return JSONResponse({"error": "rate limited"}, status_code=429)
        window.append(now)
        _buckets[ip] = window
        if len(_buckets) > 10000:  # 防内存膨胀
            _buckets.clear()
    return await call_next(request)


def require_admin(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not secrets.compare_digest(token, config.ADMIN_TOKEN):
        raise HTTPException(401, "invalid token")
    return token


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

    thumb_rel = compress.make_thumb(data, key)

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


# ---------- 公开接口 ----------

@app.get("/api/health")
def health():
    return {"ok": True}


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


@app.get("/api/random")
def random_json(variant: str = "compressed", redirect: bool = False):
    row, path = _random_row(variant)
    if redirect:
        return RedirectResponse(path, status_code=302)
    return item_json(row)


@app.get("/api/random/image")
def random_image(variant: str = "compressed"):
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
    clean = {}
    if patch.get("format") in config.COMP_FORMATS:
        clean["comp_format"] = patch["format"]
    if "quality" in patch:
        clean["comp_quality"] = max(1, min(100, int(patch["quality"])))
    if "max_width" in patch:
        clean["comp_max_width"] = max(0, int(patch["max_width"]))
    if not clean:
        raise HTTPException(400, "no valid fields")
    db.update_settings(clean)
    return db.get_settings()


@app.post("/api/admin/upload")
def upload(files: list[UploadFile] = File(...), _: str = Depends(require_admin)):
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
