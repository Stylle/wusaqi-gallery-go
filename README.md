# lolis-gallery

自部署的二次元图片收藏画廊，附带随机图片 API。复刻自 lolis.im 的功能形态，为家庭服务器 / NAS 场景做了**双 URL 省流量策略**。

技术栈：Vue 3 + Vite ｜ FastAPI + SQLite ｜ Pillow ｜ nginx ｜ Docker Compose

## 功能

- **画廊**：网格浏览 + 分页 + 灯箱；大图上**右键可复制原图 / 压缩图 / 缩略图 URL**
- **随机图 API**：`/api/random`（JSON）、`?redirect=true`、`/api/random/image`（直链），支持 `variant=compressed|original` 选压缩图或原图
- **单管理员上传**：`ADMIN_TOKEN` Bearer 鉴权，批量拖拽上传，逐文件返回结果
- **压缩设置后台可调**：格式（webp/jpeg/png）、质量（1-100）、最大宽度；仅对新上传生效
- **reindex**：误删数据库后可扫描 `data/uploads/` 重建索引

## 省流量设计（本项目核心）

每张图上传后落盘三份文件：

| 目录 | 内容 | 用途 |
|---|---|---|
| `data/uploads/` | 原图 | 仅明确请求时出网 |
| `data/compressed/` | 压缩版（后台可调参数） | **对外分享 / 随机 API 默认给这份** |
| `data/thumbs/` | 600px WebP 缩略图 | 画廊网格加载 |

配合：图片 URL 一年期 `immutable` 缓存（文件名唯一，改内容即换名）、随机接口每 IP 限流（`RATE_LIMIT`）、nginx gzip。家庭宽带小水管也能稳定供图。

## 部署（NAS / 任意 Docker 主机）

```bash
cd /vol1/docker
git clone https://github.com/<你的用户名>/lolis-gallery.git
cd lolis-gallery
cp .env.example .env        # 编辑 .env，改 ADMIN_TOKEN
docker compose up -d --build
```

访问 `http://<NAS_IP>:8300`。后续更新：`git pull && docker compose up -d --build`。

- 全部数据（图片 + 数据库）都在 `./data`，备份该目录即备份整站
- 镜像现场构建，不依赖公共镜像仓库

## API 速查

```
GET  /api/images?page=1&limit=24&sort=latest|random
GET  /api/random?variant=compressed|original[&redirect=true]
GET  /api/random/image?variant=compressed|original        # 302 直链

POST /api/admin/upload    # multipart, files=@a.png, Bearer Token
POST /api/admin/verify
GET/PUT /api/admin/settings   # {"format":"webp","quality":80,"max_width":2560}
POST /api/admin/reindex
```

外链示例：`![random](http://your-host:8300/api/random/image?variant=compressed)`

## 目录结构

```
├── docker-compose.yml
├── backend/          # FastAPI：上传/压缩/随机/设置/限流
│   └── app/
└── frontend/         # Vue3 SPA + nginx（静态 + 反代 + 图片伺服）
```
