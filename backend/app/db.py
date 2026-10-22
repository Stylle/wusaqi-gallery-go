"""SQLite 元数据存取（同步，FastAPI 线程池执行）。

v3：加用户体系（users/sessions）+ 图片归属与标签（images.owner_id/tag/orig_name）。
迁移策略：CREATE TABLE IF NOT EXISTS 建新表；老 images 表用 PRAGMA 检测后 ALTER TABLE 补列。
"""
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from . import config, util

_lock = threading.Lock()          # 写操作串行化（避免 SQLITE_BUSY）
_init_lock = threading.Lock()     # 建表/迁移只跑一次
_schema_ready = False
_local = threading.local()        # 每线程一条连接：绝不能跨线程共用 Connection
_conns: list = []                 # 已建立的连接（恢复备份时统一关闭）
_conns_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id          TEXT PRIMARY KEY,
    key         TEXT UNIQUE NOT NULL,   -- 相对路径 uploads/YYYYMMDD/<ts>-<rand>.<ext>
    owner_id    TEXT,                   -- 上传者 users.id
    tag         TEXT,                   -- 单选标签
    orig_name   TEXT,                   -- 上传时的原始文件名
    mime        TEXT NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    size        INTEGER NOT NULL,
    c_key       TEXT,                   -- 压缩版相对路径，可为空（生成失败/动图）
    c_mime      TEXT,
    c_width     INTEGER,
    c_height    INTEGER,
    c_size      INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_created ON images(created_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    pwd             TEXT NOT NULL,          -- pbkdf2_sha256$iter$salt$hash
    role            TEXT NOT NULL DEFAULT 'user',   -- admin | user
    quota_mb        INTEGER NOT NULL DEFAULT 0,     -- 0 = 不限
    max_upload_mb   INTEGER NOT NULL DEFAULT 0,     -- 0 = 用全局
    daily_limit     INTEGER NOT NULL DEFAULT 0,     -- 24 小时内上传张数上限，0 = 不限
    weekly_limit    INTEGER NOT NULL DEFAULT 0,     -- 7 天内
    monthly_limit   INTEGER NOT NULL DEFAULT 0,     -- 30 天内
    comp_format     TEXT,                   -- NULL = 用全局
    comp_quality    INTEGER,
    comp_max_width  INTEGER,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    remember    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS settings (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);

-- 访问统计（保留 3 天，滚动清理）
CREATE TABLE IF NOT EXISTS visits (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,           -- 记录时刻（本地时区 ISO）
    day    TEXT NOT NULL,           -- 本地日期 YYYY-MM-DD
    ip     TEXT NOT NULL,
    path   TEXT NOT NULL,
    status INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visits_day ON visits(day);
CREATE INDEX IF NOT EXISTS idx_visits_ip ON visits(ip);

-- 封禁名单（持久化，重启不清零）
CREATE TABLE IF NOT EXISTS bans (
    ip         TEXT PRIMARY KEY,
    until_ts   INTEGER NOT NULL,     -- 解封时间（unix 秒）
    reason     TEXT NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bans_until ON bans(until_ts);

-- IP 白名单（单 IP 或 CIDR，命中则永不封禁、不参与限流）
CREATE TABLE IF NOT EXISTS ip_whitelist (
    pattern    TEXT PRIMARY KEY,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- 永久黑名单（单 IP 或 CIDR，命中直接拒绝，不参与限流判定）
CREATE TABLE IF NOT EXISTS ip_blacklist (
    pattern    TEXT PRIMARY KEY,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- IP 归属地缓存（只查一次，7 天刷新）
CREATE TABLE IF NOT EXISTS ip_geo (
    ip         TEXT PRIMARY KEY,
    location   TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
"""

# 索引必须在补列之后建（老库 images 表尚无 owner_id/tag）
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_images_owner ON images(owner_id);
CREATE INDEX IF NOT EXISTS idx_images_tag ON images(tag);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

# 全部可配置项与默认值（后台可调，flat 键值对，便于扩展新配置项/插件）
DEFAULT_SETTINGS = {
    # 站点信息
    "site_title": "wusaqi-gallery",
    "site_icon": "",          # favicon URL 或 emoji，空 = 默认
    "site_tags": "画廊,随机图,自部署",   # 标签池：顶部筛选 chips 的来源
    "site_footer": "Powered by wusaqi-gallery",
    "share_base_url": "",     # 对外分享基址，空 = 用当前访问 URL
    "upload_default_tags": "",  # 上传页默认选中的标签（逗号分隔）
    # 外观：配色风格（gradient = 炫彩渐变 / solid = 纯色单色）
    "theme_style": "solid",
    # 压缩方案（方案 B：按机器能力自动选档，可手动覆盖）
    "comp_profile": "auto",   # auto | tiny | small | normal | custom
    "comp_format": "webp",    # webp | jpeg | png（各档位共用）
    "comp_quality": "80",     # 仅 custom 生效
    "comp_max_width": "2560", # 仅 custom 生效，0 = 不缩放
    "comp_method": "0",       # 仅 custom 生效，webp 编码强度 0-6，0 = 按档位
    "comp_max_pixels": "0",   # 仅 custom 生效，解码像素上限（百万），0 = 按档位
    "comp_concurrency": "0",  # 仅 custom 生效，同时压缩张数，0 = 按档位
    # 上传限制
    "upload_max_mb": "5",     # 全局单图上限（MB），0 = 不限；用户级覆盖优先于此项
    # 新建用户的默认额度（后台可改）
    "new_user_quota_mb": "500",
    "new_user_max_upload_mb": "5",
    "new_user_daily": "30",
    "new_user_weekly": "100",
    "new_user_monthly": "250",
    # 通知中心（Webhook）
    "notify_method": "POST",        # POST | PUT
    "notify_body_type": "json",     # json | text
    "notify_headers": "",           # 自定义请求头（JSON 对象字符串）
    "notify_body_tpl": "",          # 请求体模板（{{event}}/{{message}}/{{time}}/{{site}}），空 = 默认
    "notify_admin_login": "0",      # 1 = 管理员登录时通知
    "notify_security": "1",         # 1 = 限流 / 防爆破告警
    "notify_ban": "0",              # 1 = 手动封禁 / 解封操作
    "notify_restore": "0",          # 1 = 备份恢复完成
    "notify_daily": "0",            # 1 = 每日汇报（PV/UV/上传数）
    "notify_daily_time": "09:00",   # 汇报时间（服务器本地时区 HH:MM）
    "notify_weekly": "0",           # 1 = 每周一报周报
    "notify_monthly": "0",          # 1 = 每月 1 号报月报
    # 权限
    "random_public": "0",     # 1 = 未登录也可用随机图 API（外链场景）
    # 登录
    "session_hours": "12",    # 不勾「记住我」时的有效期
    "remember_days": "30",    # 勾选后的有效期
    # 流量防御
    "rate_limit": "120",      # 每 IP 每分钟随机图请求上限，0 = 关闭
    "rate_ban_minutes": "10",  # 超限封禁时长
    "webhook_url": "",        # 超限/爆破告警 webhook（POST JSON）
    # 安全（防爆破）
    "auth_max_fails": "10",   # 累计鉴权失败次数阈值
    "auth_ban_minutes": "10",  # 触发后封禁时长
}

ADMIN_ID = "admin"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- 连接 / 迁移 ----------

def _seed_admin(conn: sqlite3.Connection) -> str:
    """首次启动播种管理员账号（用户名/密码来自环境变量）。"""
    pwd = util.hash_password(config.ADMIN_PASSWORD)
    # 用户名被旧数据占用时依次回退，保证站点一定能起来
    for name in (config.ADMIN_USERNAME, ADMIN_ID, f"{ADMIN_ID}-root"):
        try:
            conn.execute(
                "INSERT INTO users (id, username, pwd, role, quota_mb, created_at) "
                "VALUES (?, ?, ?, 'admin', 0, ?)",
                (ADMIN_ID, name, pwd, now_iso()))
            return ADMIN_ID
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("无法创建管理员账号：users 表存在冲突数据，请检查数据库")


def get_admin() -> dict | None:
    """取管理员账号（Token 直登用；不依赖 id 恰好是 ADMIN_ID）。"""
    row = get_conn().execute(
        "SELECT * FROM users WHERE role='admin' ORDER BY created_at LIMIT 1").fetchone()
    return dict(row) if row else None


def _migrate(conn: sqlite3.Connection) -> None:
    """老库补列 + 播种 admin + 历史图片归属。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)")}
    for name, ddl in (("owner_id", "TEXT"), ("tag", "TEXT"), ("orig_name", "TEXT")):
        if name not in cols:
            conn.execute(f"ALTER TABLE images ADD COLUMN {name} {ddl}")

    # 用户表补上传频率限制列（v5.1）
    ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    for name in ("daily_limit", "weekly_limit", "monthly_limit"):
        if name not in ucols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")

    row = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if row:
        aid = row["id"]
        # ADMIN_SYNC=1：把环境变量里的用户名/密码强制写回库（忘记密码的救援通道）
        if config.ADMIN_SYNC:
            try:
                conn.execute("UPDATE users SET username=?, pwd=? WHERE id=?",
                             (config.ADMIN_USERNAME, util.hash_password(config.ADMIN_PASSWORD), aid))
            except sqlite3.IntegrityError:
                # 目标用户名被别的账号占用 → 只同步密码
                conn.execute("UPDATE users SET pwd=? WHERE id=?",
                             (util.hash_password(config.ADMIN_PASSWORD), aid))
    else:
        aid = _seed_admin(conn)

    # 历史图片（v2 无归属）统一记到 admin 名下
    conn.execute("UPDATE images SET owner_id=? WHERE owner_id IS NULL", (aid,))
    conn.commit()


def get_conn() -> sqlite3.Connection:
    """取当前线程的连接。

    历史实现是全局单连接 + check_same_thread=False，但 FastAPI 的同步端点跑在线程池里，
    多线程同时 execute 同一条连接会互相踩游标，表现为偶发
    `sqlite3.InterfaceError: bad parameter or other API misuse` 或读到 None 字段。
    改为线程本地连接，建表/迁移用全局锁保证只执行一次。
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")     # 备份恢复会关掉所有旧连接
        except Exception:
            conn = None
            _local.conn = None
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, timeout=15)
        with _conns_lock:
            _conns.append(conn)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    global _schema_ready
    if not _schema_ready:
        with _init_lock:
            if not _schema_ready:
                conn.executescript(SCHEMA)
                for k, v in DEFAULT_SETTINGS.items():
                    conn.execute("INSERT OR IGNORE INTO settings(k, v) VALUES (?, ?)", (k, v))
                conn.commit()
                _migrate(conn)          # 补列 + 播种 admin + 历史图片归属
                conn.executescript(INDEXES)
                conn.commit()
                _schema_ready = True
    return conn


# ---------- settings ----------

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


# ---------- images ----------

def insert_image(row: dict) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            """INSERT INTO images
               (id, key, owner_id, tag, orig_name, mime, width, height, size,
                c_key, c_mime, c_width, c_height, c_size, created_at)
               VALUES (:id, :key, :owner_id, :tag, :orig_name, :mime, :width, :height, :size,
                       :c_key, :c_mime, :c_width, :c_height, :c_size, :created_at)""",
            row)
        conn.commit()


def key_exists(key: str) -> bool:
    return get_conn().execute(
        "SELECT 1 FROM images WHERE key = ?", (key,)).fetchone() is not None


def get_image(image_id: str) -> dict | None:
    row = get_conn().execute(
        "SELECT i.*, u.username AS owner_name FROM images i "
        "LEFT JOIN users u ON u.id = i.owner_id WHERE i.id = ?", (image_id,)).fetchone()
    return dict(row) if row else None


def update_image(image_id: str, fields: dict) -> None:
    allowed = {"key", "c_key", "tag", "orig_name",
               "c_mime", "c_width", "c_height", "c_size"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    with _lock:
        conn = get_conn()
        conn.execute(
            f"UPDATE images SET {', '.join(f'{k} = :{k}' for k in sets)} WHERE id = :_id",
            {**sets, "_id": image_id})
        conn.commit()


def delete_image(image_id: str) -> None:
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        conn.commit()


def list_images(page: int, limit: int, sort: str,
                tag: str | None = None, owner_id: str | None = None) -> tuple[list, int]:
    where, args = [], []
    if tag:
        where.append("i.tag = ?")
        args.append(tag)
    if owner_id:
        where.append("i.owner_id = ?")
        args.append(owner_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order = "RANDOM()" if sort == "random" else "i.created_at DESC, i.rowid DESC"
    conn = get_conn()
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM images i {where_sql}", args).fetchone()["n"]
    rows = conn.execute(
        f"SELECT i.*, u.username AS owner_name FROM images i "
        f"LEFT JOIN users u ON u.id = i.owner_id "
        f"{where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
        (*args, limit, (page - 1) * limit)).fetchall()
    return [dict(r) for r in rows], total


def random_image(owner_id: str | None = None) -> dict | None:
    sql = "SELECT * FROM images"
    args: tuple = ()
    if owner_id:
        sql += " WHERE owner_id = ?"
        args = (owner_id,)
    row = get_conn().execute(sql + " ORDER BY RANDOM() LIMIT 1", args).fetchone()
    return dict(row) if row else None


def all_keys() -> set[str]:
    rows = get_conn().execute("SELECT key FROM images").fetchall()
    return {r["key"] for r in rows}


def all_images() -> list[dict]:
    """全量图片记录（维护用，按创建时间倒序）。"""
    rows = get_conn().execute(
        "SELECT * FROM images ORDER BY created_at DESC, rowid DESC").fetchall()
    return [dict(r) for r in rows]


def tag_counts() -> dict[str, int]:
    rows = get_conn().execute(
        "SELECT tag, COUNT(*) AS n FROM images WHERE tag IS NOT NULL AND tag != '' "
        "GROUP BY tag").fetchall()
    return {r["tag"]: r["n"] for r in rows}


# ---------- users ----------

def _user_row(row) -> dict:
    d = dict(row)
    v = d.get("enabled")            # 老库可能是 NULL，直接 int(None) 会 500
    d["enabled"] = 1 if v is None else int(v)
    return d


def get_user(user_id: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_row(row) if row else None


def get_user_by_name(username: str) -> dict | None:
    row = get_conn().execute(
        "SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _user_row(row) if row else None


def list_users() -> list[dict]:
    now = datetime.now(timezone.utc)
    cut = {k: (now - timedelta(days=d)).isoformat(timespec="seconds")
           for k, d in (("day", 1), ("week", 7), ("month", 30))}
    rows = get_conn().execute(
        """SELECT u.*, COALESCE(SUM(i.size), 0) AS used, COUNT(i.id) AS count,
                  COALESCE(SUM(CASE WHEN i.created_at >= :day THEN 1 ELSE 0 END), 0) AS day_count,
                  COALESCE(SUM(CASE WHEN i.created_at >= :week THEN 1 ELSE 0 END), 0) AS week_count,
                  COALESCE(SUM(CASE WHEN i.created_at >= :month THEN 1 ELSE 0 END), 0) AS month_count
           FROM users u LEFT JOIN images i ON i.owner_id = u.id
           GROUP BY u.id ORDER BY u.role = 'admin' DESC, u.created_at ASC""",
        cut).fetchall()
    out = []
    for r in rows:
        d = _user_row(r)
        d["used"] = int(d.get("used") or 0)
        d["count"] = int(d.get("count") or 0)
        d["day_count"] = int(d.get("day_count") or 0)
        d["week_count"] = int(d.get("week_count") or 0)
        d["month_count"] = int(d.get("month_count") or 0)
        d.pop("pwd", None)
        out.append(d)
    return out


def create_user(username: str, password: str, role: str = "user", quota_mb: int = 0,
                max_upload_mb: int = 0, comp_format: str | None = None,
                comp_quality: int | None = None, comp_max_width: int | None = None,
                daily_limit: int = 0, weekly_limit: int = 0,
                monthly_limit: int = 0) -> dict:
    uid = util.short_id(8)
    while get_user(uid):
        uid = util.short_id(8)
    with _lock:
        conn = get_conn()
        conn.execute(
            """INSERT INTO users (id, username, pwd, role, quota_mb, max_upload_mb,
                                  daily_limit, weekly_limit, monthly_limit,
                                  comp_format, comp_quality, comp_max_width, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (uid, username, util.hash_password(password), role, quota_mb, max_upload_mb,
             daily_limit, weekly_limit, monthly_limit,
             comp_format, comp_quality, comp_max_width, now_iso()))
        conn.commit()
    return get_user(uid)


def update_user(user_id: str, fields: dict) -> None:
    allowed = {"username", "role", "quota_mb", "max_upload_mb",
               "daily_limit", "weekly_limit", "monthly_limit",
               "comp_format", "comp_quality", "comp_max_width", "enabled", "pwd"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    with _lock:
        conn = get_conn()
        conn.execute(
            f"UPDATE users SET {', '.join(f'{k} = :{k}' for k in sets)} WHERE id = :_id",
            {**sets, "_id": user_id})
        conn.commit()


def delete_user(user_id: str, purge: bool = False, transfer_to: str = ADMIN_ID) -> int:
    """删用户。purge=False 时把其图片转交 transfer_to，返回被清理的图片数。"""
    with _lock:
        conn = get_conn()
        removed = 0
        if purge:
            rows = conn.execute("SELECT key, c_key FROM images WHERE owner_id = ?",
                                (user_id,)).fetchall()
            removed = len(rows)
            conn.execute("DELETE FROM images WHERE owner_id = ?", (user_id,))
        else:
            conn.execute("UPDATE images SET owner_id = ? WHERE owner_id = ?",
                         (transfer_to, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return removed


def user_usage(user_id: str) -> dict:
    row = get_conn().execute(
        "SELECT COALESCE(SUM(size), 0) AS used, COUNT(*) AS count "
        "FROM images WHERE owner_id = ?", (user_id,)).fetchone()
    return {"used": int(row["used"] or 0), "count": int(row["count"] or 0)}


def user_upload_counts(user_id: str) -> dict:
    """滑动窗口上传张数：最近 24 小时 / 7 天 / 30 天。"""
    now = datetime.now(timezone.utc)
    conn = get_conn()
    out = {}
    for key, days in (("day", 1), ("week", 7), ("month", 30)):
        since = (now - timedelta(days=days)).isoformat(timespec="seconds")
        out[key] = conn.execute(
            "SELECT COUNT(*) AS n FROM images WHERE owner_id = ? AND created_at >= ?",
            (user_id, since)).fetchone()["n"]
    return out


# ---------- sessions ----------

def create_session(token: str, user_id: str, expires_at: str, remember: bool) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at, remember, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, user_id, expires_at, 1 if remember else 0, now_iso()))
        conn.commit()


def get_session(token: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d["expires_at"] <= now_iso():
        delete_session(token)
        return None
    return d


def delete_session(token: str) -> None:
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def purge_expired_sessions() -> None:
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso(),))
        conn.commit()


# ---------- 访问统计（3 天滚动） ----------

def get_setting(key: str, default: str = "") -> str:
    return get_settings().get(key, default)


def record_visit(ip: str, path: str, status: int) -> None:
    now = datetime.now().astimezone()
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO visits (ts, day, ip, path, status) VALUES (?, ?, ?, ?, ?)",
            (now.isoformat(timespec="seconds"), now.strftime("%Y-%m-%d"), ip, path, status))
        conn.commit()
        # 概率触发滚动清理（保留 3 天），避免每请求都跑 DELETE
        if random.random() < 0.02:
            cut = (now - timedelta(days=3)).strftime("%Y-%m-%d")
            conn.execute("DELETE FROM visits WHERE day < ?", (cut,))
            conn.execute("DELETE FROM ip_geo WHERE checked_at < ?",
                         ((now - timedelta(days=7)).isoformat(timespec="seconds"),))
            conn.commit()


def purge_visits() -> None:
    cut = (datetime.now().astimezone() - timedelta(days=3)).strftime("%Y-%m-%d")
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM visits WHERE day < ?", (cut,))
        conn.commit()


def stats_days(days: int = 3) -> list[dict]:
    """最近 N 天逐日 PV / UV（含今天，不足的天补零）。"""
    today = datetime.now().astimezone().date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    rows = get_conn().execute(
        "SELECT day, COUNT(*) AS pv, COUNT(DISTINCT ip) AS uv "
        "FROM visits WHERE day >= ? GROUP BY day",
        (dates[0],)).fetchall()
    m = {r["day"]: dict(r) for r in rows}
    return [{"day": d, "pv": m.get(d, {}).get("pv", 0), "uv": m.get(d, {}).get("uv", 0)}
            for d in dates]


def stats_top_ips(days: int = 3, limit: int = 20) -> list[dict]:
    cut = (datetime.now().astimezone() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = get_conn().execute(
        "SELECT ip, COUNT(*) AS count, MIN(ts) AS first_at, MAX(ts) AS last_at "
        "FROM visits WHERE day >= ? GROUP BY ip ORDER BY count DESC LIMIT ?",
        (cut, limit)).fetchall()
    out = []
    geo = {r["ip"]: r["location"] for r in get_conn().execute(
        "SELECT ip, location FROM ip_geo").fetchall()}
    for r in rows:
        d = dict(r)
        d["geo"] = geo.get(r["ip"], "")
        out.append(d)
    return out


def stats_top_paths(days: int = 3, limit: int = 10) -> list[dict]:
    cut = (datetime.now().astimezone() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = get_conn().execute(
        "SELECT path, COUNT(*) AS count FROM visits WHERE day >= ? "
        "GROUP BY path ORDER BY count DESC LIMIT ?", (cut, limit)).fetchall()
    return [dict(r) for r in rows]


def stats_summary(days: int = 1) -> dict:
    cut = (datetime.now().astimezone() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    r = get_conn().execute(
        "SELECT COUNT(*) AS pv, COUNT(DISTINCT ip) AS uv FROM visits WHERE day >= ?",
        (cut,)).fetchone()
    return {"pv": r["pv"], "uv": r["uv"]}


def uploads_since(since_iso: str) -> dict:
    r = get_conn().execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes "
        "FROM images WHERE created_at >= ?", (since_iso,)).fetchone()
    return {"count": r["n"], "bytes": int(r["bytes"] or 0)}


def geo_get(ip: str) -> str | None:
    r = get_conn().execute("SELECT location FROM ip_geo WHERE ip = ?", (ip,)).fetchone()
    return r["location"] if r else None


def geo_put(ip: str, location: str) -> None:
    with _lock:
        get_conn().execute(
            "INSERT INTO ip_geo (ip, location, checked_at) VALUES (?, ?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET location = excluded.location, "
            "checked_at = excluded.checked_at",
            (ip, location, now_iso()))
        get_conn().commit()


# ---------- 封禁 / 白名单（持久化） ----------

def ban_add(ip: str, minutes: int, reason: str) -> None:
    """封禁 IP；已存在则累加次数并延长到更晚的时间。"""
    until = int(time.time() + max(1, minutes) * 60)
    with _lock:
        conn = get_conn()
        row = conn.execute("SELECT until_ts, hits FROM bans WHERE ip = ?", (ip,)).fetchone()
        if row:
            conn.execute("UPDATE bans SET until_ts = ?, reason = ?, hits = ? WHERE ip = ?",
                         (max(until, row["until_ts"]), reason, row["hits"] + 1, ip))
        else:
            conn.execute("INSERT INTO bans (ip, until_ts, reason, hits, created_at) "
                         "VALUES (?, ?, ?, 1, ?)", (ip, until, reason, now_iso()))
        conn.commit()


def ban_remove(ip: str) -> bool:
    with _lock:
        conn = get_conn()
        cur = conn.execute("DELETE FROM bans WHERE ip = ?", (ip,))
        conn.commit()
        return cur.rowcount > 0


def bans_all(now_ts: float | None = None) -> list[dict]:
    """当前生效的封禁（顺手清掉已过期的）。"""
    now = int(now_ts if now_ts is not None else time.time())
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM bans WHERE until_ts <= ?", (now,))
        conn.commit()
        rows = conn.execute("SELECT * FROM bans ORDER BY until_ts DESC").fetchall()
    return [dict(r) for r in rows]


def ban_get(ip: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM bans WHERE ip = ?", (ip,)).fetchone()
    return dict(row) if row else None


def whitelist_all() -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM ip_whitelist ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def whitelist_add(pattern: str, note: str = "") -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO ip_whitelist (pattern, note, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(pattern) DO UPDATE SET note = excluded.note",
            (pattern, note or "", now_iso()))
        conn.commit()


def whitelist_remove(pattern: str) -> bool:
    with _lock:
        conn = get_conn()
        cur = conn.execute("DELETE FROM ip_whitelist WHERE pattern = ?", (pattern,))
        conn.commit()
        return cur.rowcount > 0


# ---------- 备份 / 恢复辅助 ----------

def close_all() -> None:
    """关闭所有已知连接（恢复备份前调用），下次 get_conn() 自动重连新库。"""
    global _schema_ready
    with _init_lock:
        with _conns_lock:
            for c in _conns:
                try:
                    c.close()
                except Exception:
                    pass
            _conns.clear()
        _local.conn = None
        _schema_ready = False


def snapshot_to(path: str) -> None:
    """用 SQLite 在线备份 API 导出一致性快照（WAL 下直接拷文件可能撕页）。"""
    with _lock:
        src = get_conn()
        dst = sqlite3.connect(path)
        try:
            src.backup(dst)
        finally:
            dst.close()


def counts() -> dict:
    conn = get_conn()
    out = {}
    for t in ("images", "users", "visits", "bans", "ip_whitelist", "ip_blacklist"):
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        except Exception:
            out[t] = 0
    return out


def blacklist_all() -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM ip_blacklist ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def blacklist_add(pattern: str, note: str = "") -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO ip_blacklist (pattern, note, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(pattern) DO UPDATE SET note = excluded.note",
            (pattern, note or "", now_iso()))
        conn.commit()


def blacklist_remove(pattern: str) -> bool:
    with _lock:
        conn = get_conn()
        cur = conn.execute("DELETE FROM ip_blacklist WHERE pattern = ?", (pattern,))
        conn.commit()
        return cur.rowcount > 0


def restore_from(src_path: str) -> None:
    """把 src_path 这个库整体写回当前库（不替换文件，Windows 下也不会被占用卡住）。"""
    global _schema_ready
    with _lock:
        src = sqlite3.connect(src_path)
        try:
            src.backup(get_conn())      # 目标=活库，内容整体覆盖
        finally:
            src.close()
    _schema_ready = False               # 让 get_conn() 重跑建表/补列（老备份平滑升级）
    get_conn()
