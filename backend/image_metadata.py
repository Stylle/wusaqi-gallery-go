"""Remove identifying metadata before an upload becomes a gallery original.

JPEG/PNG/WebP/GIF are filtered without recompressing image data. Only image
structure, animation controls and a freshly constructed orientation survive.
Unknown metadata and bytes after the image terminator are discarded.
"""
import os
import struct
import tempfile
import zlib


def exact(src, count):
    value = src.read(count)
    if len(value) != count:
        raise ValueError("图片结构不完整，无法安全清除元数据")
    return value


def transfer(src, out, count):
    while count:
        block = exact(src, min(count, 65536))
        if out is not None:
            out.write(block)
        count -= len(block)


def orientation_exif(src):
    from PIL import Image
    orientation = src.getexif().get(274, 1)
    if orientation in range(2, 9):
        clean = Image.Exif()
        clean[274] = orientation
        return clean.tobytes()
    return b""


def clean_jpeg(src, out, exif):
    if exact(src, 2) != b"\xff\xd8":
        raise ValueError("无效 JPEG")
    out.write(b"\xff\xd8")
    if exif:
        out.write(b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif)
    scan = False
    while True:
        if scan:
            block = src.peek(65536)
            if not block:
                raise ValueError("JPEG 缺少结束标记")
            pos = block.find(b"\xff")
            if pos != 0:
                transfer(src, out, len(block) if pos < 0 else pos)
                continue
        if exact(src, 1) != b"\xff":
            raise ValueError("无效 JPEG 标记")
        marker = exact(src, 1)
        while marker == b"\xff":
            marker = exact(src, 1)
        value = marker[0]
        if scan and (value == 0 or 0xD0 <= value <= 0xD7):
            out.write(b"\xff" + marker)
            continue
        if value == 0xD9:
            out.write(b"\xff\xd9")
            return
        if value == 1:
            out.write(b"\xff" + marker)
            continue
        if value == 0 or value == 0xD8 or 0xD0 <= value <= 0xD7:
            raise ValueError("无效 JPEG 结构")
        length = exact(src, 2)
        size = struct.unpack(">H", length)[0]
        if size < 2:
            raise ValueError("无效 JPEG 数据段")
        payload = exact(src, size - 2)
        metadata = 0xE0 <= value <= 0xEF or value == 0xFE
        # Adobe APP14's fixed 12-byte transform is required for CMYK colors;
        # arbitrary APP14 payloads and all other application markers are removed.
        adobe = value == 0xEE and len(payload) == 12 and payload.startswith(b"Adobe")
        if not metadata or adobe:
            out.write(b"\xff" + marker + length + payload)
        scan = value == 0xDA or (scan and value == 0xDC)


def png_chunk(out, kind, payload):
    out.write(struct.pack(">I", len(payload)) + kind + payload)
    out.write(struct.pack(">I", zlib.crc32(kind + payload)))


def clean_png(src, out, exif):
    signature = b"\x89PNG\r\n\x1a\n"
    if exact(src, 8) != signature:
        raise ValueError("无效 PNG")
    out.write(signature)
    allowed = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND", b"acTL", b"fcTL", b"fdAT", b"gAMA", b"cHRM", b"sRGB", b"sBIT"}
    while True:
        header = exact(src, 8)
        length, kind = struct.unpack(">I4s", header)
        if length > 0x7FFFFFFF:
            raise ValueError("无效 PNG 数据块")
        keep = kind in allowed
        if keep:
            out.write(header)
        transfer(src, out if keep else None, length + 4)
        if kind == b"IHDR" and exif:
            png_chunk(out, b"eXIf", exif[6:])
        if kind == b"IEND":
            return


def webp_chunk(out, kind, payload):
    out.write(kind + struct.pack("<I", len(payload)) + payload)
    if len(payload) % 2:
        out.write(b"\0")


def clean_webp(src, out, exif):
    header = exact(src, 12)
    if header[:4] != b"RIFF" or header[8:] != b"WEBP":
        raise ValueError("无效 WebP")
    end = struct.unpack("<I", header[4:8])[0] + 8
    out.write(b"RIFF\0\0\0\0WEBP")
    while src.tell() < end:
        kind, length = struct.unpack("<4sI", exact(src, 8))
        if src.tell() + length + length % 2 > end:
            raise ValueError("无效 WebP 数据块")
        if kind == b"VP8X":
            value = bytearray(exact(src, length))
            if len(value) != 10:
                raise ValueError("无效 WebP 扩展头")
            value[0] = (value[0] & ~0x2C) | (0x08 if exif else 0)
            webp_chunk(out, kind, value)
        elif kind == b"ANMF":
            if length < 16:
                raise ValueError("无效 WebP 动画帧长度")
            start = out.tell()
            out.write(b"ANMF\0\0\0\0" + exact(src, 16))
            frame_end = src.tell() + length - 16
            while src.tell() < frame_end:
                sub_kind, sub_size = struct.unpack("<4sI", exact(src, 8))
                if src.tell() + sub_size + sub_size % 2 > frame_end:
                    raise ValueError("无效 WebP 动画帧")
                keep = sub_kind in (b"ALPH", b"VP8 ", b"VP8L")
                if keep:
                    out.write(sub_kind + struct.pack("<I", sub_size))
                transfer(src, out if keep else None, sub_size + sub_size % 2)
            size = out.tell() - start - 8
            out.seek(start + 4); out.write(struct.pack("<I", size)); out.seek(0, 2)
        elif kind in (b"VP8 ", b"VP8L", b"ALPH", b"ANIM"):
            out.write(kind + struct.pack("<I", length))
            transfer(src, out, length)
        else:
            transfer(src, None, length)
        if length % 2:
            exact(src, 1)
            if kind in (b"VP8 ", b"VP8L", b"ALPH", b"ANIM"):
                out.write(b"\0")
    if src.tell() != end:
        raise ValueError("无效 WebP 长度")
    if exif:
        webp_chunk(out, b"EXIF", exif)
    length = out.tell() - 8
    out.seek(4); out.write(struct.pack("<I", length)); out.seek(0, 2)


def gif_blocks(src, out):
    while True:
        size = exact(src, 1)
        if out is not None:
            out.write(size)
        if size == b"\0":
            return
        transfer(src, out, size[0])


def clean_gif(src, out, _exif):
    header = exact(src, 13)
    if header[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("无效 GIF")
    out.write(header)
    if header[10] & 0x80:
        transfer(src, out, 3 * (2 << (header[10] & 7)))
    while True:
        kind = exact(src, 1)
        if kind == b";":
            out.write(kind)
            return
        if kind == b",":
            desc = exact(src, 9)
            out.write(kind + desc)
            if desc[8] & 0x80:
                transfer(src, out, 3 * (2 << (desc[8] & 7)))
            out.write(exact(src, 1))
            gif_blocks(src, out)
        elif kind == b"!":
            label = exact(src, 1)
            if label == b"\xf9":
                size = exact(src, 1)
                if size != b"\x04":
                    raise ValueError("无效 GIF 动画控制块")
                payload = exact(src, 5)
                if payload[-1] != 0:
                    raise ValueError("无效 GIF 控制块结束符")
                out.write(kind + label + size + payload)
            elif label == b"\xff":
                size = exact(src, 1)[0]
                app = exact(src, size)
                size = exact(src, 1)[0]
                value = exact(src, size)
                if app in (b"NETSCAPE2.0", b"ANIMEXTS1.0") and len(value) == 3 and value[0] == 1:
                    out.write(b"!\xff\x0bNETSCAPE2.0\x03" + value + b"\0")
                if size:
                    gif_blocks(src, None)
            else:
                gif_blocks(src, None)
        else:
            raise ValueError("无效 GIF 图片块")


class DiskFrame:
    """Pillow's sequence encoder can read one clean frame without retaining all pixels."""
    def __init__(self, path, mode, size):
        self.path, self.mode, self.size = path, mode, size

    def seek(self, frame):
        if frame != 0:
            raise EOFError

    def tell(self):
        return 0

    def tobytes(self, *args):
        from PIL import Image
        with Image.open(self.path) as frame:
            return frame.tobytes(*args)


def clean_avif(src, dest):
    from PIL import Image, ImageOps
    # libavif cannot reliably encode a rotated sequence. Apply orientation to
    # pixels first, then pass no EXIF at all. Spool frames to bounded-memory disk
    # images instead of keeping an entire animation's decoded pixels in a list.
    with tempfile.TemporaryDirectory(prefix='.avif-clean-', dir=os.path.dirname(dest)) as staging:
        frames, durations = [], []
        for index in range(getattr(src, "n_frames", 1)):
            src.seek(index); src.load()
            durations.append(src.info.get("duration", 0))
            frame = ImageOps.exif_transpose(src)
            frame.info.clear()
            path = os.path.join(staging, str(index)+'.png')
            frame.save(path, "PNG", exif=b"", icc_profile=b"")
            frames.append(DiskFrame(path, frame.mode, frame.size))
            frame.close()
        with Image.open(frames[0].path) as first:
            first.save(dest, "AVIF", save_all=len(frames) > 1,
                       append_images=frames[1:], duration=durations, quality=100,
                       subsampling="4:4:4", max_threads=1, speed=8,
                       exif=b"", xmp=b"", icc_profile=b"")
        return frames[0].size


def sanitize(src, path, dest):
    """Write a separate atomic clean original, leaving resumable input intact."""
    from PIL import Image
    exif = orientation_exif(src)
    fd, temp = tempfile.mkstemp(prefix=".clean-", dir=os.path.dirname(dest))
    os.close(fd)
    try:
        fmt = src.format.upper()
        expected_size = src.size
        cleaner = {"JPEG": clean_jpeg, "PNG": clean_png, "WEBP": clean_webp, "GIF": clean_gif}.get(fmt)
        if cleaner:
            with open(path, "rb") as original, open(temp, "w+b") as out:
                cleaner(original, out, exif)
        elif fmt == "BMP":
            # BMP may contain embedded V5 profiles; a fresh pixel image omits them.
            clean = src.copy()
            clean.info.clear()
            clean.save(temp, "BMP")
            clean.close()
        elif fmt == "AVIF":
            expected_size = clean_avif(src, temp)
        else:
            raise ValueError("此图片格式尚不能安全清除个人信息")
        with Image.open(temp) as check:
            if check.format != fmt or check.size != expected_size or getattr(check, "n_frames", 1) != getattr(src, "n_frames", 1):
                raise ValueError("清除个人信息后的图片校验失败")
            if set(check.getexif()) - {274}:
                raise ValueError("图片仍包含个人 EXIF 信息")
            if any(check.info.get(k) for k in ("xmp", "XML:com.adobe.xmp", "comment", "icc_profile")):
                raise ValueError("图片仍包含来源元数据")
        with open(temp, "r+b") as ready:
            ready.flush()
            os.fsync(ready.fileno())
        os.chmod(temp, os.stat(path).st_mode & 0o777)
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
        src.seek(0)
    return os.path.getsize(dest)
