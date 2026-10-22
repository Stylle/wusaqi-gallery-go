"""单元级验收：环境变量解析 + 管理员播种/同步（每个用例独立进程）。

路径自适应：python 解释器取当前运行的 sys.executable，backend/TMP 按本文件位置推导，
在任意机器、任意盘符上均可直接运行：python qa/unit-admin-env.py
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
TMP = os.path.join(ROOT, ".tmp-qa-unit")
PY = sys.executable

passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  OK   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}  {extra}")


def probe(code, env=None):
    e = dict(os.environ)
    for k in ("ADMIN_PASSWORD", "ADMIN_USERNAME", "ADMIN_SYNC", "DATA_DIR"):
        e.pop(k, None)
    e["PYTHONIOENCODING"] = "utf-8"
    e.update(env or {})
    p = subprocess.run([PY, "-c", code], cwd=BACKEND, env=e,
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"probe 失败: {p.stderr[-800:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


CONF = """
import json
from app import config
print(json.dumps({
  'username': config.ADMIN_USERNAME,
  'password': config.ADMIN_PASSWORD,
  'sync': config.ADMIN_SYNC,
}, ensure_ascii=False))
"""

SEED = """
import json, os
from app import config, db, util
os.makedirs(config.DATA_DIR, exist_ok=True)
db.get_conn()
a = db.get_admin()
print(json.dumps({
  'username': a['username'], 'role': a['role'],
  'p_ok': util.verify_password(%r, a['pwd']),
  'p_bad': util.verify_password(%r, a['pwd']),
}, ensure_ascii=False))
"""


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)

    print("\n[1] 环境变量解析")
    r = probe(CONF, {})
    check("全空 → 用户名 admin", r["username"] == "admin", r["username"])
    check("全空 → changeme", r["password"] == "changeme", r["password"])
    check("全空 → 同步关闭", r["sync"] is False, r["sync"])

    r = probe(CONF, {"ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "p1", "ADMIN_SYNC": "1"})
    check("自定义用户名生效", r["username"] == "owner", r["username"])
    check("自定义密码生效", r["password"] == "p1", r["password"])
    check("同步开关生效", r["sync"] is True, r["sync"])

    print("\n[2] 播种（全新库）")
    d = os.path.join(TMP, "seed")
    r = probe(SEED % ("p1", "wrong"), {"DATA_DIR": d, "ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "p1"})
    check("用户名 = owner", r["username"] == "owner", r["username"])
    check("角色 = admin", r["role"] == "admin", r["role"])
    check("密码可用", r["p_ok"] is True)
    check("错误密码不通过", r["p_bad"] is False)

    print("\n[3] 二次启动：不覆盖已有密码")
    r = probe(SEED % ("p1", "p2"), {"DATA_DIR": d, "ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "p2"})
    check("旧密码仍有效", r["p_ok"] is True)
    check("新环境变量未覆盖", r["p_bad"] is False)

    print("\n[4] ADMIN_SYNC=1 强制同步")
    r = probe(SEED % ("p3", "p1"), {"DATA_DIR": d, "ADMIN_USERNAME": "owner",
                                    "ADMIN_PASSWORD": "p3", "ADMIN_SYNC": "1"})
    check("同步后新密码有效", r["p_ok"] is True)
    check("旧密码失效", r["p_bad"] is False)

    print("\n[5] 老库升级：id=admin 的账号被复用，不重复建号")
    code = """
import json
from app import db
db.get_conn()
rows = db.get_conn().execute("SELECT id, username, role FROM users WHERE role='admin'").fetchall()
print(json.dumps({'n': len(rows), 'ids': [r['id'] for r in rows]}, ensure_ascii=False))
"""
    r = probe(code, {"DATA_DIR": d, "ADMIN_USERNAME": "owner2", "ADMIN_PASSWORD": "x"})
    check("管理员账号唯一", r["n"] == 1, str(r))
    check("id 仍为 admin", r["ids"] == ["admin"], str(r["ids"]))

    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n===== {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
