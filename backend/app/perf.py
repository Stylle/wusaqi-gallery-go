"""压缩方案（性能档位）：按机器能力自动挑参数，后台也可手动指定。

方案 B 的思路：
  - 启动时探测 CPU 核数与可用内存（容器里会读 cgroup 限额，不受宿主机干扰）；
  - 落到 tiny / small / normal 三档，分别给出质量、最大宽度、webp 编码强度、
    解码像素上限、压缩并发数；
  - 后台 `comp_profile` 可选 auto（默认，跟随探测）/ tiny / small / normal / custom；
  - custom 时用 comp_quality / comp_max_width / comp_method / comp_max_pixels /
    comp_concurrency 显式覆盖；
  - 所有压缩/缩略图生成共用一个可调并发槽（低配机器 = 1），避免大图并发把内存打爆。
"""
import os
import threading
from contextlib import contextmanager

# 档位参数。max_pixels 单位是「百万像素」（解码前拦截，防 OOM）；
# method 为 webp 编码强度（0 最快最省 CPU，6 最慢最小），jpeg/png 忽略该值。
PROFILES = {
    "tiny": {
        "label": "轻量方案",
        "desc": "1 核 / 1GB 级：低配 VPS、软路由、树莓派",
        "quality": 72, "max_width": 1600, "method": 2, "max_pixels": 40,
        "concurrency": 1, "thumb_quality": 70, "thumb_method": 2,
    },
    "small": {
        "label": "均衡方案",
        "desc": "2 核 / 2~3GB：入门 VPS、家用小主机",
        "quality": 78, "max_width": 2048, "method": 4, "max_pixels": 60,
        "concurrency": 1, "thumb_quality": 76, "thumb_method": 4,
    },
    "normal": {
        "label": "标准方案",
        "desc": "4 核 / 4GB+：NAS、独立服务器、本地电脑",
        "quality": 82, "max_width": 2560, "method": 6, "max_pixels": 120,
        "concurrency": 2, "thumb_quality": 78, "thumb_method": 4,
    },
}

MODES = ("auto", "custom", *PROFILES)


def _read_int(path: str, scale: int = 1) -> int | None:
    try:
        with open(path, "r") as fh:
            raw = fh.read().strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw) * scale


def _cpu_cores() -> int:
    """可用核数：cgroup 配额优先（容器里 os.cpu_count() 是宿主机的）。"""
    n = os.cpu_count() or 1
    # cgroup v2: "200000 100000" → 2 核；"max 100000" → 不限制
    try:
        with open("/sys/fs/cgroup/cpu.max", "r") as fh:
            parts = fh.read().split()
        if len(parts) == 2 and parts[0] != "max" and int(parts[1]) > 0:
            n = min(n, max(1, round(int(parts[0]) / int(parts[1]))))
    except (OSError, ValueError):
        pass
    # cgroup v1: quota / period
    try:
        quota = _read_int("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period = _read_int("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if quota and quota > 0 and period and period > 0:
            n = min(n, max(1, round(quota / period)))
    except (OSError, ValueError):
        pass
    return max(1, n)


def _windows_mem_mb() -> int | None:
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MemoryStatus()
        st.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys // (1024 * 1024))
    except Exception:
        pass
    return None


def _mem_total_mb() -> int | None:
    """总内存：/proc/meminfo 与 cgroup 限额取更小值（容器限额才是真实可用量）。"""
    total = None
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError, IndexError):
        total = None

    for path in ("/sys/fs/cgroup/memory.max",
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        mb = _read_int(path)
        if mb and mb // (1024 * 1024) < 1024 * 1024:      # 排除 max / 天文数字
            mb = mb // (1024 * 1024)
            total = mb if total is None else min(total, mb)

    return total if total is not None else _windows_mem_mb()


def _pick(cores: int | None, mem_mb: int | None) -> str:
    if (cores is not None and cores <= 1) or (mem_mb is not None and mem_mb <= 1536):
        return "tiny"
    if (cores is not None and cores <= 2) or (mem_mb is not None and mem_mb <= 3072):
        return "small"
    return "normal"


_det_cache: dict | None = None
_det_lock = threading.Lock()


def detect(force: bool = False) -> dict:
    global _det_cache
    with _det_lock:
        if _det_cache is None or force:
            cores, mem = _cpu_cores(), _mem_total_mb()
            _det_cache = {"cores": cores, "memMb": mem, "profile": _pick(cores, mem)}
        return dict(_det_cache)


def _clamp(v, lo: int, hi: int, default: int) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def effective(settings: dict | None = None) -> dict:
    """当前生效的压缩参数（含自动探测结果，供后台展示）。"""
    if settings is None:
        from . import db
        settings = db.get_settings()
    det = detect()

    mode = str(settings.get("comp_profile") or "auto").strip().lower()
    if mode not in MODES:
        mode = "auto"
    name = det["profile"] if mode == "auto" else mode
    auto = PROFILES[det["profile"]]
    base = PROFILES.get(name, auto)

    fmt = str(settings.get("comp_format") or "webp").strip().lower()
    if fmt not in ("webp", "jpeg", "png"):
        fmt = "webp"

    if name == "custom":
        quality = _clamp(settings.get("comp_quality"), 1, 100, auto["quality"])
        max_width = _clamp(settings.get("comp_max_width"), 0, 12000, auto["max_width"])
        method = _clamp(settings.get("comp_method"), 0, 6, auto["method"])
        max_pixels = _clamp(settings.get("comp_max_pixels"), 0, 500, auto["max_pixels"])
        concurrency = _clamp(settings.get("comp_concurrency"), 1, 8, auto["concurrency"])
    else:
        quality, max_width = base["quality"], base["max_width"]
        method, max_pixels = base["method"], base["max_pixels"]
        concurrency = base["concurrency"]

    return {
        "mode": mode,
        "profile": name,
        "autoProfile": det["profile"],
        "label": base["label"],
        "detected": {"cores": det["cores"], "memMb": det["memMb"]},
        "format": fmt,
        "quality": quality,
        "maxWidth": max_width,
        "method": method,
        "maxPixels": max_pixels,
        "concurrency": concurrency,
        "thumbQuality": base["thumb_quality"],
        "thumbMethod": base["thumb_method"],
    }


class _SlotPool:
    """可动态改容量的并发槽（压缩是 CPU/内存大户，必须限并发）。"""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._limit = 1
        self._active = 0

    def configure(self, limit: int) -> None:
        with self._cv:
            self._limit = max(1, int(limit or 1))
            self._cv.notify_all()

    @property
    def state(self) -> dict:
        with self._cv:
            return {"limit": self._limit, "active": self._active}

    @contextmanager
    def slot(self, limit: int | None = None):
        with self._cv:
            if limit:
                self._limit = max(1, int(limit))
            while self._active >= self._limit:
                self._cv.wait()
            self._active += 1
        try:
            yield
        finally:
            with self._cv:
                self._active -= 1
                self._cv.notify()


pool = _SlotPool()


def describe() -> str:
    """一行日志摘要。"""
    eff = effective()
    mem = eff["detected"]["memMb"]
    mem_s = f"{mem / 1024:.1f}GB" if mem else "未知内存"
    return (f"压缩方案 {eff['label']}({eff['profile']}"
            f"{'/自动' if eff['mode'] == 'auto' else ''} · {eff['format']} "
            f"q{eff['quality']} {eff['maxWidth'] or '不缩放'}px · 并发 {eff['concurrency']}"
            f" · 探测 {eff['detected']['cores']}核/{mem_s})")
