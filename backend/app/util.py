"""短 id / 存储 key / 密码哈希 等纯函数工具。"""
import hashlib
import random
import re
import secrets
import string
import time

ALPHABET = string.digits + string.ascii_letters  # base62

PBKDF2_ITER = 200_000


def short_id(n: int = 7) -> str:
    return "".join(random.SystemRandom().choice(ALPHABET) for _ in range(n))


def new_key(ext: str) -> str:
    """uploads/YYYYMMDD/<unix秒>-<8位随机>.<ext>，按日期分目录便于备份/迁移。"""
    ts = int(time.time())
    r = "".join(random.SystemRandom().choice(ALPHABET) for _ in range(8))
    t = time.localtime(ts)
    return f"uploads/{t.tm_year:04d}{t.tm_mon:02d}{t.tm_mday:02d}/{ts}-{r}.{ext}"


# ---------- 密码哈希（PBKDF2-SHA256，无第三方依赖） ----------

def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(iters))
        return secrets.compare_digest(dk.hex(), digest)
    except Exception:
        return False


# ---------- 文件名清洗（重命名用） ----------

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_stem(name: str, fallback: str = "image", max_len: int = 80) -> str:
    """把用户输入清洗成安全的文件名主干（不含扩展名）。"""
    s = _BAD.sub("", (name or "").strip())
    s = s.replace("..", "").strip(" .")
    s = re.sub(r"\s+", "-", s)
    if not s:
        s = fallback
    return s[:max_len]
