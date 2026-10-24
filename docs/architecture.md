# 架构评估与内存验证

本文评估的是当前项目的功能、数据兼容和常驻内存，不把上传压缩峰值当作常驻占用。用户提供的旧 Docker 部署约 176 MB 是生产观测；下文分别记录 Windows 进程工作集和 WSL 2 中的真实 Docker cgroup 测量，不跨环境直接相减计算优化比例。

## 原实现中的开销

- Dockerfile 同时安装并启动 nginx、supervisor 和 Python/uvicorn。
- FastAPI 同步路由交给线程池处理，`db.py` 使用线程本地 SQLite 连接，所有连接被 `_conns` 保留；每条连接有自己的缓存，且没有设置页缓存总预算。
- Pillow 与 Web API 在同一 Python 进程内。解码、缩放与编码产生的内存释放后，进程和原生分配器未必立即把所有页面交还系统。
- 请求使用的配置反复查库；导入和补压缩会物化整份图库记录/待处理文件列表；限流和通知线程缺乏统一的固定容量管理。

这些是代码中可确认的开销来源。没有旧生产容器的逐进程/cgroup 数据，不能断言其中某一个因素独自造成了 176 MB。

## 候选方案

| 方案 | 对本项目的影响 | 判断 |
| --- | --- | --- |
| 精简 FastAPI + 单 worker | 改动小；限连接、限制缓存、懒导入 Pillow、精简 uvicorn 依赖可改善，解释器与 Web 框架仍常驻 | 适合小步优化，但没有证据保证能长期低于目标上限 |
| Go `net/http` + SQLite + 按需图片进程 | Vue 页面不变；HTTP、静态文件和后台任务共用一个常驻服务；沿用数据库和密码格式；图像内存与服务分离 | **本次采用**，本机实测达到常驻目标 |
| Rust + SQLite + 图片处理 | 也可实现低常驻内存；需要重写全部业务并重新验证各图片编码器、备份和部署链路 | 可行，但相对当前体量缺少足够收益证据来增加实现成本 |
| Node.js + SQLite | 与 Vue 同语言，但 V8 与运行时仍常驻；未实测，不能凭语言保证更低内存 | 不作为本次首选 |
| Redis/数据库独立服务/微服务 | 增加额外常驻进程、网络与运维配置 | 本项目没有必要 |

选择 Go 是因为业务主要是 SQLite 元数据、文件流和少量后台任务。页面仍使用 Vue 3，保留全部管理界面、主题、中英文案和配置键；避免把整个前端也重写造成额外风险。

## 实现边界

1. 只有 Go 服务常驻。Python 和 Pillow 作为镜像内的文件存在，不在空闲时启动；每个图片任务结束后子进程退出。保留 Pillow 是为了兼容 WebP/AVIF/GIF/EXIF 与现有压缩参数，而不是把 Python Web 服务留在后台。
2. SQLite 连接池限制为 1，WAL，页缓存建议值 2 MiB，关闭 mmap，临时 SQL 数据允许写磁盘。并发 HTTP 请求可以并存，SQL 操作在一个连接上排队。小规模自部署图库优先选择稳定占用与一致性。
3. `GOMEMLIMIT=40MiB`、`GOGC=50`，减少 Go 运行时保留的内存。该配置是软限制，不能限制 Pillow 子进程，也不等于 RSS 或 Docker cgroup 的硬上限。[Go GC 官方说明](https://go.dev/doc/gc-guide)。SQLite 页缓存与 mmap 的配置含义见 [SQLite PRAGMA 文档](https://www.sqlite.org/pragma.html)。
4. 图片上传解析只保留小型 multipart 缓冲区，文件放磁盘；文件与 ZIP 使用流式复制。恢复时先在数据卷内校验、迁移归档数据库，再切换，失败回滚。大备份需要足够磁盘空间容纳归档、展开数据与切换期间的旧数据。
5. API 写入串行，避免配额、图片重命名、备份快照与导入相互竞争。压缩配置的并发数保留为上限，当前写入串行策略可能使实际并发更低；这符合低内存部署目标。
6. 补压缩按 100 条元数据扫描；本地目录逐个遍历，不把整份图片列表读入服务内存。失败导入队列仍持久化在设置表，保留旧数据格式。
7. 随机限流与登录计数最多保留 4096 个客户端状态，每个状态固定 60 个计数桶；随机接口约 1 秒粒度、登录失败约 10 秒粒度。通知队列最多 32 条，单消费者投递，避免每个事件新建线程。
8. 图片使用长缓存，随机图 API 使用 `no-store`；静态资源由 Go 直接读取，不再绕一层反向代理。

## 功能与迁移核对

| 原功能 | 新实现 |
| --- | --- |
| 五个页面、灯箱、菜单、移动端后台、亮暗/渐变、中英 | 原 Vue 页面继续使用，新增滚动加载、错误重试与标签编辑 |
| 所有后台设置键与压缩档位 | `server/defaults.json` / `profiles.json` 沿用，热更新；非法值返回 400 |
| SQLite/原图/缩略图/压缩图 | 复用原数据卷，旧路径、图片 ID 与分享链接保留 |
| PBKDF2 密码与会话 | 兼容原编码与到期时间；启动时不会默认覆盖旧密码；恢复后清空会话 |
| 多用户、配额、单图限制、滚动上传数 | 保留；修复 0 上限与最后一个启用管理员的保护 |
| 本地导入、补压缩、重试、取消 | 后台任务，启动状态先锁定，避免重复任务竞态；GIF 不误判为缺压缩版 |
| 防御/名单/通知/统计 | 保留；真实 IP 仅信任显式配置的代理；修复昨日统计包含今日的问题 |
| ZIP 在线备份和恢复 | 快照兼容原归档；拒绝路径穿越和符号链接，展开总量最多 20 GiB |
| `/api/admin/upload` / `/api/admin/reindex` | 删除无前端调用的旧别名；使用 `/api/upload` / `/api/admin/local/import` |
| 列表的随机排序 | 删除无页面调用、无法稳定滚动翻页的排序参数；随机图功能保留 |

画廊的空标签问题来自旧 `/api/tags` 把配置标签池和实际图片标签合并。新版接口只返回正在使用的标签；上传候选单独读取原 `site_tags`，不会擅自清空管理员配置。

## 本地实测

测试平台：Windows 11，Go 1.27.3，Python 3.12。旧版对照使用重构前 Git 版本的 Python 代码，不运行 nginx/supervisor；依赖为 FastAPI 0.161.1、uvicorn 0.54.0、Pillow 13.0.0。该对照不等于旧生产镜像。

相同测试集：10,000 条图片元数据、83 份真实小图片文件、16 并发执行 1024 次列表/标签/公开设置/用户信息请求，随后上传一张 3500×2200 BMP，再观察 5 秒。读取独立服务进程树的 RSS/Windows working set，不包含浏览器、Node、编译器和测试客户端。

| 阶段 | 旧 Python 服务（MiB） | Go 服务（MiB） |
| --- | ---: | ---: |
| 空闲 | 57.30 | 18.78 |
| 1024 次请求后 | 75.61 | 25.39 |
| 大图上传后回落 | 70.36 | 25.85 |
| 上传时整个进程树峰值（不计入常驻目标） | 181.11 | 142.81 |

表中使用最终锁定的 Pillow 13.0.0；处理完成后没有遗留图片子进程。Go 的 Windows private bytes 对应约 55.25 / 61.76 / 61.87 MiB，与工作集不是同一个指标，同样在 70 MiB 内。Windows 虚拟环境的解释器启动器会临时产生两个进程 ID，这不代表并行处理了两张图片。

本次 `go test ./...`（14 项）、`go vet ./...`、4 项前端行为测试、前端生产构建、89 项 HTTP 端到端检查与 26 项部署契约检查通过。浏览器实测 83 张图片按 36 → 72 → 83 自动加载；标签新增、清空和后台移动端抽屉可用。Linux amd64/arm64 已通过交叉编译。后续全站检查与修复见 [后台和设计验收记录](qa-review.md)。

原始输出由 `qa/memory-benchmark.py` 保存到本地 `artifacts/memory-windows.json`；本次结果也保存在 [Go 原始记录](benchmarks/windows-go.json) 和 [旧 Python 对照记录](benchmarks/windows-legacy.json)。旧服务可用 `--legacy-python` 和 `--legacy-backend` 指向独立的旧代码与解释器复测。

## Docker 容器实测

2026-10-23 在本机 WSL 2（Linux 6.18.33.2）、Docker Engine 29.9.2、cgroup v2 中构建并运行实际部署镜像。amd64 镜像通过全部 89 项 HTTP 回归；arm64 镜像通过 QEMU 执行的 12 项检查，覆盖页面、旧账号与数据、上传、三种图片链接、配置、备份、健康检查和重启。ARM 模拟结果只用于功能兼容验证，不代表真实 ARM 主机性能或内存。

与 Windows 测试相同的数据与负载：10,000 条元数据、83 个实际文件、16 并发、1024 次请求，以及一张 3500×2200 BMP。Docker 占用按照 `memory.current - inactive_file` 计算，与 Docker CLI 的 Linux 缓存扣除口径一致；CLI 在相邻时刻采样会有少量差异。

| 阶段 | 默认资源 Docker 占用（MiB） | 1 核 / 512 MiB 限制 Docker 占用（MiB） |
| --- | ---: | ---: |
| 空闲 | 10.52 | 10.05 |
| 浏览压力后 | 15.28 | 13.53 |
| 上传完成后 5 秒中位数 | 14.98 | 13.88 |
| 上传时峰值，单独计量 | 121.01 | 112.23 |

默认资源下服务进程 RSS 为 18.66 / 23.32 / 23.09 MiB；1 核 / 512 MiB 下为 17.65 / 22.21 / 22.36 MiB。两组均观察到一个临时图片子进程，处理完成后无残留。原始记录包含 cgroup anonymous/file memory 和 `docker stats` 输出：[默认资源](benchmarks/docker-amd64.json)、[1 核 / 512 MiB](benchmarks/docker-amd64-512m.json)。

测试数据通过 WSL 的 Windows 磁盘挂载进入容器。生产 Linux 文件系统、文件缓存归属、CPU 数量和图像尺寸会影响结果，以上不是所有平台都固定为 10–15 MiB 的保证。WSL、Docker daemon 和浏览器自身的内存不计入应用容器。

## Docker 验收复现

Linux Docker 主机（包括 WSL 2）安装测试依赖后，可自动复现：

```bash
python -m pip install -r backend/requirements.txt psutil pyyaml
docker build -t wusaqi-gallery:local .
QA_DOCKER_IMAGE=wusaqi-gallery:local python qa/regression.py
QA_DOCKER_IMAGE=wusaqi-gallery:local python qa/features.py
QA_DOCKER_IMAGE=wusaqi-gallery:local python qa/container-memory.py
QA_DOCKER_IMAGE=wusaqi-gallery:local QA_DOCKER_CPUS=1 QA_DOCKER_MEMORY=512m \
  python qa/container-memory.py
```

脚本只使用 `.qa-data` 下的独立临时数据，默认不使用业务数据；报告写入 `artifacts/memory-docker.json`。功能测试使用 host 网络，以便容器访问本机 Webhook 接收器；不改变部署 Compose 的网络设置。

构建后，先启动独立测试数据卷，再分别观察空闲、浏览压力和上传结束后的占用：

```bash
docker build -t wusaqi-gallery:local .
docker run -d --name wusaqi-memory-test -p 18300:80 \
  -e ADMIN_PASSWORD=local-benchmark -v wusaqi-test-data:/data \
  wusaqi-gallery:local
docker stats --no-stream wusaqi-memory-test
docker top wusaqi-memory-test
# 压测、上传并等待处理结束，再重复 stats/top
docker inspect --format '{{json .State.Health}}' wusaqi-memory-test
```

应分别报告 Docker stats、cgroup anonymous/file memory 与稳态请求情况；不能把 Windows working set、Go heap、容器包含文件缓存的 usage 混为同一指标。镜像磁盘大小也不等于运行内存。

不建议把容器硬限制直接设成 70 MB：图片解码峰值明显高于常驻目标，硬限制会使上传 OOM。低配主机可在后台选轻量方案、保持低并发，按真实图片尺寸验证上传峰值。
