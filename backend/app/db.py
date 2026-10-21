"""SQLite 元数据存取（同步，FastAPI 线程池执行）。"""
import sqlite3
import threading

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id          TEXT PRIMARY KEY,
    key         TEXT UNIQUE NOT NULL,   -- 相对路径 uploads/YYYY/MM/DD/<ts>-<rand>.<ext>
    mime        TEXT NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    size        INTEGER NOT NULL,
    c_key       TEXT,                   -- 压缩版相对路径，可为空（非图片/生成失败）
    c_mime      TEXT,
    c_width     INTEGER,
    c_height    INTEGER,
    c_size      INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_created ON images(created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""

# 全部可配置项与默认值（后台可调，flat 键值对，便于扩展新配置项/插件）
DEFAULT_SETTINGS = {
    # 站点信息
    "site_title": "lolis-gallery",
    "site_icon": "",          # favicon URL 或 emoji，空 = 默认
    "site_tags": "画廊,随机图,自部署",   # 首页展示标签，逗号分隔
    "site_footer": "Powered by lolis-gallery",
    # 图片压缩
    "comp_format": "webp",    # webp | jpeg | png
    "comp_quality": "80",     # 1-100
    "comp_max_width": "2560", # 0 = 不缩放
    # 权限
    "random_public": "0",     # 1 = 未登录也可用随机图 API（外链场景）
    # 流量防御
    "rate_limit": "120",      # 每 IP 每分钟随机图请求上限，0 = 关闭
    "rate_ban_minutes": "10", # 超限封禁时长
    "webhook_url": "",        # 超限/爆破告警 webhook（POST JSON）
    # 安全（防爆破）
    "auth_max_fails": "10",   # 累计鉴权失败次数阈值
    "auth_ban_minutes": "10", # 触发后封禁时长
}


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            _conn.execute("INSERT OR IGNORE INTO settings(k, v) VALUES (?, ?)", (k, v))
        _conn.commit()
    return _conn


def get_settings() -> dict:
    rows = get_conn().execute("SELECT k, v FROM settings").fetchall()
    return {r["k"]: r["v"] for r in rows}


def update_settings(patch: dict) -> None:
    with _lock:
        conn = get_conn()
        for k, v in patch.items():
            conn.execute(
                "INSERT INTO settings(k, v) VALUES (?, ?) "
                "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, str(v)))
        conn.commit()


def insert_image(row: dict) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            """INSERT INTO images
               (id, key, mime, width, height, size,
                c_key, c_mime, c_width, c_height, c_size, created_at)
               VALUES (:id, :key, :mime, :width, :height, :size,
                       :c_key, :c_mime, :c_width, :c_height, :c_size, :created_at)""",
            row)
        conn.commit()


def key_exists(key: str) -> bool:
    return get_conn().execute(
        "SELECT 1 FROM images WHERE key = ?", (key,)).fetchone() is not None


def list_images(page: int, limit: int, sort: str) -> tuple[list, int]:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) AS n FROM images").fetchone()["n"]
    order = "RANDOM()" if sort == "random" else "created_at DESC, rowid DESC"
    rows = conn.execute(
        f"SELECT * FROM images ORDER BY {order} LIMIT ? OFFSET ?",
        (limit, (page - 1) * limit)).fetchall()
    return [dict(r) for r in rows], total


def random_image() -> dict | None:
    row = get_conn().execute(
        "SELECT * FROM images ORDER BY RANDOM() LIMIT 1").fetchone()
    return dict(row) if row else None


def all_keys() -> set[str]:
    rows = get_conn().execute("SELECT key FROM images").fetchall()
    return {r["key"] for r in rows}
