"""图片处理：信息提取、缩略图、可配置压缩版。

流量策略核心：上传时一次性生成两种版本——
  thumbs/      画廊网格用小图（固定 webp 600px）
  compressed/  对外分享用压缩版（格式/质量/最大宽度后台可调）
原版仅保留在 files/，需要时才取，最大程度省机器流量。
"""
import io
import os

from PIL import Image, ImageOps

from . import config

# 输出格式 -> (Pillow format, 扩展名, mime)
FORMATS = {
    "webp": ("WEBP", "webp", "image/webp"),
    "jpeg": ("JPEG", "jpg", "image/jpeg"),
    "png": ("PNG", "png", "image/png"),
}


def read_info(data: bytes) -> dict:
    """提取宽高与 mime，同时校验是否为可解码图片。"""
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        fmt = (img.format or "").upper()
    mime = Image.MIME.get(fmt, "application/octet-stream")
    # PNG/GIF 之类取首帧信息即可，load 已完成
    return {"mime": mime, "format": fmt}


def _normalize(img: Image.Image, fmt: str) -> Image.Image:
    # JPEG 不支持 alpha，webp/png 保留
    if fmt == "JPEG":
        img = img.convert("RGB")
    # 带方向 EXIF 的 jpeg 转正
    if fmt in ("JPEG", "WEBP"):
        img = ImageOps.exif_transpose(img)
    return img


def make_thumb(data: bytes, rel_key: str) -> str:
    """生成缩略图到 thumbs/<rel_key>.webp，返回相对路径。"""
    out_path = os.path.join(config.THUMBS_DIR, rel_key + ".webp")
    if os.path.exists(out_path):
        return rel_key + ".webp"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((config.THUMB_WIDTH, config.THUMB_WIDTH * 8), Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.save(out_path, "WEBP", quality=config.THUMB_QUALITY, method=4)
    return rel_key + ".webp"


def make_compressed(data: bytes, rel_key_no_ext: str, fmt: str,
                    quality: int, max_width: int) -> tuple[str, dict]:
    """按后台设置生成压缩版到 compressed/，返回 (相对路径, 元信息)。"""
    pillow_fmt, ext, mime = FORMATS[fmt]
    out_path = os.path.join(config.COMPRESSED_DIR, rel_key_no_ext + "." + ext)
    rel = rel_key_no_ext + "." + ext
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with Image.open(io.BytesIO(data)) as img:
        img = _normalize(img, pillow_fmt)
        if max_width and img.width > max_width:
            h = max(1, round(img.height * max_width / img.width))
            img = img.resize((max_width, h), Image.LANCZOS)
        if pillow_fmt == "PNG":
            img.save(out_path, pillow_fmt, optimize=True)
        else:
            img.save(out_path, pillow_fmt, quality=quality, optimize=True, method=4)

    return rel, {
        "c_mime": mime,
        "c_width": img.width,
        "c_height": img.height,
        "c_size": os.path.getsize(out_path),
    }
