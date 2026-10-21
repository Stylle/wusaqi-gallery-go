"""短 id / 存储 key 生成。"""
import random
import string
import time

ALPHABET = string.digits + string.ascii_letters  # base62


def short_id(n: int = 7) -> str:
    return "".join(random.SystemRandom().choice(ALPHABET) for _ in range(n))


def new_key(ext: str) -> str:
    """uploads/YYYY/MM/DD/<unix秒>-<8位随机>.<ext>，与原站规律一致。"""
    ts = int(time.time())
    r = "".join(random.SystemRandom().choice(ALPHABET) for _ in range(8))
    t = time.gmtime(ts)
    return f"uploads/{t.tm_year:04d}/{t.tm_mon:02d}/{t.tm_mday:02d}/{ts}-{r}.{ext}"
