# 维护者发布

发布前使用独立测试数据完成容器功能、迁移、图片处理与内存检查；镜像标签与源码提交对应，凭据只交给官方认证接口或 Docker CLI，不写入源码、镜像层和日志。

## 2026-11-13 发布记录

菜单优化 `1872855`：手机账户与导航菜单互斥，支持外部点击/Escape 收起；移除账户菜单中的重复上传入口；顶栏触控区域为 44×44，抑制双击放大并保留双指缩放。后台 16 项使用四字短标题、独立图标列和五组导航，桌面侧栏独立滚动、手机抽屉关闭时不可聚焦。

- 镜像 `stylle/wusaqi-gallery:1872855` / `:latest`（amd64、arm64），索引 `sha256:f093bfa19f96f94c591431c2d1a7a578265ff6af743f574080e2c72ee7110326`。
- 前端 19 项及生产构建通过；16 个面板逐项浏览器验收、8 次连续菜单切换互斥验证通过。Windows、Linux、Docker CI 全部通过：[43409184664](https://github.com/Stylle/wusaqi-gallery-go/actions/runs/43409184664)。两个架构各 13 项部署检查与注册表按摘要拉取后 13 项检查通过。
- 本地 8010 预览同步更新，保留站点名称、用户、图库和设置；使用指南已更新菜单路径。本次未改服务端代码、数据结构与图片处理流程。

标题修复补丁 `cdeab38`：站点名称由服务器写入首屏 HTML，Vue 继承该标题初始化顶栏，刷新时不再短暂出现默认品牌；标题包含特殊字符时按文本转义。管理员图库开关缩短为“隐藏”，私密标签及访问权限保留。

- 镜像 `stylle/wusaqi-gallery:cdeab38` / `:latest`（amd64、arm64），索引 `sha256:5556c7c62f4b1038862e4a31fa905489374bef953299a5cd8a3d8b93fc9de81e`。
- 33 项 Go、19 项前端与生产构建通过；Windows、Linux、Docker CI 全部通过：[43400491459](https://github.com/Stylle/wusaqi-gallery-go/actions/runs/43400491459)。两个架构各 13 项部署检查通过，注册表按摘要拉取后再次通过 13 项检查。
- 本地 8010 已更新，保留当前自定义站点名“测试图床”、图库和登录；浏览器确认页签/顶栏一致、开关为“隐藏”。

- 功能源码 `accdf16`（含 `3a8ab48`）：修复主题选中与刷新配色闪烁；补充跟随系统图标，宽屏画廊自适应、手机列数保留；新增中英文关于页、GitHub/指南入口及上下滚动悬浮按钮，隐藏页面外层原生滚动条。
- 纯色/炫彩在服务器输出 HTML 时确定，亮暗偏好在样式加载前解析；配置更改后的条件刷新不复用旧 HTML。静态关于页面公开，关闭站点公开访问后图库仍受登录保护。
- 镜像 `stylle/wusaqi-gallery:accdf16` / `:latest`，支持 amd64、arm64；上版 `ce2f991` 保留。索引摘要 `sha256:0d485fdef1d37c79035c67e6579f71f8f07ac7527362b5bcd4bf4be8a8394128`。
- Go 32 项、前端 18 项及生产构建通过；Windows、Linux、Docker 全部 CI 通过：[43398747430](https://github.com/Stylle/wusaqi-gallery-go/actions/runs/43398747430)。实际 amd64/arm64 容器各 12 项部署检查通过，注册表按摘要拉取后再次通过 12 项检查。
- 本地 8010 预览已替换为新镜像，保留原有 83 张样本图库、账号与设置；README、使用指南和 Docker Hub Overview 同步更新。本次没有改动图片处理流程或数据库结构，也没有重测内存，已有内存记录保留原测量版本。

## 2026-11-12 发布记录

- 功能源码 `ce2f991`：新增管理员专用 Telegram 机器人，私聊 `/random`、`/random 标签名`、`/tags`；五分钟一次性绑定、实时管理员角色校验与解除绑定。普通用户、群聊及频道请求没有回复。
- Token 保存后不回显；私密图默认关闭，开启后仅明确指定 `/random 私密` 可取。Go 长轮询复用现有进程，直接流式发送文件，无需开放站点、图片外链或新端口。
- 镜像 `stylle/wusaqi-gallery:ce2f991` / `:latest`，支持 `linux/amd64` 与 `linux/arm64`；旧版本标签保留。
- 索引摘要 `sha256:653f3cf452da360d51bdf3aa45cddbff2f0bb4321119385b0f56ab8188d63cb1`；amd64 `sha256:20300499811341306bf65b2c5b25f7e45b94669c5a96e2b6891a03199109846d`；arm64 `sha256:ca3e9f0631dda3c1ad814818620d222a493e53980104ca587a0bd42f8c1ee872`。
- 本地 31 项 Go、13 项前端行为、355 项 HTTP 与 26 项部署检查通过；Windows、Linux、标准 Dockerfile 容器 CI 全通过：[43193234350](https://github.com/Stylle/wusaqi-gallery-go/actions/runs/43193234350)。本机最终镜像全部 355 项服务检查通过，修正一个旧测试的暂停时序后额外连续三次验证清理队列。
- ARM64 的 7 项新增 Telegram 专项测试与 12 项部署冒烟通过；Docker Hub 实际拉取后 12 项冒烟通过。真实 Telegram Token 未提供，尚未进行真实账号收图联调；完成配置步骤见 [接入指南](guide.md#telegram-管理员机器人)。
- 默认容器稳态 10.99 / 16.48 / 17.09 MiB；1 核 / 512 MiB 为 10.34 / 14.68 / 15.09 MiB，机器人使用默认关闭配置。测量口径、处理峰值及原始数据见 [内存记录](architecture.md#2026-11-12-telegram-版实测)。
- 保留远端已整理的简洁 README、最简 Compose 和完整指南结构；完整功能和接入说明写入使用指南，Docker Hub 介绍继续从 README 自动生成。
- 本地下载大模块时网络停滞，最终构建仅在 builder 阶段预填已校验的 Go 模块缓存；运行层、依赖版本与源码不变，标准 Dockerfile 的正常构建由上述 CI 验证。

## 2026-11-03 发布记录

- 功能源码 `217c38f`，包含私密标签、管理员显示开关、站点公开访问、外链总开关和标签规则、版权联系说明。
- 上传与新导入自动去除个人照片元数据；后台可一键清理已有图库，支持持久化分批、暂停/继续、最多三次自动重试、失败项重试和文件/数据库失败回滚。
- 镜像 `stylle/wusaqi-gallery:217c38f` / `:latest`，支持 amd64、arm64；上版 `b0f4613` 保留。
- 索引 `sha256:9e69c7b229585d18858731205b6b5c2aaec88226aa31d0bfc815ba1d078ff491`；amd64 `sha256:44c6a4dc6bfaf60fd9bde117be05673f59340d916b91ad93c4acaa950954b136`；arm64 `sha256:5cdacb64b28bbeb2da6959c2305bcff81f1692667adaf2c57342ea0c1b53fb93`。
- 实际 amd64 Docker 共 355 项服务检查通过；24 项 Go、13 项前端、26 项部署检查通过。Windows、Linux、Docker CI：[41649141179](https://github.com/Stylle/wusaqi-gallery-go/actions/runs/41649141179)。
- ARM64 113 项照片与动画清理检查、注册表拉取后 12 项部署冒烟通过；浏览器独立样本库 83 张全部完成清理，失败为零。
- 默认容器稳态 12.31 / 16.25 / 16.20 MiB；1 核 / 512 MiB 为 10.78 / 14.69 / 14.47 MiB。图片处理峰值单独计量，原始报告见架构文档。
- 升级只迁移数据库字段，不自动改写历史图片；已有任务保留。管理员可先备份，再在后台启动历史图片信息清理。

## 2026-11-02 发布记录

- 功能源码提交 `b0f4613`；补齐队列持久化、自动分批执行全部、暂停/继续与最多三次自动重试。
- 新上传页使用分块续传、分块及整图 SHA-256、完成凭证与防重复提交。失败暂存不进入图库，可继续、重试或取消，过期自动清理。
- 镜像 `stylle/wusaqi-gallery:b0f4613` / `:latest`，支持 amd64、arm64；上一版 `e5adfe8` 保留。
- 索引摘要 `sha256:b90c7bfd5e2b0bde238c6d2acb60827a692fff651dc5fd946a79df74c17cd477`；amd64 为 `sha256:fb0a20a2e306070cd7cc8b74ea1b03aa1d6a47fa5cb459da91982f38d4e57d50`，arm64 为 `sha256:8c6fee019ed91985ceef8ffdb77f6123fb7136ea3743d0ad24ef7de0317ed59b`。
- 18 项 Go、11 项前端行为与 26 项部署契约检查通过；原有 89 + 39 项及新增 41 项 HTTP 检查纳入 Windows、Linux 与 Docker CI。ARM64 冒烟检查通过。
- 当前默认容器稳态约 9.89–15.67 MiB，1 核 / 512 MiB 约 10.09–14.27 MiB；峰值及原始报告见 [架构文档](architecture.md)。
- 新表自动建立，已有原图、链接、用户和站点设置保留。旧 `POST /api/upload` 保持同步兼容；第三方客户端要续传需切换到 `/api/uploads`。

## 2026-10-25 发布记录

- 源码提交：`e5adfe8`，新增画廊批量选择、标签设置/清空、原图 ZIP、逐项批量删除结果；后台索引检查/重建、生成文件清空；随机 API 标签参数。
- 镜像：`stylle/wusaqi-gallery:e5adfe8` 和 `:latest`，支持 `linux/amd64`、`linux/arm64`。
- 镜像索引摘要：`sha256:371a4b94b50f56b4ab08814cd24d0c00ba01520be8de684fee8ab4c6080c07a1`。
- amd64：`sha256:fed69e85b5ed785764944b2f70d79634f3e1acac03c6cf6b05402589a9796762`；arm64：`sha256:70285f45f69a72f0bf0c29ff19a67faefad79b5c172fe3fb661669b18860fcf7`。
- 本机及 amd64 容器均通过 89 项原有回归与 39 项新增功能检查；ARM64 12 项冒烟通过；上传后拉取验证 12 项通过。
- 默认容器稳态约 10.54–15.44 MiB，1 核 / 512 MiB 约 9.95–14.50 MiB，上传峰值单独计量。原始记录见 [架构与测量](architecture.md)。
- 上一版 `67fa611` 标签保留，数据格式兼容；回滚前仍需核对并备份业务数据。

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

> 轻量自部署图片画廊与随机图 API。Go + Vue + SQLite，管理员 Telegram 机器人、私密标签、断点上传与后台图片队列，单容器部署。

Docker Hub short description（不超过 100 字符）：

> Go + Vue + SQLite gallery. Admin Telegram bot, private tags, resumable uploads, metadata cleanup.

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
python qa/reliability.py
python qa/privacy.py
python qa/metadata.py
python qa/metadata-cleanup.py
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

Windows 可使用具有 Docker Engine 的 WSL 2 发行版构建，发行版名称由部署者自行选择。先在所选 Linux 环境执行 `docker version`，确认客户端与服务端均可用。WSL 系统组件及 Docker daemon 的占用不属于应用容器常驻内存。

本地开发时保持一个 WSL 会话运行：仅有 systemd 后台服务时，WSL 可能自动退出，容器和 `/run` 中的临时认证会随之停止或清除。实际 Linux VPS/NAS 部署没有这个 Windows 会话要求。

Docker Hub Overview 上传 `docs/dockerhub-description.md` 的完整内容，short description 使用上文建议；GitHub About 同步更新。凭据不足时保留已生成的介绍文件，不能把本地生成冒充线上更新。
