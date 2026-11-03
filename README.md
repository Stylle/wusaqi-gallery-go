# wusaqi-gallery-go

轻量、自部署的图片画廊与随机图 API。保留完整的 Vue 3 界面，用 **Go 单进程 + SQLite** 提供页面、图片和接口；Pillow 仅在处理图片时启动，完成即退出。适合 NAS、小内存 VPS 和个人图床。

> Docker Hub 的 `latest` 已更新为 Go 架构，支持 `linux/amd64` 和 `linux/arm64`。当前发布版本为 `217c38f`，新增私密标签、可撤销外链、上传照片元数据清理与已有图库的后台批量清理；旧 Python 镜像保留为 `legacy-python-20261023`。升级前请备份整个 `data/` 目录。

## 有哪些功能

| 功能 | 说明 |
| --- | --- |
| 画廊 | 瀑布流、灯箱、三档网格、仅看我的、标签筛选；滑到页面底部自动加载下一批，无翻页按钮 |
| 图片链接 | 原图、压缩版、WebP 缩略图；独立站内浏览路径，可撤销外链总开关与按标签控制 |
| 批量操作 | 登录后进入批量模式，多选或全选已加载图片；原图 ZIP 下载、统一设置/清空标签、批量删除，单次最多 500 张 |
| 标签 | 实际使用的标签筛选；内置「私密」标签仅管理员可读，管理员可选择显示；支持批量编辑 |
| 上传 | 拖拽、多选、粘贴、分块续传、完整性校验、网络重试与完成凭证；清除照片个人元数据后入库；JPG/PNG/WebP/AVIF/GIF/BMP，GIF 保留动图 |
| 压缩 | 自动探测机器或选择轻量/均衡/标准/自定义；格式、质量、宽度、像素上限、并发上限；支持用户覆盖 |
| 随机图 | JSON 或 302 直链，可选原图/压缩图、按标签精确随机；默认登录后使用，也可在后台公开 |
| 用户 | 管理员和普通用户；容量、单图大小、日/周/月上传数量；停用、改密、删除及图片转交 |
| 后台 | 站点公开访问、图片与标签外链权限、版权联系说明，以及外观、上传、压缩、防御、通知、用户与备份，保存后热生效 |
| 本地图库 | 扫描导入、检查/重建索引、清空生成文件；持久化补齐队列，一键补齐全部、自动分批、暂停/继续、失败重试 |
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

新版 `217c38f` 本机真实 Docker 容器测试（WSL 2 / amd64）：一万条图片元数据、16 并发、1024 次请求，空闲 **12.31 MiB**，浏览后 **16.25 MiB**，大图上传完成后回落到 **16.20 MiB**。限制为 1 核 / 512 MiB 时，三阶段约 **10.78 / 14.69 / 14.47 MiB**。上传处理峰值单独计量；原始数据和平台限制见上方架构说明。

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

上传后可在图片上右键或长按：复制原图/压缩图/缩略图链接、下载、重命名、编辑标签、删除。原图保留格式与显示分辨率，入库前清除个人元数据；压缩配置只影响后续上传；已有图片缺少衍生文件时，可到“本地图库”补齐。

标签池和图片标签相互独立：从标签池移除一个候选，不会批量清除图片已有标签；清空最后一张图片的标签，画廊的对应筛选项会自动消失。

### 私密标签、公开访问与外链权限

在上传或编辑标签时，管理员选择 **私密**，即可把图片设为仅管理员可读。画廊默认隐藏私密图片；管理员勾选「显示私密图片」后可筛选查看，取消勾选或退出登录即隐藏。普通用户即使是原上传者，也不能读取、修改或下载已被管理员标记私密的图片。

后台「公开访问与外链」提供以下独立设置，点击「保存全部设置」后生效：

| 配置 | 开启 | 关闭 |
| --- | --- | --- |
| 允许站点公开访问 | 游客可浏览非私密画廊 | 画廊、标签和随机 API 要求登录；全部公开图片外链停用，登录入口保留 |
| 允许图片外链 | 根据标签规则允许原图、缩略图、压缩图分享 | 已复制的三种外链均返回 404；已登录与公开站点的站内浏览仍正常 |
| 按标签允许外链 | 该标签可生成分享链接 | 该标签的旧外链失效；标签重设后按新标签权限处理；无标签图片也可单独控制 |

「私密」标签始终禁止外链，不受总开关放行。公开随机图 API 同时遵守站点与外链开关，跳过私密和禁止外链的标签；管理员默认随机也排除私密图片。站点公开访问与外链默认开启，随机图 API 默认要求登录，兼容旧部署行为。

站内图片使用 `/media/files/…`、`/media/thumbs/…`、`/media/compressed/…`，依靠同站 HttpOnly / SameSite=Strict Cookie 浏览。访客浏览凭证只能读公开站点的非私密图片；管理员凭证每次都核验会话、账号启用状态和权限。API 写入仍要求 `Authorization: Bearer …`，Cookie 不能替代它。`/files/…`、`/thumbs/…`、`/compressed/…` 是分享路径，每次请求核验现行规则，因此旧链接也受新开关约束；未入库的文件不会被当作公开媒体读取。

这些设置控制服务端后续访问，无法撤回已经下载的文件；公开画廊里看得到的图片仍可被访客保存。新版媒体响应不再长期缓存；如果旧版本图片已被浏览器或 CDN 按原来的 `immutable` 策略缓存，需清除那部分缓存才能立即向服务端重新校验。反向代理应把 `/media/` 转发给 Go 服务，避免直接暴露数据目录或自行缓存媒体。

后台「版权与联系」可设置版权/违规说明和联系方式，显示在所有页面底部；联系方式默认为空，请填写自己的邮箱、QQ 等内容。两项均以纯文字显示，留空隐藏，不会执行输入的 HTML。

### 上传照片的个人信息清理

新上传和新扫描导入的图片，在正式入库前自动清除 GPS 经纬度、拍摄时间、相机/手机型号、设备序列号、作者、EXIF/IPTC/XMP、编辑器注释、嵌入预览、ICC 配置及文件尾附加信息；原图、压缩图与缩略图均受保护。清理为默认必经步骤，没有公开原始文件的回退；失败的任务保持未入库状态，续传上传可重试或取消。

JPEG、PNG、WebP、GIF 通过过滤元数据块保留原有图像压缩数据，不重新压缩像素；保留显示所需的方向标记、透明度和动画帧/播放参数。BMP 从像素重新保存；AVIF 按帧校正方向后重新编码，动画中间帧写入临时目录，避免将全部帧同时常驻内存。AVIF 文件大小和编码结果可能变化，因此这里的「原图」是清理后的完整分辨率图片，不是源文件的逐字节备份。

断点续传仍对接收到的源文件做分块与整图 SHA-256 校验；清理结果写到独立暂存文件，成功后才提交图片与完成凭证。源文件校验值不会被清理后的文件替换，网络重试、任务续传和防重复提交保持有效；图片的存储大小与容量统计使用清理后的实际字节数。新上传文件的原始文件名不进入公开图片信息，上传任务中仅对上传者保留续传所需文件名；管理员手动命名/重命名的文件名和本地导入路径按原有方式保留。

已有图库可到后台「本地图库导入 → 后台图片任务」，点击 **清理全部图片个人信息**，确认后按每批 1–50 张自动清理全部原图及现有缩略图、压缩图。支持暂停、继续、失败重试，队列进度保存在 SQLite；关闭页面不影响执行，服务重启会恢复任务。单张失败最多自动重试三次；清理与补齐共用一个队列，需要先完成已有的暂停任务。

清理保留图片 ID、文件路径、标签、归属和入库时间，刷新文件的缓存版本并修正实际大小。所有可用版本先在独立目录清理成功，再原子替换；文件替换或数据库提交失败会回滚，失败明细保留在后台。缺失的缩略图/压缩图不会在这一步补建，可另用补齐功能；损坏文件会列为失败，原文件保留，可能仍含个人信息，敏感图片可先设为私密。

元数据清理后无法恢复，操作前可下载整站备份。升级本身不会自动改写历史原图，只有管理员启动清理任务才处理；新生成的缩略图和压缩图也会去除元数据。清除元数据不会自动擦除画面中的人脸、地址、路牌、水印等可见内容。

实现与测试依据：[Pillow 图片格式文档](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html)、[WebP 容器规范](https://developers.google.com/speed/webp/docs/riff_container)、[PNG 规范](https://www.w3.org/TR/png-3/)。

### 批量处理与索引维护

登录后点击画廊的“批量处理”，点击图片选择，或“全选已加载”；继续滚动可加载并选择更多图片，单次最多 500 张。下载会把原图打包为 ZIP；普通用户只能编辑/删除自己上传的图片，管理员可操作全部。标签操作统一替换所选图片的标签，留空即清除；批量删除会显示成功和失败数量，失败项保留选中便于重试。删除不可恢复，请先备份。

直接在服务器上删过文件后，进入后台“本地图库导入”→“检查索引”，查看原图、缩略图和压缩版缺失数量及明细。“重建索引”会重新核对磁盘，移除原图已不存在的记录及其衍生文件，并修正失效压缩图引用；已有图片的 ID、标签、归属和原图链接保持不变。未入库的新原图仍使用“扫描/导入”。挂载异常或权限问题应先恢复数据卷，避免把空目录误当成已删除图库。

需要更换生成格式或重做衍生文件时，点击“清空缩略图与压缩图”并确认；它仅清除生成文件，保留全部原图和元数据。随后使用同页的“补齐缺失缩略图和压缩版”。补齐前画廊会使用原图显示，流量相应增加；GIF 不生成压缩副本，不算缺失压缩版。导入任务运行期间不能执行索引维护，请先结束或取消导入。

“重建索引”依据现有数据库记录核对原图，并非遍历清除所有从未入库的孤立文件；“清空缩略图与压缩图”则清空两个生成目录中的**全部**文件。

### 自动补齐队列

检查缺失后设置“每批张数”（1–50，默认 5），点击“一键补齐全部”。服务器会逐张处理、每批完成后自动继续，直到本次队列结束；批量大小不等于并发数，不会同时解码几十张图。无需一直开着页面，也无需每批再点击。

队列与进度保存在 SQLite。可暂停/继续，暂停会等待当前图片结束；继续时可修改批量大小。运行中的队列在服务重启后继续，已暂停的保持暂停。每张失败最多自动重试 **3 次**（加首次共 4 次，间隔约 1/2/4 秒），耗尽后跳过并显示明细，其余图片继续；问题修复后可单独重试失败项。运行补齐期间禁止清空生成目录、导入和整站恢复，避免任务相互覆盖。

### 上传断线、失败与恢复

新版上传页按 **1 MiB** 分块发送，逐块 SHA-256 校验，并校验完整文件 SHA-256；校验和传输均分块读取，不把整个文件放入浏览器或服务端内存。每个网络请求最多自动重试 3 次，之后可点击继续；同一任务、同一分块和重复提交不会生成重复图片。

“上传完成”需同时满足：原图接收完整、完整性校验通过、图片处理成功、数据库及完成凭证一并提交。图片处理中会单独显示状态，不把传输 100% 当成成功。传输不完整或压缩失败的文件在 `/data/.incoming/` 私有暂存，不进入画廊、本地导入或备份；生成文件先写临时路径，再移入正式目录。失败处理同样最多自动重试 3 次；耗尽后保留错误和原始暂存，可取消或修复配置后重试处理。

网络中断或页面刷新后，重新打开上传页可查询最近 50 个任务。浏览器不会在刷新后自动保留本地文件权限：**未传完的任务需重新选择同一文件**，按服务端已确认位置续传；已经完整接收的任务在后台继续处理，无需重传。若只是成功响应丢失，查询原完成凭证即可得到同一张图片，不再次入库。

浏览器会保留同内容、同文件名、同标签的任务标识，重新选择一批文件时可复用其中已完成的结果。防重复以同一任务及 7 天完成凭证为范围；清理浏览器存储、换浏览器或第三方客户端使用新 `clientId` 不属于全图库内容去重。

未完成/失败暂存自最后接收或处理起保留约 24 小时，启动及每小时清理过期数据；手动取消会清理暂存。完成凭证保留 7 天。每用户最多 20 个未完成任务，并预留对应容量，提交入库时再次核对账号与配额。备份不含私有暂存；整站恢复会清除上传凭证和补齐队列，不能用备份恢复未传完的文件。旧的同步 `POST /api/upload` 保留兼容，不支持此续传协议；页面与新客户端使用下列 `/api/uploads` 接口。

## API

除公开接口外使用 `Authorization: Bearer <token>`，token 来自账号密码登录。

```text
GET    /api/health
GET    /api/public/settings
GET    /api/tags                          # 仅返回 count > 0 的图片标签
GET    /api/images?limit=36&cursor=...     # 返回 items/total/hasMore/nextCursor
                                         # 可加 tag=...、mine=1（需登录）
GET    /api/random?variant=compressed|original[&redirect=true][&tag=...]
GET    /api/random/image?variant=...[&tag=...] # 302，不缓存随机结果
POST   /api/auth/login                    # {username,password,remember}
POST   /api/auth/logout
GET    /api/auth/me
POST   /api/auth/password                 # {old,new}
POST   /api/upload                        # multipart files、tag
POST   /api/uploads                       # {clientId,filename,size,sha256,tag}
GET    /api/uploads                       # 当前用户最多 50 个任务，未完成优先
GET    /api/uploads/{id}                  # 状态、已确认 received、完成后的 item
PUT    /api/uploads/{id}/chunk            # 原始字节；Upload-Offset、X-Chunk-SHA256
POST   /api/uploads/{id}/complete         # 完整接收后入处理队列；可重复查询提交
POST   /api/uploads/{id}/retry            # 手动重试处理失败任务
DELETE /api/uploads/{id}                  # 取消未完成任务并清理暂存
PATCH  /api/images/{id}                   # {filename} 或 {tag}，空 tag 清除
DELETE /api/images/{id}
PATCH  /api/images/batch                 # {ids:[...],tag:"..."}；空 tag 清除
DELETE /api/images/batch                 # {ids:[...]}；逐项 results/done/failed
POST   /api/images/batch/download        # {ids:[...]}；流式原图 ZIP
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
GET    /api/admin/local/repair            # 补齐队列、进度、失败明细
POST   /api/admin/local/repair            # {batchSize:5}，补齐全部缺失文件
POST   /api/admin/local/repair/pause
POST   /api/admin/local/repair/resume     # 可传 {batchSize:5}
POST   /api/admin/local/repair/retry-failed
GET    /api/admin/local/index            # 只读检查磁盘与索引
POST   /api/admin/local/rebuild          # 移除失效记录、修正压缩版引用
POST   /api/admin/local/clear-derived    # {confirm:"clear-derived"}
GET    /api/admin/backup/stats
GET    /api/admin/backup
POST   /api/admin/restore                 # multipart file=.zip
POST   /api/admin/notify/test
```

滚动读取时，将上次响应的 `nextCursor` 原样传回；切换标签或仅我的条件时从空游标重新开始。`hasMore=false` 即结束。新上传的图片在刷新后出现，删除已读图片不会导致后续重复或跳过。

随机图公开后可直接用于 Markdown：

```markdown
![random](https://你的域名/api/random/image?variant=compressed)
![cat](https://你的域名/api/random/image?variant=compressed&tag=cat)
```

`tag` 按完整标签精确匹配，中文或特殊字符请先 URL 编码；省略或留空表示全部图片，无匹配返回 404。两个随机接口都支持此参数，原有登录/公开与限流规则不变。批量接口均需登录，`ids` 单次 1–500 个；编辑/删除会在修改前检查全部 ID 与权限。ZIP 先核验所有原图是否可读，再流式输出，不在服务端内存中积攒整个归档。列表中的 `thumb` / `compressed` 缺失时为 `null`；有效生成链接附带缓存版本参数，重生成后自动刷新。

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
python qa/features.py
python qa/reliability.py
python qa/privacy.py
python qa/metadata.py
python qa/metadata-cleanup.py
python qa/check-compose.py
python qa/memory-benchmark.py
```

回归使用 `.qa-data` 内的独立临时数据，覆盖旧库迁移、权限、上传、标签、游标、配额、防御、导入、备份恢复和重启。内存测试额外需要 `psutil`，结果不包含浏览器、编译器和 Node 开发服务器。

后台界面与功能验收、手机端设计修复及对应测试范围，见 [验收记录](docs/qa-review.md)。

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

维护者发布流程见 [发布说明](docs/release.md)。`README.md` 是介绍的主源，执行 `python scripts/sync-docs.py` 生成 Docker Hub 版文档，发布时同步上传；受 Docker Hub 25,000 字节限制，超长时本地开发章节改为完整文档链接。构建镜像和更新 GitHub/Docker Hub 元数据需要维护者自己的登录授权。

历史 `PLAN` 文档只记录旧版本设计，以当前源码和本 README 为准。

## 使用范围

沿用项目原有约定：仅供个人学习与自部署使用。仓库未新增开源许可证授权。
