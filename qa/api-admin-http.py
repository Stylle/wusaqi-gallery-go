"""端到端：自定义管理员账号 + 会话生命周期（针对 8010 测试实例）。

启动方式（先把后端跑在 8010，端口可用 BASE 覆盖）：
  python qa/api-admin-http.py
账号取环境变量 QA_USER / QA_PASS，缺省 owner / qa-pass-123。
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:8010")
USER = os.environ.get("QA_USER", "owner")
PW = os.environ.get("QA_PASS", "qa-pass-123")

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
check("响应不含 token_login 字段", "token_login" not in ps, str(ps))

st, r = call("POST", "/api/auth/login", {"username": USER, "password": PW})
check("自定义账号登录成功", st == 200, f"{st} {r}")
tk = r.get("token", "")
check("返回会话 token", bool(tk))

st, me = call("GET", "/api/auth/me", token=tk)
check(f"身份为 {USER} / admin", me.get("username") == USER and me.get("role") == "admin", str(me))

st, _ = call("GET", "/api/users", token=tk)
check("会话可访问管理接口", st == 200, str(st))

st, _ = call("POST", "/api/admin/verify", token=tk)
check("旧 verify 端点已移除（404）", st == 404, str(st))

st, _ = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
check("默认用户名 admin 不可用（若播种即 owner）", st == 401, str(st))

st, _ = call("POST", "/api/auth/login", {"username": USER, "password": "wrong-pass"})
check("错误密码被拒绝", st == 401, str(st))

st, _ = call("POST", "/api/auth/logout", token=tk)
check("登出成功", st == 200, str(st))
st, _ = call("GET", "/api/auth/me", token=tk)
check("登出后会话失效（401）", st == 401, str(st))

print(f"\n===== {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
