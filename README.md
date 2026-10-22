# lolis-gallery

自部署的二次元图片收藏画廊，附带随机图片 API。功能形态复刻自 lolis.im，视觉为独立设计（参考 maxcat 风格配色），为家庭服务器 / NAS 场景做了**双 URL 省流量策略**与**流量防御**。

技术栈：Vue 3 + Vite ｜ FastAPI + SQLite ｜ Pillow ｜ nginx ｜ Docker Compose

## 功能总览

- **画廊**：瀑布流（按原图比例排布，不裁切）+ 小/中/大三档尺寸 + 灯箱；骨架屏；右键复制原图 / 压缩图 / 缩略图 URL
- **手机端**：≤768px 顶栏折叠为汉堡菜单；画廊自动 3/2/1 列；右键菜单换成**长按**；后台左侧树变顶部横向滚动条；表格横向滑动；刘海屏安全区与 44px 触控目标
- **标签**：顶部标签 chips 点击即筛选（带计数）；上传时可选标签，默认值后台配置
- **随机图 API**：`/api/random`（JSON / 302 直链），`variant=compressed|original`
- **多用户**：管理员后台建号；普通用户有**容量配额**与**独立压缩参数**（管理员可改）；用户后台只看自己用量与上传入口
- **权限**：游客仅可浏览画廊；复制链接、随机图、上传、后台需登录；画廊支持「仅我的」筛选（登录用户）
- **图片管理**：重命名（原图 / 压缩图 / 缩略图同步改名）、删除（三份文件一起删）；管理员可操作全部，普通用户仅限自己的图
- **上传**：拖拽 / 多选 / **Ctrl+V 粘贴上传**，逐文件进度 + 压缩前后对比 + 配额条
- **压缩方案（方案 B）**：启动自动探测 CPU 核数与内存（容器读 cgroup 限额）→ `tiny / small / normal` 三档，各档独立质量、最大宽度、webp 编码强度、分辨率上限与**压缩并发数**（1 核机器恒为 1，防大图并发打爆内存）；后台可切「自动 / 指定档 / 自定义」，并附方案对照表与格式推荐
- **上传限制**：全局单图大小 + 用户级单图大小、容量配额、**每日 / 每周 / 每月张数**（滑动窗口，管理员不受限）；新建用户默认 5MB 单图 / 500MB 配额 / 30 张每日 / 100 张每周 / 250 张每月，可在后台改默认值
- **三态主题**：亮色 / 暗黑 / 跟随系统，玻璃拟态卡片
- **树形后台**（komari 风格）：站点信息、分享基址、标签、压缩、流量防御、登录规则、用户管理全部可配
- **流量防御**：随机图接口每 IP 每分钟限流，超限 → **webhook 告警** + 封禁；登录失败超阈值 → 封禁（防爆破）
- **本地图库导入**：把图片直接丢进 `data/uploads`，后台「媒体维护 → 本地图库导入」扫描入库（原路径不变、归属管理员）；缺压缩版/缩略图的图片可在同一面板**分批补压缩**（每次 3~5 张，低配机器也不打满 CPU）

## 省流量设计（本项目核心）

| 目录 | 内容 | 用途 |
|---|---|---|
| `data/uploads/YYYYMMDD/` | 原图 | 仅明确请求时出网 |
| `data/compressed/` | 压缩版（参数可按用户覆盖） | **对外分享 / 随机 API 默认给这份** |
| `data/thumbs/` | 600px WebP 缩略图 | 画廊网格加载 |

配合图片一年期 `immutable` 缓存 + 限流封禁，家庭宽带小水管也能稳定供图。

## 登录规则

- 账号密码登录（管理员在后台「用户管理」建号，无公开注册）
- **记住我**：勾选 → 30 天（存 `localStorage`）；不勾 → 12 小时（存 `sessionStorage`，关浏览器失效）
- 有效期可在后台「账号与权限 → 登录规则」调整
- 万能 `ADMIN_TOKEN` 默认**关闭**；设 `ALLOW_ADMIN_TOKEN=1` 且配置了 `ADMIN_TOKEN` 才启用（启用时登录页会多出 Token 登录入口）

## 管理员账号（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | 首次启动（空库）创建的管理员用户名 |
| `ADMIN_PASSWORD` | 回落 `ADMIN_TOKEN`，否则 `changeme` | 首次启动的密码；库已存在时**不覆盖** |
| `ADMIN_TOKEN` | 空 | 万能 Token；留空即无此凭据 |
| `ALLOW_ADMIN_TOKEN` | 未设时有 Token 则 1，否则 0 | `0` 完全关闭 Token 直登 |
| `ADMIN_SYNC` | `0` | `1` = 每次启动把库里的管理员用户名/密码覆盖为上面两项（**忘记密码的救援开关**） |

启动日志会打印当前管理员用户名与 Token 直登状态（不打印密码）。密码若仍是 `changeme` 会有醒目告警。

**忘记密码**：改 `.env` 的 `ADMIN_PASSWORD` + 设 `ADMIN_SYNC=1` → `docker compose up -d` 重启 → 登录后把 `ADMIN_SYNC` 改回 `0`（否则每次重启都会覆盖后台改过的密码）。

## 部署（NAS / 任意 Docker 主机）

```bash
cd /vol1/docker
git clone https://github.com/Stylle/lolis-gallery.git
cd lolis-gallery
cp .env.example .env        # 编辑 .env：ADMIN_PASSWORD 必改
docker compose up -d --build
```

访问 `http://<NAS_IP>:8300`。更新：`git pull && docker compose up -d --build`。

- 全部数据（图片 + 数据库）在 `./data`，备份该目录 = 备份整站
- 镜像现场构建，不依赖公共镜像仓库
- **首次部署**：用 `.env` 里的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录 → 后台建用户、改站点信息与分享基址
- **从 v3 升级**：老 `.env` 里的 `ADMIN_TOKEN` 仍可作为 admin 密码登录（`ADMIN_PASSWORD` 缺省回落到它）；Token 直登默认关闭，需要时设 `ALLOW_ADMIN_TOKEN=1`

## 本地开发（无 Docker）

```bash
# 后端
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
DATA_DIR=../data ADMIN_USERNAME=admin ADMIN_PASSWORD=devpass123 \
  uvicorn app.main:app --reload --port 8000

# 前端（另开终端，vite 已配好 /api /files /thumbs /compressed 代理）
cd frontend
npm install && npm run dev
```

打开 http://127.0.0.1:5173 。后端**只读环境变量**，不读 `.env` 文件。

## 手机端适配

| 断点 | 变化 |
|---|---|
| ≤900px | 内容区收窄内边距 |
| ≤768px | 顶栏折叠为汉堡菜单（含主题切换）、画廊 3/2 列、后台左侧树变顶部横向条、表格横向滚动、表单控件 16px 防 iOS 缩放、按钮 ≥42px |
| ≤560px | 画廊「大」档变单列、角标缩小 |
| `hover: none` | 关闭所有仅鼠标准备的位移/阴影 |

手机上**长按图片 500ms** 唤出与右键相同的菜单（复制链接 / 重命名 / 删除），灯箱内的「操作 ▾」也可用。

## Webhook 告警

后台「流量与安全 → 流量防御」填 Webhook URL，触发限流封禁或爆破封禁时 POST JSON：

```json
{
  "event": "rate_limit",
  "site": "椒盐画廊",
  "ip": "1.2.3.4",
  "limit_per_minute": 60,
  "ban_minutes": 10,
  "time": "2026-10-22T00:00:00+00:00"
}
```

事件名：`rate_limit` / `auth_brute_force`。

## API 速查

```
GET  /api/public/settings                              # 站点公开信息（含 share_base_url / token_login）
GET  /api/tags                                          # 标签 + 计数
GET  /api/images?page=1&limit=24&sort=latest|random[&tag=&mine=1]
GET  /api/random?variant=compressed|original[&redirect=true]
GET  /api/random/image?variant=compressed|original      # 302 直链

POST   /api/auth/login     {username,password,remember}  → token
POST   /api/auth/logout
GET    /api/auth/me                                     # 用户信息 + 用量
POST   /api/auth/password

POST   /api/upload         multipart files=@a.png&tag=xxx
PATCH  /api/images/{id}    {filename?|tag?}              # 重命名 / 改标签
DELETE /api/images/{id}                                 # 删三份文件

GET    /api/users          # 管理员：列表 + 用量
POST   /api/users          # 管理员：建号
PATCH  /api/users/{id}
DELETE /api/users/{id}?purge=false

GET/PUT /api/admin/settings
GET     /api/admin/system                              # 压缩方案运行态（探测结果 / 档位 / 格式）
GET     /api/admin/local/scan?dry_run=true&limit=50    # 扫描 uploads 未入库原图（dry_run=false 导入）
POST    /api/admin/local/compress?dry_run=true&limit=5  # 补生成缺失的压缩版/缩略图
POST    /api/admin/reindex                             # 兼容别名：全量扫描导入
GET     /api/admin/bans
```

完整字段说明见后台「开发者 → API 文档」。

## 目录结构

```
├── docker-compose.yml
├── PLAN.md / PLAN-V3.md / PLAN-V4.md   # 原始计划 / v3 用户体系 / v4 移动端与部署配置
├── qa/                      # 验收脚本（接口 / 环境变量 / compose 契约）
├── backend/                 # FastAPI：账号会话/上传/压缩/随机/权限/限流/webhook
│   └── app/
│       ├── main.py          # 路由与业务
│       ├── auth.py          # 登录 / 会话 / 权限
│       ├── db.py            # SQLite（自动迁移建表）
│       ├── compress.py      # 缩略图 / 压缩 / 支持格式清单
│       ├── perf.py          # 压缩方案：机器探测 / 档位 / 并发槽
│       └── util.py          # 短 id / 文件 key / 密码哈希
└── frontend/                # Vue3 SPA（瀑布流画廊 / 树形后台 / 登录）
```

扩展性：配置项集中注册（`db.DEFAULT_SETTINGS` + `main.py` 的 `put_settings` 规则），后台树形面板按分组渲染——加新配置组不必动核心逻辑。
