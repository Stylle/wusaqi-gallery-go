# wusaqi-gallery 🖼️

自部署的图片收藏画廊 + 随机图 API。Vue 3 + FastAPI + SQLite，双容器 Docker 部署，
数据全部落在本地目录，**不依赖任何外部云服务**。

## 功能总览

| 模块 | 说明 |
|---|---|
| 画廊 | 瀑布流网格 + 灯箱大图，标签筛选 / 仅看我的 / 三档网格尺寸 |
| 三 URL 策略 | 每张图落盘三份：原图 `files/`、压缩版 `compressed/`、缩略图 `thumbs/`，右键可复制任意一种链接 |
| 压缩可配置 | 格式（webp/jpeg/png）、质量、最大宽度，后台调整对新上传生效；每人还可覆盖全局压缩参数 |
| 随机图 API | `/api/random` JSON 与 302 直链两种形态，`variant=compressed\|original` 选择出图版本，外链/Markdown 直接用 |
| 上传 | 拖拽多选批量上传，逐文件进度条 + 压缩前后大小对比 |
| 权限门控 | 游客只能浏览画廊；复制链接 / 随机 API / 上传 / 后台均需登录；随机 API 可在后台一键转公开外链 |
| 多用户 | 管理员可创建普通用户，配额（总容量/单图上限/日周月上传数）逐人可调 |
| 流量防御 | 随机接口限流 → 超限 webhook 告警 + IP 封禁 N 分钟；登录爆破计数封禁；黑白名单；内网 IP 永不封禁 |
| 通知 | webhook 推送（登录 / 封禁 / 解封 / 限流等事件分类开关），支持测试发送 |
| 后台 | 树形配置面板：站点信息（标题/图标/标签/页脚）、压缩、防御、用户、备份，全部热生效 |
| 备份恢复 | 一键打包整个数据目录为 zip 下载，上传 zip 一键恢复 |
| 主题 | 亮色 / 暗黑 / 跟随系统三态 + 纯色 / 炫彩两套配色风格，手机端完整适配（后台为抽屉式侧栏） |
| 国际化 | 中 / 英文界面切换 |

## 架构

**单容器双进程**（supervisor 管理）：一个镜像里 nginx 负责静态与反代，uvicorn 负责 API。

```
        :8300 (对外唯一端口)
┌─────────────────────────────────────┐
│  wusaqi-gallery 容器                │
│  ┌───────────────────────────────┐  │
│  │ nginx                         │  │
│  │  /            SPA 静态文件     │  │
│  │  /files /thumbs /compressed   │  │ ← /data 卷，一年 immutable 长缓存
│  │  /api/ ──反代──▶ 127.0.0.1:8000│  │
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │ uvicorn (FastAPI + SQLite)    │  │ 上传/压缩/鉴权/限流/webhook
│  └───────────────────────────────┘  │
│  supervisor 守护两个进程，崩了自动拉起 │
└─────────────────────────────────────┘
```

- **省流量设计**：随机 API 与画廊网格默认只出缩略图/压缩版，原图仅在明确请求时出网；
  nginx 对图片路径下发 `immutable` 长缓存，重复访问不回源。
- 图片请求由 nginx 直接命中卷内文件，不经过 Python。
- 单容器的好处：一次 pull、一条 compose、一份日志；数据仍在 `data/` 一个目录里。

## 代码结构

```
wusaqi-gallery/
├── Dockerfile            # 单容器镜像：node 编前端 → python + nginx + supervisor
├── deploy/
│   ├── nginx.conf        # 静态+图片伺服 + /api 反代 + 一年 immutable 缓存
│   └── supervisord.conf  # 双进程守护（uvicorn + nginx）
├── backend/app/
│   ├── main.py           # 路由与入口：公开接口/会话/图片/后台/防御中间件
│   ├── config.py         # 运行时配置（全部可用环境变量覆盖）
│   ├── db.py             # SQLite：建表迁移/设置/图片/用户/会话/封禁/访问统计
│   ├── auth.py           # 登录会话（记住我 30d / 会话 12h）与权限
│   ├── compress.py       # 压缩管线（格式/质量/最大宽度）
│   ├── notify.py         # webhook 事件推送与周期报告
│   ├── backup.py         # 整站备份与恢复
│   ├── perf.py           # 启动环境探测（日志展示）
│   └── util.py           # 密码哈希与通用工具
├── frontend/src/
│   ├── api.js            # 全部后端调用封装
│   ├── auth.js           # 登录态（双存储 token）与全局校验
│   ├── site.js           # 站点公开配置下发与动态标题/图标
│   ├── theme.js          # 三态主题
│   ├── i18n.js           # 中英文案
│   └── views/            # Gallery / Random / Upload / Admin / Login
├── docs/                 # 历史版本规划文档（PLAN/V3/V4）
├── qa/                   # 回归脚本（compose 契约/单测/端到端/并发冒烟）
├── docker-compose.yml        # 源码构建部署
├── docker-compose.hub.yml    # 镜像拉取部署（推荐）
└── .env.example
```

**扩展约定**：新增一个后台可调配置项 = `db.DEFAULT_SETTINGS` 加键 +
`main.py` 的 `PUBLIC_SETTING_KEYS`（若需公开下发）/ `put_settings` 校验规则里声明，
前端后台树自动渲染，无需改其他代码。

## 快速部署

### 方式一：Docker Hub 镜像部署（推荐，NAS / VPS 通用，免源码免构建）

镜像已发布：[`stylle/wusaqi-gallery`](https://hub.docker.com/r/stylle/wusaqi-gallery)（单容器：nginx + FastAPI 同容器）

**粘贴式部署**——把下面这段整段粘进 飞牛 Docker → Compose（或 Portainer、`docker compose up -d`）即可：

```yaml
services:
  gallery:
    image: stylle/wusaqi-gallery:latest   # 锁定版本可换 :<git短哈希>，回滚同理
    container_name: wusaqi-gallery
    restart: unless-stopped               # 开机自启 + 异常自动重启
    ports:
      - "8300:80"                         # 【必备·按需改】左边是对外端口；右边 80 固定别动
    volumes:
      - ./data:/data                      # 【必备·按需改】左边是数据目录（图片+数据库），建议绝对路径如 /vol1/docker/wusaqi-gallery/data
    environment:
      # ---------- 必备 ----------
      - ADMIN_PASSWORD=change-me-please   # 【必备】管理员初始密码（仅首次建库播种，之后改密码走后台）
      # ---------- 可选：有默认值，不需要可整行删除 ----------
      - ADMIN_USERNAME=admin              # 管理员用户名，默认 admin
      - ADMIN_SYNC=0                      # 1 = 每次启动用上面的用户名/密码强制覆盖库里的（忘记密码救援通道；救完务必改回 0）
      - RATE_LIMIT=120                    # 随机图 API 每 IP 每分钟请求上限，超出触发 webhook 告警 + 临时封禁；0 = 关闭
      - TZ=Asia/Shanghai                  # 时区（影响每日/每周汇报与日志时间戳）
```

（完整版含健康检查见仓库 `docker-compose.hub.yml`；健康检查段可整段省略。）

访问 `http://<主机IP>:8300`，用上面的账号密码登录即可。

日常管理（命令行方式时）：

```bash
docker compose pull && docker compose up -d          # 升级到 latest
docker compose logs -f                               # 看日志
docker compose down                                  # 停止（data/ 数据不受影响）
```

> 数据全部在部署目录的 `data/` 里（SQLite + 图片），备份/迁移 = 拷走这个目录。

### 方式二：源码构建部署（需要改代码自用时）

```bash
git clone https://github.com/Stylle/wusaqi-gallery.git && cd wusaqi-gallery
cp .env.example .env && vi .env
docker compose up -d --build
```

### 发布新镜像（维护者）

标准构建机为 GreenCloud VPS（`/opt/wusaqi-gallery`，已克隆源码并登录 Docker Hub）：

```bash
ssh root@<vps>
cd /opt/wusaqi-gallery
git pull
bash scripts/build-push.sh            # 构建并推送 latest + git 短哈希双标签
```

任意装了 Docker 的机器也可发布：

```bash
git clone https://github.com/Stylle/wusaqi-gallery.git && cd wusaqi-gallery
docker login -u stylle                # 密码处填 Docker Hub Access Token（RW 权限）
bash scripts/build-push.sh            # Windows 用 scripts\build-push.bat
```

脚本会构建单容器镜像并推送 `latest` + 当前 git 短哈希双标签，便于回滚：

```bash
# 回滚到指定版本（把 <sha> 换成推过的短哈希）
docker pull stylle/wusaqi-gallery:<sha>
# 然后在 docker-compose.hub.yml 里把 image 标签改成对应 sha 再 up -d
```

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | 首次启动播种的管理员用户名（库已存在不覆盖） |
| `ADMIN_PASSWORD` | `changeme` | 首次启动的密码；库已存在时不覆盖，启动日志会告警 |
| `ADMIN_SYNC` | `0` | 忘记密码救援：设 `1` 重启一次，强制把库里管理员账密同步为上面两项，完成后改回 `0` |
| `WEB_PORT` | `8300` | 对外 HTTP 端口 |
| `RATE_LIMIT` | `120` | 随机图接口每 IP 每分钟限流，`0` 关闭（后台也可调） |

> 其余全部配置（压缩参数、webhook、黑白名单、上传上限、站点信息等）在后台管理面板调整，存数据库、热生效。

### 更新 / 迁移 / 备份

```bash
# 更新到最新版
git pull && docker compose up -d --build

# 迁移到新机器：停服后整个拷走 data/ 即可（SQLite + 图片自包含）
# 日常备份：后台「备份」页一键下载 zip，或直接备份 data/ 目录
```

## API 摘要

鉴权统一 `Authorization: Bearer <token>`，token 来自 `POST /api/auth/login`。

```
GET  /api/health                  # 存活探针（compose healthcheck 用）
GET  /api/public/settings         # 站点公开信息
GET  /api/tags                    # 标签列表
GET  /api/images?page=&limit=&sort=latest|random&tag=&mine=
GET  /api/random?variant=compressed|original[&redirect=true]
GET  /api/random/image?variant=   # 302 直链
POST /api/auth/login|logout       GET /api/auth/me
POST /api/admin/upload            # multipart files
PUT  /api/admin/settings          POST /api/admin/reindex
*    /api/admin/*                 # 用户/封禁/黑白名单/备份/通知（管理员）
```

完整字段说明见站内「后台 → API 文档」。

## 本地开发（不依赖 Docker）

```bash
# 后端（Windows 示例，任意 python ≥3.11）
cd backend
pip install -r requirements.txt
ADMIN_USERNAME=admin ADMIN_PASSWORD=test123 DATA_DIR=./data \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（/api、/files 等自动代理到 8000）
cd frontend
npm ci
npm run dev        # http://127.0.0.1:5173
```

## QA 回归脚本

```bash
python qa/check-compose.py       # compose 与 .env.example 契约
python qa/unit-admin-env.py      # 环境变量解析/播种/同步（自包含）
python qa/api-admin-http.py      # 端到端（需先起 8010 测试实例）
python qa/concurrent-smoke.py    # 并发冒烟（需先起后端）
```

## 许可

仅供个人学习与自部署使用。
