"""数据备份与恢复（含图片）。

备份内容（zip）：
    MANIFEST.json          版本、时间、统计
    metadata.db            SQLite 一致性快照（在线 backup API）
    uploads/...            原图
    compressed/...         压缩版
    thumbs/...             缩略图

恢复流程（先解压到 staging 校验，再原子替换，失败可回滚）：
    staging → 校验 metadata.db（必须能打开且有 images 表）
             → db.close_all()
             → 旧数据改名成 *.bak-<ts>，新数据就位
             → db.get_conn() 自动重连新库
"""
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile

from . import config, db

MANIFEST = "MANIFEST.json"
DIRS = ("uploads", "compressed", "thumbs")


def _dir_size(path: str) -> tuple[int, int]:
    total = files = 0
    for root, _, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return total, files


def stats() -> dict:
    db_bytes = os.path.getsize(config.DB_PATH) if os.path.exists(config.DB_PATH) else 0
    dirs = {}
    for d in DIRS:
        size, files = _dir_size(os.path.join(config.DATA_DIR, d))
        dirs[d] = {"bytes": size, "files": files}
    return {
        "db_bytes": db_bytes,
        "dirs": dirs,
        "counts": db.counts(),
        "data_dir": config.DATA_DIR,
        "total_bytes": db_bytes + sum(v["bytes"] for v in dirs.values()),
    }


def create_zip(dest: str) -> dict:
    """写出一份完整备份，返回 manifest。"""
    counts = db.counts()
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "metadata.db")
        db.snapshot_to(snap)               # WAL 下的安全快照
        manifest = {
            "app": "lolis-gallery",
            "format": 1,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "counts": counts,
            "data_dir": config.DATA_DIR,
        }
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(snap, "metadata.db")
            z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            for d in DIRS:
                base = os.path.join(config.DATA_DIR, d)
                if not os.path.isdir(base):
                    continue
                for root, _, names in os.walk(base):
                    for n in names:
                        full = os.path.join(root, n)
                        rel = os.path.relpath(full, config.DATA_DIR).replace("\\", "/")
                        try:
                            z.write(full, rel)
                        except OSError:
                            pass       # 正在被写入的文件跳过，不阻塞整包
    manifest["bytes"] = os.path.getsize(dest)
    return manifest


def _safe_name(name: str) -> bool:
    """拒绝绝对路径与目录穿越（zip-slip）。"""
    if name.startswith("/") or name.startswith("\\") or ".." in name.split("/"):
        return False
    return ":" not in name.split("/")[0]          # 排除 C: 这类盘符


def _validate_db(path: str) -> dict:
    if not os.path.exists(path):
        raise ValueError("备份里没有 metadata.db")
    try:
        conn = sqlite3.connect(path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "images" not in tables:
                raise ValueError("备份里的数据库不是本站格式（缺少 images 表）")
            n = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise ValueError(f"备份里的数据库无法打开：{e}")
    return {"images": n}


def restore_zip(zip_path: str) -> dict:
    """从备份包恢复（含图片）。

    Windows 下不能直接 rename 正在使用的 metadata.db，因此：
      数据库 → 用 SQLite backup API 整体写回活库（原子、不换文件）
      图片   → 覆盖同名文件（备份里没有的旧文件保留，避免误删）
    """
    stage = tempfile.mkdtemp(prefix="lg-restore-")
    try:
        # 1) 解压到 staging（逐个校验路径，挡 zip-slip）
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if name.endswith("/") or not _safe_name(name):
                    continue
                if name != "metadata.db" and name != MANIFEST and \
                        not any(name.startswith(d + "/") for d in DIRS):
                    continue
                target = os.path.join(stage, name)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)

        summary = _validate_db(os.path.join(stage, "metadata.db"))

        # 2) 数据库：写回活库
        db.restore_from(os.path.join(stage, "metadata.db"))

        # 3) 图片：覆盖同名文件
        copied = 0
        for d in DIRS:
            src_root = os.path.join(stage, d)
            if not os.path.isdir(src_root):
                continue
            dst_root = os.path.join(config.DATA_DIR, d)
            os.makedirs(dst_root, exist_ok=True)
            for root, _, names in os.walk(src_root):
                rel = os.path.relpath(root, src_root)
                dst_dir = os.path.join(dst_root, rel) if rel != "." else dst_root
                os.makedirs(dst_dir, exist_ok=True)
                for n in names:
                    try:
                        shutil.copy2(os.path.join(root, n), os.path.join(dst_dir, n))
                        copied += 1
                    except OSError:
                        pass       # 单个文件被占用就跳过，不影响整体
        summary["files_copied"] = copied
        summary["restored_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        return summary
    finally:
        shutil.rmtree(stage, ignore_errors=True)
