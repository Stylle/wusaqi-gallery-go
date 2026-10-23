#!/usr/bin/env bash
# 构建并推送 wusaqi-gallery 单容器镜像到 Docker Hub
# Go 单进程服务，Pillow 仅按需启动。
# 用法（在仓库根目录、已 docker login 的机器上）：
#   bash scripts/build-push.sh              # 推 latest + git 短哈希双标签
#   IMAGE_PREFIX=myuser bash scripts/build-push.sh   # 自定义命名空间
set -euo pipefail

PREFIX="${IMAGE_PREFIX:-stylle}"
IMAGE="${PREFIX}/wusaqi-gallery"
VERSION="$(git rev-parse --short HEAD)"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

echo "==> 构建 ${IMAGE}:${VERSION}"
docker buildx build --platform "$PLATFORMS" -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" --push .

echo
echo "✅ 完成。部署端拉取升级："
echo "   docker compose -f docker-compose.hub.yml pull && docker compose -f docker-compose.hub.yml up -d"
