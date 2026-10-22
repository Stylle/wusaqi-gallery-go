#!/usr/bin/env bash
# 构建并推送 lolis-gallery 双镜像到 Docker Hub。
# 用法（在仓库根目录、已 docker login 的机器上）：
#   bash scripts/build-push.sh              # 推 latest + git 短哈希双标签
#   IMAGE_PREFIX=myuser bash scripts/build-push.sh   # 自定义命名空间
set -euo pipefail

PREFIX="${IMAGE_PREFIX:-stylle}"
API_IMAGE="${PREFIX}/lolis-api"
WEB_IMAGE="${PREFIX}/lolis-web"
VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"

echo "==> 构建 ${API_IMAGE}:${VERSION}"
docker build -t "${API_IMAGE}:${VERSION}" -t "${API_IMAGE}:latest" ./backend

echo "==> 构建 ${WEB_IMAGE}:${VERSION}"
docker build -t "${WEB_IMAGE}:${VERSION}" -t "${WEB_IMAGE}:latest" ./frontend

echo "==> 推送（共 4 个标签）"
docker push "${API_IMAGE}:${VERSION}"
docker push "${API_IMAGE}:latest"
docker push "${WEB_IMAGE}:${VERSION}"
docker push "${WEB_IMAGE}:latest"

echo
echo "✅ 完成。NAS 端拉取部署："
echo "   curl -O https://raw.githubusercontent.com/Stylle/lolis-gallery/main/docker-compose.hub.yml"
echo "   docker compose -f docker-compose.hub.yml up -d"
