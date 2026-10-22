"""并发冒烟：验证 SQLite 线程本地连接改造后不会出现偶发 500。

用法：
    python qa/concurrent-smoke.py --base http://127.0.0.1:8000 \
        --user admin --password '你的密码' [--rounds 30]

背景：db.get_conn() 早期是全局单连接 + check_same_thread=False，
FastAPI 同步端点跑线程池时多线程共用一个 Connection，会出现
`sqlite3.InterfaceError: bad parameter or other API misuse`
或读到 None 字段导致 500。改成线程本地连接后应全部 200。
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
