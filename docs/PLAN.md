# lolis.im 复刻计划 — 「Gallery 图床」

> 目标：复刻 lolis.im（二次元图片收藏画廊 + 随机图片 API），Vue3 前端 + 本地 Docker 部署到飞牛 NAS，源码托管 GitHub。

---

## 一、原站分析（实测抓包结论）

### 1. 站点定位
- 标题：`lolis.im — ギャラリー / a little gallery`
- 描述：**二次元图片收藏画廊，附带随机图片 API**
- 私人收藏型图床：无注册、无多用户，**单管理员 Token 上传**，访客只能浏览和取图

### 2. 技术栈指纹
| 层 | 结论 | 依据 |
|---|---|---|
| 前端 | Vue 3 + Vite（SPA，懒加载 Upload 页） | bundle 中 `createApp`、`assets/index-*.js`、`data-v-` scoped CSS |
| 图片存储 | Cloudflare R2 对象存储 | bundle 文案 `PUT images → R2 bucket`；图片域名 `cdn.lolis.im` |
| 缩略图 | Cloudflare Images 实时变换 | thumb URL 形如 `/cdn-cgi/image/width=600,quality=78,format=auto/<原图url>` |
| 后端 | 轻量 API 服务（推断 Worker/小型服务，未暴露指纹） | 响应头无 PHP/框架痕迹，接口极简 |

### 3. 数据模型（实测 `/api/random.json` 返回）
```json
{
  "id": "1xpwtiz",
  "key": "uploads/2026/10/11/1791677988-7qke5m.jpg",
  "url": "https://cdn.lolis.im/uploads/2026/10/11/1791677988-7qke5m.jpg",
  "thumb": "/cdn-cgi/image/width=600,quality=78,format=auto/...",
  "width": 540, "height": 960,
  "mimeType": "image/jpeg",
  "size": 118755
}
```
- 文件 key 规律：`uploads/YYYY/MM/DD/<unix时间戳>-<随机串>.<扩展名>`
- id 为 7 位短随机串

### 4. API 契约（从 bundle 提取的完整端点清单）
**公开接口**
| 端点 | 作用 |
|---|---|
| `GET /api/images?page=&limit=&sort=latest\|random` | 分页图片列表 |
| `GET /api/random` | 随机一张，返回 JSON 元数据 |
| `GET /api/random?redirect=true` | 随机一张，302 跳原图 |
| `GET /api/random/image` | 随机一张，直接出图（外链用） |

**管理接口（`Authorization: Bearer <ADMIN_TOKEN>`）**
| 端点 | 作用 |
|---|---|
| `POST /api/admin/upload` | multipart 批量上传（`files=@image.png`，多文件） |
| `POST /api/admin/verify` | 校验 Token（登录/保存用） |
| `POST /api/admin/reindex` | 扫描存储重建索引（元数据兜底修复） |

### 5. 页面结构
`Gallery`（瀑布流/网格 + 分页）、`Random`（随机看图）、`Upload`（管理员上传页）、`API`（接口文档页）、`Me`（关于页）

---

## 二、复刻功能规划

### MVP（第一版必须）
1. **图片上传**：管理 Token 鉴权，拖拽/多选批量上传，逐文件返回成功/失败结果
2. **存储**：本地磁盘卷，沿用 `uploads/YYYY/MM/DD/<ts>-<rand>.<ext>` 目录规律
3. **元数据**：SQLite 单表（id/key/宽高/mime/size/上传时间），上传时用 Pillow 提取宽高
4. **缩略图**：上传时本地生成 WebP 缩略图（宽 600，quality 78），存 `thumbs/` 目录
5. **画廊页**：网格瀑布流 + 分页（page/limit）+ 点击看大图（灯箱）
6. **随机 API**：`/api/random`（JSON）、`?redirect=true`、`/api/random/image`（直链）三个全保留
7. **API 文档页**：站内展示接口用法（复刻原站的 API panel）
8. **reindex**：扫描 uploads 目录重建 SQLite 索引

### V2（可选增强）
- 按标签/来源筛选、排序（latest/random 之外的 sort）
- 上传时自动压缩/转码（超规格图片限制）
- 简单防刷：上传频率限制、随机接口缓存
- 图片鉴黄/审核队列（如果想公开注册的话，MVP 不做）

### 明确不做（对齐原站）
- 多用户注册/登录 —— 原站就是单管理员模式
- 对象存储多后端 —— 本地卷即可，NAS 场景够用

---

## 三、技术选型与架构

### 选型（贴合你现有技术栈）
| 组件 | 方案 | 理由 |
|---|---|---|
| 前端 | Vue 3 + Vite + 原生 fetch | 与原站同款，你熟 |
| 后端 | Python FastAPI | 你电影助手项目同款，复用经验 |
| 元数据 | SQLite（aiosqlite/sqlalchemy） | 单机单管理员，杀鸡不用 MySQL |
| 缩略图 | Pillow | 轻量够用 |
| 图片服务 | nginx 直接伺服静态卷 + 反代 API | 性能好，FastAPI 只管接口 |
| 部署 | Docker Compose，Debian 13 基础镜像思路 | 对齐你 NAS 部署习惯 |

### 架构图
```
浏览器/外部调用
      │
      ▼
┌─────────────── nginx 容器 (80) ───────────────┐
│  /            → Vue3 静态文件 (dist)           │
│  /api/*       → 反代 fastapi:8000             │
│  /files/*     → 伺服 uploads 卷 (原图)         │
│  /thumbs/*    → 伺服 thumbs 卷 (缩略图)        │
└──────────────┬────────────────────────────────┘
               ▼
┌─────────────── FastAPI 容器 (:8000) ──────────┐
│  /api/images        分页列表                   │
│  /api/random*       随机图（JSON/302/直链）     │
│  /api/admin/*       上传/verify/reindex        │
│  Pillow: 提取宽高 + 生成缩略图                  │
└──────┬──────────────────────┬────────────────┘
       ▼                      ▼
┌──────────────┐      ┌──────────────────────┐
│ SQLite       │      │ 数据卷 (NAS 挂载)      │
│ metadata.db  │      │ /data/uploads/YYYY/MM/DD │
└──────────────┘      │ /data/thumbs/        │
                      └──────────────────────┘
```

### 仓库结构
```
lolis-gallery/
├── docker-compose.yml
├── .env.example            # ADMIN_TOKEN=xxx
├── frontend/               # Vue3 + Vite
│   ├── src/{views: Gallery,Random,Upload,ApiDoc,About}
│   ├── Dockerfile          # node 构建 → nginx 运行
│   └── nginx.conf          # 静态 + /api 反代 + /files /thumbs 静态
├── backend/
│   ├── app/{main.py, api/, models.py, storage.py, thumbs.py, config.py}
│   ├── requirements.txt    # fastapi uvicorn pillow aiosqlite python-multipart
│   └── Dockerfile          # python:3.13-slim (Debian 底座)
└── README.md               # 含部署文档
```

### API 复刻细节（关键差异点）
- `url`：原站返回 CDN 域名，我们返回相对/同域路径 `/files/uploads/...`
- `thumb`：原站靠 Cloudflare 实时变换，我们返回 `/thumbs/uploads/...xxx.webp`（上传时生成）
- 其余字段与响应结构 1:1 对齐，前端可无缝工作

---

## 四、实施流程（Step by Step）

| # | 步骤 | 产出 |
|---|---|---|
| 1 | 初始化 GitHub 仓库 `lolis-gallery`（README/.gitignore/MIT） | 空仓库 |
| 2 | 后端骨架：FastAPI + SQLite + 上传/随机/列表/verify/reindex 五个接口 + 单测 | backend 可跑 |
| 3 | 缩略图模块（Pillow，上传后异步生成） | thumbs/ 产出 |
| 4 | 前端骨架：Vite + Vue3，五个页面 + API 面板，抓原站样式对齐（简洁白底画廊风） | frontend 可跑 |
| 5 | 本地联调：`docker compose up --build`，上传→画廊→随机 API 全链路验证 | 验证通过 |
| 6 | push 到 GitHub（main 分支） | 代码托管 |
| 7 | NAS 部署（见下节） | 上线 |

## 五、部署办法（最终交付形态）

### 1. GitHub 仓库
- 仓库名建议：`lolis-gallery`
- 私有/公开自选（含 ADMIN_TOKEN 逻辑的代码不含密钥，公开也无妨，密钥只进 `.env`）
- `.env.example` 提交，真实 `.env` 进 `.gitignore`

### 2. NAS 上的目录规划（飞牛 NAS，Debian 底座）
```bash
# 源码放这里
/vol1/docker/lolis-gallery/          # git clone 的仓库
/vol1/docker/lolis-gallery/data/     # compose 挂载的数据卷（uploads/thumbs/db）
```

### 3. docker-compose.yml（定稿草案）
```yaml
services:
  api:
    build: ./backend
    container_name: lolis-api
    restart: unless-stopped
    environment:
      - ADMIN_TOKEN=${ADMIN_TOKEN}
      - DATA_DIR=/data
    volumes:
      - ./data:/data
    expose:
      - "8000"

  web:
    build: ./frontend
    container_name: lolis-web
    restart: unless-stopped
    ports:
      - "8300:80"          # NAS 上对外端口，按需改
    volumes:
      - ./data:/data:ro    # nginx 直接读图
    depends_on:
      - api
```
> 单 compose 两容器：nginx 容器同时干「前端静态 + 反代 API + 伺服图片」三件事，FastAPI 不对外暴露端口。

### 4. 部署命令流（NAS 上）
```bash
# 首次
cd /vol1/docker
git clone https://github.com/<你的用户名>/lolis-gallery.git
cd lolis-gallery
cp .env.example .env        # 填 ADMIN_TOKEN
docker compose up -d --build

# 后续更新
cd /vol1/docker/lolis-gallery
git pull
docker compose up -d --build
```
浏览器访问 `http://<NAS_IP>:8300` 即为画廊；随机图外链：`http://<NAS_IP>:8300/api/random/image`。

### 5. 数据安全
- 全部图片/缩略图/数据库都在 `./data`，备份这个目录 = 备份整站
- 不推公共镜像仓库（对齐你电影助手的做法），镜像在 NAS 上现场 `--build`

---

## 六、待确认项
1. 对外端口用 `8300` 还是你有既定端口段？
2. GitHub 用户名/仓库名确认（我后面建仓库用）
3. 原站的「随机 API」要不要加 `Referer` 防盗链（V2 做，MVP 先裸奔）
