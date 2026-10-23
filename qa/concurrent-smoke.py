"""并发冒烟：验证 Go 服务的有界 SQLite 连接在并发请求下稳定响应。

用法：
    python qa/concurrent-smoke.py --base http://127.0.0.1:8000 \
        --user admin --password '你的密码' [--rounds 30]

Go 的 database/sql 负责请求排队，连接池固定为一条，避免线程各自保留缓存。
"""
import argparse
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor


def call(url, token=None, timeout=20):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        e.read()
        return e.code
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("QA_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--user", default=os.environ.get("QA_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("QA_PASSWORD", ""))
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()

    if not args.password:
        print("缺少 --password（或环境变量 QA_PASSWORD）")
        return 2

    login = urllib.request.Request(
        args.base + "/api/auth/login",
        data=json.dumps({"username": args.user, "password": args.password,
                         "remember": True}).encode(),
        headers={"Content-Type": "application/json"})
    token = json.loads(urllib.request.urlopen(login, timeout=15).read())["token"]

    paths = ["/api/images?page=1&limit=36", "/api/tags", "/api/auth/me",
             "/api/admin/stats", "/api/public/settings", "/api/users",
             "/api/admin/settings", "/api/admin/bans"]
    jobs = [(args.base + p, token) for p in paths for _ in range(args.rounds)]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        res = list(ex.map(lambda a: call(*a), jobs))

    dist = dict(Counter(res))
    bad = [r for r in res if r != 200]
    print(f"请求 {len(res)} 次 → {dist}")
    if bad:
        print(f"FAIL：{len(bad)} 个非 200：{sorted(set(map(str, bad)))}")
        return 1
    print("OK：全部 200，无 sqlite 并发错误")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
