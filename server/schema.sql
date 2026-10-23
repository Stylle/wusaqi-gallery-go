
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
