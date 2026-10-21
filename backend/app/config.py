"""运行时配置，全部可用环境变量覆盖。"""
import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")      # 原图
THUMBS_DIR = os.path.join(DATA_DIR, "thumbs")        # 缩略图（画廊网格用，webp 固定）
COMPRESSED_DIR = os.path.join(DATA_DIR, "compressed")  # 压缩版（对外分享用，格式可配置）
DB_PATH = os.path.join(DATA_DIR, "metadata.db")

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "changeme")

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))

# 随机图接口每 IP 每分钟限流次数，0 = 关闭
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "120"))

# 缩略图固定参数（画廊网格用，足够小）
THUMB_WIDTH = 600
THUMB_QUALITY = 78

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif", "avif", "bmp"}

# 压缩设置的可选范围（后台可调）
COMP_FORMATS = {"webp", "jpeg", "png"}
