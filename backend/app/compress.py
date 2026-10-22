"""图片处理：信息提取、缩略图、可配置压缩版。

流量策略核心：上传时一次性生成两种版本——
  thumbs/      画廊网格用小图（固定 webp 600px）
  compressed/  对外分享用压缩版（格式/质量/最大宽度由压缩方案决定）
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

# 支持的输入格式（Pillow 实际能解就行，这里用于后台展示与前端 accept）
INPUT_FORMATS = [
    {"ext": "jpg / jpeg", "label": "JPG / JPEG", "recommend": True,
     "note": "照片首选：体积小、兼容性最好，压缩后几乎无感"},
    {"ext": "png", "label": "PNG", "recommend": True,
     "note": "截图 / 需要透明背景时用；无损但原图体积偏大"},
    {"ext": "webp", "label": "WebP", "recommend": True,
     "note": "已有素材推荐：同画质体积最小，所有现代浏览器都支持"},
    {"ext": "avif", "label": "AVIF", "recommend": False,
     "note": "支持（取决于 Pillow 构建）；部分老浏览器打不开"},
    {"ext": "gif", "label": "GIF", "recommend": False,
     "note": "支持，但动图不生成压缩版（保留原图），流量偏大"},
    {"ext": "bmp", "label": "BMP", "recommend": False,
     "note": "不推荐：未压缩位图，体积可能是 JPG 的 10 倍以上"},
]


def read_info(data: bytes) -> dict:
    """只读文件头拿宽高/格式（不整图解码，省 CPU），解不开会抛异常。"""
    with Image.open(io.BytesIO(data)) as img:
        fmt = (img.format or "").upper()
        width, height = img.size
        frames = getattr(img, "n_frames", 1)
    return {"mime": Image.MIME.get(fmt, "application/octet-stream"), "format": fmt,
            "width": width, "height": height, "frames": frames}


def _normalize(img: Image.Image, fmt: str) -> Image.Image:
    # JPEG 不支持 alpha，webp/png 保留
    if fmt == "JPEG":
        img = img.convert("RGB")
    # 带方向 EXIF 的 jpeg 转正
    if fmt in ("JPEG", "WEBP"):
        img = ImageOps.exif_transpose(img)
    return img


def make_thumb(data: bytes, rel_key: str, quality: int = None, method: int = None) -> str:
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
        img.save(out_path, "WEBP", quality=quality or config.THUMB_QUALITY,
                 method=method if method is not None else 4)
    return rel_key + ".webp"


def make_compressed(data: bytes, rel_key_no_ext: str, fmt: str,
                    quality: int, max_width: int, method: int = 4) -> tuple[str, dict]:
    """按当前压缩方案生成压缩版到 compressed/，返回 (相对路径, 元信息)。"""
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
            img.save(out_path, pillow_fmt, quality=quality, optimize=True, method=method)
        size = (img.width, img.height)

    return rel, {
        "c_mime": mime,
        "c_width": size[0],
        "c_height": size[1],
        "c_size": os.path.getsize(out_path),
    }
