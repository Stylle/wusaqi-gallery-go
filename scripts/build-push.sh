#!/usr/bin/env bash
# 构建并推送 wusaqi-gallery 单容器镜像到 Docker Hub
# （nginx + uvicorn 同容器；双容器旧方案已废弃）。
# 用法（在仓库根目录、已 docker login 的机器上）：
#   bash scripts/build-push.sh              # 推 latest + git 短哈希双标签
#   IMAGE_PREFIX=myuser bash scripts/build-push.sh   # 自定义命名空间
set -euo pipefail

PREFIX="${IMAGE_PREFIX:-stylle}"
IMAGE="${PREFIX}/wusaqi-gallery"
VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"

echo "==> 构建 ${IMAGE}:${VERSION}"
docker build -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" .

echo "==> 推送（2 个标签）"
docker push "${IMAGE}:${VERSION}"
docker push "${IMAGE}:latest"

echo
echo "✅ 完成。部署端拉取升级："
echo "   docker compose -f docker-compose.hub.yml pull && docker compose -f docker-compose.hub.yml up -d"
