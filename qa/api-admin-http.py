"""V4 端到端：自定义管理员账号 + ALLOW_ADMIN_TOKEN=0（针对 8010 测试实例）。"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"
PW = open(r"/path/to/project/pw.txt", encoding="utf-8").read().strip()
TOKEN = "legacy-token-for-test"

passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  OK   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}  {extra}")


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"raw": raw}


st, ps = call("GET", "/api/public/settings")
check("public settings 可用", st == 200, str(st))
check("token_login = 0", ps.get("token_login") == "0", str(ps.get("token_login")))

st, r = call("POST", "/api/auth/login", {"username": "owner", "password": PW})
check("自定义账号登录成功", st == 200, f"{st} {r}")
tk = r.get("token", "")
check("返回会话 token", bool(tk))

st, me = call("GET", "/api/auth/me", token=tk)
check("身份为 owner / admin", me.get("username") == "owner" and me.get("role") == "admin", str(me))

st, _ = call("GET", "/api/users", token=tk)
check("会话可访问管理接口", st == 200, str(st))

st, _ = call("POST", "/api/admin/verify", token=TOKEN)
check("ADMIN_TOKEN 直登被拒绝（401）", st == 401, str(st))

st, _ = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
check("默认用户名 admin 不可用", st == 401, str(st))

st, _ = call("POST", "/api/auth/login", {"username": "owner", "password": "wrong-pass"})
check("错误密码被拒绝", st == 401, str(st))

st, _ = call("POST", "/api/auth/logout", token=tk)
check("登出成功", st == 200, str(st))
st, _ = call("GET", "/api/auth/me", token=tk)
check("登出后会话失效（401）", st == 401, str(st))

print(f"\n===== {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
