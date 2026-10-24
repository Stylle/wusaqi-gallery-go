# 维护者发布

发布前使用独立测试数据完成容器功能、迁移、图片处理与内存检查；镜像标签与源码提交对应，凭据只交给官方认证接口或 Docker CLI，不写入源码、镜像层和日志。

## 2026-10-23 发布记录

- 源码提交：`67fa611`，新仓库 [Stylle/wusaqi-gallery-go](https://github.com/Stylle/wusaqi-gallery-go)。旧仓库保留。
- 镜像：`stylle/wusaqi-gallery:67fa611` 和 `:latest`，均包含 `linux/amd64`、`linux/arm64`。
- 镜像索引摘要：`sha256:b30642a0c80504618055464487b5100f3a1f98dff6933d99bca699e2e432f447`。
- amd64 清单：`sha256:3637e348c24f0974c5fe8d98bf969aab3b951e34f1af8d8600f2127d9fe8e006`；arm64 清单：`sha256:1e9c62468df60ce78e2f75861786a2d6c37e40dc14cf9ec23867d54a7c5c7bbd`。
- 旧 Python 镜像保留为 `stylle/wusaqi-gallery:legacy-python-20261023`，摘要 `sha256:0c5ecc311ac0de0795f9ebd0871b7d2e0353074f8c661ea7ea59cd1f26681327`。
- amd64 容器 89 项回归、ARM64 模拟执行 12 项检查通过；镜像上传后实际拉取，再通过 12 项发布检查后更新 `latest`。内存原始数据见 [架构与测量](architecture.md)。

回滚时指定旧镜像标签；如果升级后发生过数据库恢复或其他业务修改，还应使用升级前的数据备份。镜像标签不能代替数据备份。

## 介绍信息

GitHub About 建议：

> 轻量自部署图片画廊与随机图 API。Vue 3 + Go + SQLite，滚动加载、多用户、标签、压缩、备份，单容器部署。

Docker Hub short description（不超过 100 字符）：

> Lightweight self-hosted gallery & random image API. Go + Vue + SQLite; on-demand image processing.

GitHub README 主源是仓库根目录 `README.md`；Docker Hub Overview 由 `python scripts/sync-docs.py` 生成到 `docs/dockerhub-description.md`，其中相对文档链接会转成 GitHub 地址。发布后按实际标签与验证结果更新介绍，再重新同步。

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
python qa/features.py
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

已有脚本默认构建 `linux/amd64,linux/arm64`，同时推送 Git 短哈希与 `latest`；需要支持多平台的 Buildx 构建器。只构建单平台时可显式设置 `PLATFORMS=linux/amd64`，不要无意覆盖已经发布的多架构 `latest`：

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

Linux Docker 主机上的实际容器检查：

```bash
QA_DOCKER_IMAGE=wusaqi-gallery:local python qa/regression.py
QA_DOCKER_IMAGE=wusaqi-gallery:local python qa/container-memory.py
QA_DOCKER_IMAGE=wusaqi-gallery:multi QA_DOCKER_PLATFORM=linux/arm64 \
  QA_STARTUP_TIMEOUT=120 QA_REQUEST_TIMEOUT=180 python qa/container-smoke.py
```

本次 Windows 构建机使用 WSL 2 中的专用 `wusaqi-build` Ubuntu 和 Docker Engine；PowerShell 可通过 `wsl -d wusaqi-build -u root -- docker version` 检查环境。项目的本地预览仍使用 `http://127.0.0.1:8010`，现由真实容器运行。WSL 的系统组件和 Docker daemon 占用不属于应用容器的常驻内存。

本地开发时保持一个 WSL 会话运行：仅有 systemd 后台服务时，WSL 可能自动退出，容器和 `/run` 中的临时认证会随之停止或清除。实际 Linux VPS/NAS 部署没有这个 Windows 会话要求。

Docker Hub Overview 上传 `docs/dockerhub-description.md` 的完整内容，short description 使用上文建议；GitHub About 同步更新。凭据不足时保留已生成的介绍文件，不能把本地生成冒充线上更新。
