#!/bin/bash
# 起一个"自定义管理员账号 + 关闭 Token 直登"的测试实例（8010），密码从临时文件读
BASE="/path/to/project/.tmp-v4"
export DATA_DIR="$BASE/http"
export ADMIN_USERNAME="owner"
export ADMIN_PASSWORD="$(cat "$BASE/pw.txt")"
export ADMIN_TOKEN="legacy-token-for-test"
export ALLOW_ADMIN_TOKEN="0"
export PYTHONIOENCODING="utf-8"
cd "$(dirname "$0")/../backend" || exit 1
exec "python3" \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8010
