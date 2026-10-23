# 维护者发布

本地重构、文档与测试可以先完成；推送 GitHub、安装 Docker 环境并构建/上传镜像，以及修改线上仓库介绍，需要按项目所有者的安排取得对应登录许可。当前文档和脚本不代表已发布。

## 介绍信息

GitHub About 建议：

> 轻量自部署图片画廊与随机图 API。Vue 3 + Go + SQLite，滚动加载、多用户、标签、压缩、备份，单容器部署。

Docker Hub short description（不超过 100 字符）：

> Lightweight self-hosted gallery & random image API. Go + Vue + SQLite; on-demand image processing.

GitHub README 主源是仓库根目录 `README.md`；Docker Hub Overview 由 `python scripts/sync-docs.py` 生成到 `docs/dockerhub-description.md`，其中相对文档链接会转成 GitHub 地址。发布验证完成后再移除两份介绍中的“尚未发布”提示并重新同步。

## 本地验收

```bash
cd frontend
npm ci
npm test
npm run build
cd ../server
go test ./...
go vet ./...
go build -trimpath -ldflags="-s -w" -o gallery .
cd ..
python qa/regression.py
python qa/check-compose.py
python qa/memory-benchmark.py
python scripts/sync-docs.py
```

检查旧数据迁移、登录、全部后台、滚动加载和三种图片链接；保留新的本地数据目录，不使用生产数据做破坏性测试。原生平台内存结果与 Docker 结果分别记录在 `docs/architecture.md`。

## 凭据和权限

- GitHub：所有者在本机完成设备登录或提供仅限此仓库写入的访问授权。修改 README、提交代码和 About 是不同操作，应在发布时核对。
- Docker Hub：用户名 `stylle`，需要对 `stylle/wusaqi-gallery` 有写入权限的 PAT。使用 Docker 的交互登录或 `--password-stdin`，不把凭据写入文件、Compose、镜像层或命令行参数。
- Docker Engine/Desktop：需可用的 Linux 容器后端；Windows 如果尚未启用 WSL 2/虚拟化，安装可能要求管理员权限及重启。

## 构建与推送

已有脚本面向当前平台构建，同时推送 Git 短哈希与 `latest`：

```bash
docker login -u stylle
bash scripts/build-push.sh
# Windows: scripts\build-push.bat
```

给 amd64 NAS/VPS 与 arm64 主机发布多架构镜像时：

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t stylle/wusaqi-gallery:<git-short-sha> \
  -t stylle/wusaqi-gallery:latest --push .
```

先用本地标签完成容器健康检查和内存验收，再运行含 `--push` 的命令。推送后验证镜像标签、目标平台、健康检查与实际拉取。

Docker Hub Overview 上传 `docs/dockerhub-description.md` 的完整内容，short description 使用上文建议；GitHub About 同步更新。凭据不足时保留已生成的介绍文件，不能把本地生成冒充线上更新。
