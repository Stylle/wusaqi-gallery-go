"""V4：docker-compose 环境变量契约检查（本机没装 docker，用 YAML 解析代替）。"""
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  OK   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}  {extra}")


def main():
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        raw = f.read()
    compose = yaml.safe_load(raw)
    check("单容器化（仅一个服务）", list(compose["services"]) == ["gallery"],
          str(list(compose["services"])))
    env = compose["services"]["gallery"]["environment"]
    check("healthcheck 存在", "healthcheck" in compose["services"]["gallery"])

    check("compose YAML 可解析", isinstance(env, list) and len(env) > 0)
    keys = [e.split("=", 1)[0] for e in env]
    for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_SYNC"):
        check(f"声明了 {k}", k in keys, str(keys))
    for gone in ("ADMIN_TOKEN", "ALLOW_ADMIN_TOKEN"):
        check(f"已移除 {gone}", gone not in keys, str(keys))

    check("不再有 :? 强制必填", ":?" not in raw)
    check("ADMIN_SYNC 默认 0（不覆盖后台改的密码）", "ADMIN_SYNC=${ADMIN_SYNC:-0}" in raw)
    check("ADMIN_PASSWORD 允许留空（回落 changeme）", "ADMIN_PASSWORD=${ADMIN_PASSWORD:-}" in raw)

    # 后端读取的变量必须和 compose 声明的一致
    cfg = open(os.path.join(ROOT, "backend", "app", "config.py"), encoding="utf-8").read()
    used = set(re.findall(r'(?:environ\.get|_flag)\("([A-Z_]+)"', cfg))
    for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_SYNC"):
        check(f"后端读取 {k}", k in used, str(sorted(used)))

    # .env.example 覆盖所有 compose 变量
    ex = open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
    env_keys = set(re.findall(r"^([A-Z_]+)=", ex, re.M))
    for e in env:
        if "${" not in e:           # 硬编码值（如 DATA_DIR=/data），不需要 .env
            continue
        k = e.split("=", 1)[0]
        check(f".env.example 含 {k}", k in env_keys, str(sorted(env_keys)))

    print(f"\n===== {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
