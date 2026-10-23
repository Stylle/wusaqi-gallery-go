# wusaqi-gallery-go

轻量、自部署的图片画廊与随机图 API。保留完整的 Vue 3 界面，用 **Go 单进程 + SQLite** 提供页面、图片和接口；Pillow 仅在处理图片时启动，完成即退出。适合 NAS、小内存 VPS 和个人图床。

> Docker Hub 的 `latest` 已更新为 Go 架构，支持 `linux/amd64` 和 `linux/arm64`。当前发布版本为 `67fa611`；旧 Python 镜像保留为 `legacy-python-20261023`。升级前请备份整个 `data/` 目录。

## 有哪些功能

| 功能 | 说明 |
| --- | --- |
| 画廊 | 瀑布流、灯箱、三档网格、仅看我的、标签筛选；滑到页面底部自动加载下一批，无翻页按钮 |
| 图片链接 | 保留原图、压缩版、WebP 缩略图三种 URL；复制、下载、重命名与删除 |
| 标签 | 画廊只显示实际有图片的标签；图片菜单可编辑或清空标签；后台标签池作为上传候选保留 |
| 上传 | 拖拽、多选、剪贴板粘贴、逐文件进度和压缩大小；JPG/PNG/WebP/AVIF/GIF/BMP，GIF 保留动图 |
| 压缩 | 自动探测机器或选择轻量/均衡/标准/自定义；格式、质量、宽度、像素上限、并发上限；支持用户覆盖 |
| 随机图 | JSON 或 302 直链，可选原图/压缩图；默认登录后使用，也可在后台公开 |
| 用户 | 管理员和普通用户；容量、单图大小、日/周/月上传数量；停用、改密、删除及图片转交 |
| 后台 | 站点标题、图标、页脚、分享域名、上传、压缩、防御、通知、用户与备份，保存后热生效 |
| 本地图库 | 扫描已有文件、后台导入、进度、取消、失败重试、补齐缺失缩略图和压缩版 |
| 防御与统计 | 随机接口限流、登录防爆破、临时封禁、IP/CIDR 黑白名单；最近三天 PV/UV 与热门路径 |
| 通知 | Webhook 方法/请求头/正文模板，事件开关，日报/周报/月报与测试发送 |
| 备份 | 在线 SQLite 快照与全部图片 ZIP；校验后恢复，恢复完成需重新登录 |
| 外观 | 中英切换、亮色/暗色/跟随系统、纯色/渐变，保留手机导航和后台抽屉 |

图片、数据库与配置都在本地。核心功能无需外部数据库、Redis 或云存储。公网 IP 归属地查询使用 ip-api.com；Webhook 仅在配置后投递。

## 为什么换架构

旧镜像同时常驻 nginx、supervisor、Python/FastAPI，且请求线程各自保留 SQLite 连接和页缓存。新版由一个 Go 进程处理 HTTP 与文件流，SQLite 固定一条连接、2 MiB 页缓存；上传内容写临时文件，图片任务单独启动并在完成后退出，避免图像解码器长期保留内存。

```text
浏览器 / API 客户端
         │ :8300 → 容器 :80
         ▼
  Go 服务（唯一常驻应用进程）
    ├─ Vue 静态页面、图片文件流、API
    ├─ SQLite /data/metadata.db
    └─ 按需 Pillow 子进程 → 缩略图 / 压缩图 → 退出
```

目标是**不处理图片时约 20–70 MB，尽可能更低**；这是验证目标，不是所有机器上的硬保证。`GOMEMLIMIT=40MiB` 是 Go 运行时的软限制，不能当作整个容器内存上限。上传、压缩、导入、备份，以及 Linux 文件缓存会影响测量。架构评估、实测口径与复现步骤见 [架构与内存说明](docs/architecture.md)。

本机真实 Docker 容器测试（WSL 2 / amd64）：一万条图片元数据、16 并发、1024 次请求，空闲 **10.52 MiB**，浏览后 **15.28 MiB**，大图上传完成后回落到 **14.98 MiB**。限制为 1 核 / 512 MiB 时，三阶段约 **10.05 / 13.53 / 13.88 MiB**。上传处理峰值单独计量；原始数据和平台限制见上方架构说明。

## Docker 部署

镜像：[stylle/wusaqi-gallery](https://hub.docker.com/r/stylle/wusaqi-gallery)。可直接使用下面的 Compose；需要自行构建时使用下一节的源码方式。

```yaml
services:
  gallery:
    image: stylle/wusaqi-gallery:latest
    container_name: wusaqi-gallery
    restart: unless-stopped
    ports:
      - "8300:80"
    volumes:
      - ./data:/data
    environment:
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: change-me-please
      ADMIN_SYNC: "0"
      RATE_LIMIT: "120"
      TZ: Asia/Shanghai
      GOMEMLIMIT: 40MiB
      GOGC: "50"
```

执行 `docker compose up -d`，访问 `http://主机IP:8300`。飞牛、群晖、Portainer 可粘贴同一份 Compose。`./data` 建议换成主机的绝对路径。只改端口映射左侧，对内仍使用 80。

仓库提供 [镜像版 Compose](docker-compose.hub.yml)，包含健康检查。升级和看日志：

```bash
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
docker compose -f docker-compose.hub.yml logs -f
```

发布脚本同时推送 `latest` 与 Git 短哈希标签。回滚时将 `image` 改为已发布的哈希标签；数据库如已执行恢复或修改，应同时使用升级前的数据备份。

### 从源码构建

```bash
git clone https://github.com/Stylle/wusaqi-gallery-go.git
cd wusaqi-gallery-go
cp .env.example .env
# 编辑 .env，设置初始管理员密码
docker compose up -d --build
```

整个部署仍只有一个容器、一个端口、一份数据卷。Dockerfile 自带健康检查，无需额外 Python 探活进程。

## 从旧 Python 版本升级

1. 停止旧服务，备份**整个** `data/` 目录；保留当前镜像标签，方便回滚。
2. 用新版镜像启动，继续挂载原来的 `/data`，保持 `8300:80`。不要同时运行两个实例写同一份 SQLite。
3. 新版自动补齐旧表字段，保留已有账号、密码、会话、站点设置、图片归属和文件路径。已有账号不会被环境变量覆盖，除非主动设置 `ADMIN_SYNC=1`。
4. 登录后检查画廊、随机图、后台和备份。未使用的标签会从画廊消失，但上传标签池仍可在后台编辑。

旧库的 `uploads/uploads/日期/...` 层级会原样保留，不要手动移动文件；分享链接继续有效。旧版本导出的整站 ZIP 也可恢复。恢复会替换数据库和三份图片目录，归档中没有的现有文件不会保留；先备份当前数据。

清理了无人使用的 `/api/admin/upload`、`/api/admin/reindex` 两个旧别名；分别改用 `/api/upload`、`/api/admin/local/import`。画廊随机排序参数不再提供，随机出图继续使用 `/api/random`。普通 `page/limit` 读取仍兼容，页面自身改用游标滚动加载。

## 配置与使用

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `ADMIN_USERNAME` | `admin` | 首次建库创建的管理员用户名 |
| `ADMIN_PASSWORD` | `changeme` | 首次建库密码；部署时设置自己的密码 |
| `ADMIN_SYNC` | `0` | 救援开关：设 1 重启，用环境变量覆盖已有管理员账密，完成后改回 0 |
| `WEB_PORT` | `8300` | 源码 Compose 的主机端口 |
| `RATE_LIMIT` | `120` | 首次建库的随机接口每 IP 每分钟上限；已有库以后台设置为准，0 关闭 |
| `TZ` | `Asia/Shanghai`（镜像） | 日志、统计与定时通知的时区 |
| `GOMEMLIMIT` | `40MiB` | Go 运行时软内存限制；不包含图片子进程与文件缓存 |
| `GOGC` | `50` | 垃圾回收频率，在 CPU 与内存之间取舍 |
| `TRUSTED_PROXIES` | 空 | 可信反代 IP/CIDR，逗号分隔；默认忽略客户端伪造的真实 IP 请求头 |
| `DATA_DIR` | `/data`（镜像） | 数据目录 |
| `LISTEN_ADDR` | `:80`（镜像） | 服务监听地址，本地开发默认 `127.0.0.1:8000` |
| `WEB_DIR` / `IMAGE_WORKER` / `PYTHON` | 镜像内置 | 裸机运行时可覆盖页面目录、图片任务脚本和 Python 解释器 |

其他配置都在后台保存到 SQLite 并热生效。管理员不受业务上传配额限制；普通用户的单图上限 0 表示跟随全局，全局单图上限 0 表示不限（HTTP 上传请求仍有 200 MiB 保护上限）。日/周/月是最近 24 小时/7 天/30 天的滚动上传数。

反向代理部署时，填写 `TRUSTED_PROXIES` 并让代理发送 `X-Real-IP` 或 `X-Forwarded-For`。原来的“内网不封禁”规则保留；如果请求实际来自内网代理而未正确传递公网 IP，限流将按内网请求处理。

上传后可在图片上右键或长按：复制原图/压缩图/缩略图链接、下载、重命名、编辑标签、删除。原图不变，压缩配置只影响后续上传；已有图片缺少衍生文件时，可到“本地图库”补齐。

标签池和图片标签相互独立：从标签池移除一个候选，不会批量清除图片已有标签；清空最后一张图片的标签，画廊的对应筛选项会自动消失。

## API

除公开接口外使用 `Authorization: Bearer <token>`，token 来自账号密码登录。

```text
GET    /api/health
GET    /api/public/settings
GET    /api/tags                          # 仅返回 count > 0 的图片标签
GET    /api/images?limit=36&cursor=...     # 返回 items/total/hasMore/nextCursor
                                         # 可加 tag=...、mine=1（需登录）
GET    /api/random?variant=compressed|original[&redirect=true]
GET    /api/random/image?variant=...      # 302，不缓存随机结果
POST   /api/auth/login                    # {username,password,remember}
POST   /api/auth/logout
GET    /api/auth/me
POST   /api/auth/password                 # {old,new}
POST   /api/upload                        # multipart files、tag
PATCH  /api/images/{id}                   # {filename} 或 {tag}，空 tag 清除
DELETE /api/images/{id}
GET/POST/PATCH/DELETE /api/users[/{id}]    # 管理员
GET/PUT /api/admin/settings
GET    /api/admin/system
GET    /api/admin/stats
GET/POST/DELETE /api/admin/bans[/{ip}]
POST/DELETE /api/admin/whitelist[/{IP或CIDR}]
POST/DELETE /api/admin/blacklist[/{IP或CIDR}]
GET    /api/admin/local/scan?limit=50
POST   /api/admin/local/import
GET    /api/admin/local/status
POST   /api/admin/local/import/cancel
POST   /api/admin/local/compress?dry_run=true&limit=5
GET    /api/admin/backup/stats
GET    /api/admin/backup
POST   /api/admin/restore                 # multipart file=.zip
POST   /api/admin/notify/test
```

滚动读取时，将上次响应的 `nextCursor` 原样传回；切换标签或仅我的条件时从空游标重新开始。`hasMore=false` 即结束。新上传的图片在刷新后出现，删除已读图片不会导致后续重复或跳过。

随机图公开后可直接用于 Markdown：

```markdown
![random](https://你的域名/api/random/image?variant=compressed)
```

## 本地运行和验证

需要 Go ≥1.26、Node.js ≥22、Python ≥3.11。先构建前端和 Go 服务，再运行，无需 Docker。

```bash
cd frontend
npm ci
npm test
npm run build
cd ../server
go build -trimpath -ldflags="-s -w" -o gallery .
cd ..
python -m venv .venv
# Linux/macOS: .venv/bin/python；Windows: .venv/Scripts/python.exe
.venv/bin/python -m pip install -r backend/requirements.txt
cd server
ADMIN_USERNAME=admin ADMIN_PASSWORD=local-test PYTHON=../.venv/bin/python ./gallery
# http://127.0.0.1:8000
```

Windows PowerShell 可使用 `scripts/dev.ps1`，它会在项目内准备工具依赖、构建并启动本地服务；首次执行前安装好 Go、Node.js 和 Python。

开发前端时，在 `frontend/` 执行 `npm run dev`，默认将 API 和图片代理到 `127.0.0.1:8000`。生产页面由 Go 服务直接提供。

```bash
cd server && go test ./... && go vet ./...
cd ..
python qa/regression.py
python qa/check-compose.py
python qa/memory-benchmark.py
```

回归使用 `.qa-data` 内的独立临时数据，覆盖旧库迁移、权限、上传、标签、游标、配额、防御、导入、备份恢复和重启。内存测试额外需要 `psutil`，结果不包含浏览器、编译器和 Node 开发服务器。

后台 14 个栏目的界面与功能验收、手机端设计修复及对应测试范围，见 [验收记录](docs/qa-review.md)。

## 项目结构与发布

```text
server/               Go 服务、SQLite schema、默认配置、压缩档位
backend/image_worker.py  按需图片处理，无常驻 Python Web 服务
frontend/src/         原 Vue 页面、样式、主题与中英文案
qa/                   HTTP 回归、部署契约、内存测试
docs/                 架构说明、Docker Hub 介绍、历史规划
scripts/              本地启动、文档同步、镜像发布
Dockerfile            Vue 构建 → Go 构建 → Go + 按需 Pillow 运行环境
```

维护者发布流程见 [发布说明](docs/release.md)。`README.md` 是介绍的主源，执行 `python scripts/sync-docs.py` 生成 Docker Hub 版文档，发布时同步上传。构建镜像和更新 GitHub/Docker Hub 元数据需要维护者自己的登录授权。

历史 `PLAN` 文档只记录旧版本设计，以当前源码和本 README 为准。

## 使用范围

沿用项目原有约定：仅供个人学习与自部署使用。仓库未新增开源许可证授权。
