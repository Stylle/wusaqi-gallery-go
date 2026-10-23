"""One image job per process; no HTTP server or persistent Python runtime.

The Go service sends a small JSON job on stdin. Images stay on disk, and only
metadata is returned on stdout. Exiting returns all Pillow/native allocations
to the OS, including memory retained by image codecs after a large upload.
"""
import json
import os
import sys


def run(job):
    from PIL import Image, ImageOps
    path = job["path"]
    # The application validates pixel counts before decoding, including custom
    # limits above Pillow's default warning threshold.
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as src:
        fmt = (src.format or "").upper()
        width, height = src.size
        info = {"width": width, "height": height,
                "mime": Image.MIME.get(fmt, "application/octet-stream"),
                "format": fmt, "frames": getattr(src, "n_frames", 1)}
        if job.get("op") == "info":
            return info
        lim = job["limits"]
        if lim["maxPixels"] and width * height > lim["maxPixels"] * 1_000_000:
            raise ValueError(f"图片分辨率 {width}×{height} 超过当前压缩方案上限 {lim['maxPixels']} MP")
        img = ImageOps.exif_transpose(src)
        # Original image metadata stays unchanged for URL/database compatibility.
        thumb = job.get("thumb")
        if thumb and not os.path.exists(thumb):
            os.makedirs(os.path.dirname(thumb), exist_ok=True)
            small = img.copy()
            small.thumbnail((600, 4800), Image.Resampling.LANCZOS)
            if small.mode not in ("RGB", "RGBA"):
                small = small.convert("RGB")
            small.save(thumb, "WEBP", quality=lim["thumbQuality"], method=lim["thumbMethod"])
            small.close()
        dest = job.get("compressed")
        if dest and fmt != "GIF":
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            out_fmt = {"webp": "WEBP", "jpeg": "JPEG", "png": "PNG"}[lim["format"]]
            if out_fmt == "JPEG" or img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            if lim["maxWidth"] and img.width > lim["maxWidth"]:
                img = img.resize((lim["maxWidth"], max(1, round(img.height * lim["maxWidth"] / img.width))), Image.Resampling.LANCZOS)
            kwargs = {"optimize": True}
            if out_fmt != "PNG":
                kwargs.update(quality=lim["quality"], method=lim["method"])
            img.save(dest, out_fmt, **kwargs)
            info.update(c_width=img.width, c_height=img.height,
                        c_size=os.path.getsize(dest),
                        c_mime={"webp": "image/webp", "jpeg": "image/jpeg", "png": "image/png"}[lim["format"]])
        img.close()
        return info


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "result": run(json.load(sys.stdin))}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
