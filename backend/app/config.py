"""运行时配置，全部可用环境变量覆盖。"""
import os


def _flag(name: str, default: bool) -> bool:
    """环境变量开关：1/true/yes/on 为真，0/false/no/off 为假，未设置用默认值。"""
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "y", "t")


DATA_DIR = os.environ.get("DATA_DIR", "/data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")      # 原图
THUMBS_DIR = os.path.join(DATA_DIR, "thumbs")        # 缩略图（画廊网格用，webp 固定）
COMPRESSED_DIR = os.path.join(DATA_DIR, "compressed")  # 压缩版（对外分享用，格式可配置）
DB_PATH = os.path.join(DATA_DIR, "metadata.db")

# ---------- 管理员账号 ----------
# 首次启动时用它播种管理员；库已存在则不覆盖（改密码走后台或 ADMIN_SYNC）
ADMIN_USERNAME = (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"
# 首次启动的密码；库已存在时不覆盖（改密码走后台「修改密码」或 ADMIN_SYNC）
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or "changeme"

# 启动时把库里的管理员用户名/密码强制同步为上面两个环境变量（忘记密码时的救援开关）
ADMIN_SYNC = _flag("ADMIN_SYNC", False)

# 随机图接口每 IP 每分钟限流次数，0 = 关闭
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "120"))

# 缩略图固定参数（画廊网格用，足够小）
THUMB_WIDTH = 600
THUMB_QUALITY = 78

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif", "avif", "bmp"}

# 压缩设置的可选范围（后台可调）
COMP_FORMATS = {"webp", "jpeg", "png"}
