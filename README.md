# lolis-gallery

自部署的二次元图片收藏画廊，附带随机图片 API。功能形态复刻自 lolis.im，视觉为独立设计（参考 maxcat 风格配色），为家庭服务器 / NAS 场景做了**双 URL 省流量策略**与**流量防御**。

技术栈：Vue 3 + Vite ｜ FastAPI + SQLite ｜ Pillow ｜ nginx ｜ Docker Compose

## 功能总览

- **画廊**：网格 + 分页 + 灯箱；骨架屏加载动画；大图右键复制原图 / 压缩图 / 缩略图 URL
- **随机图 API**：`/api/random`（JSON / 302 直链），`variant=compressed|original` 选压缩或原图
- **三态主题**：亮色 / 暗黑 / 跟随系统，maxcat 风格粉蓝渐变配色，玻璃拟态卡片
- **权限门控**：游客仅可浏览画廊；复制链接、随机图、上传、后台、API 文档均需登录；随机图可在后台一键开放为公开（外链场景）
- **上传进度**：逐文件上传 + 实时进度条 + 压缩前后大小对比
- **树形后台**（komari 风格）：站点信息（标题/图标/标签/页脚）、图片压缩（格式/质量/最大宽度）、流量防御、安全，全部后台可配
- **流量防御**：随机图接口每 IP 每分钟限流，超限 → **webhook 告警**（POST JSON）+ 封禁 N 分钟；鉴权失败累计超阈值 → 封禁（防爆破）；后台可查看当前封禁列表
- **reindex**：误删数据库后扫描目录重建索引

## 省流量设计（本项目核心）

| 目录 | 内容 | 用途 |
|---|---|---|
| `data/uploads/` | 原图 | 仅明确请求时出网 |
| `data/compressed/` | 压缩版（后台可调参数） | **对外分享 / 随机 API 默认给这份** |
| `data/thumbs/` | 600px WebP 缩略图 | 画廊网格加载 |

实测（900×1300 图）：原图 66KB → 压缩 23KB（-65%）→ 缩略图 12KB。
配合图片一年期 `immutable` 缓存 + 限流封禁，家庭宽带小水管也能稳定供图。

## 部署（NAS / 任意 Docker 主机）

```bash
cd /vol1/docker
git clone https://github.com/Stylle/lolis-gallery.git
cd lolis-gallery
cp .env.example .env        # 编辑 .env：ADMIN_TOKEN 必改
docker compose up -d --build
```

访问 `http://<NAS_IP>:8300`。更新：`git pull && docker compose up -d --build`。

- 全部数据（图片 + 数据库）在 `./data`，备份该目录 = 备份整站
- 镜像现场构建，不依赖公共镜像仓库
- **首次部署**：打开 Upload 页输入 Token 登录 → 后台按需调整站点信息与防御参数

## Webhook 告警

后台「流量与权限 → 流量防御」填入 Webhook URL，触发限流封禁或爆破封禁时 POST JSON：

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

对接企微/钉钉/飞书机器人时套一层转发即可（事件名：`rate_limit` / `auth_brute_force`）。

## API 速查

```
GET  /api/public/settings                              # 站点公开信息
GET  /api/images?page=1&limit=24&sort=latest|random    # 公开
GET  /api/random?variant=compressed|original[&redirect=true]   # 登录可用，后台可开放
GET  /api/random/image?variant=compressed|original     # 302 直链

POST /api/admin/upload         # multipart files=@a.png
POST /api/admin/verify
GET/PUT /api/admin/settings    # 全部配置项读写
POST /api/admin/reindex
GET  /api/admin/bans           # 当前封禁列表
```

## 目录结构

```
├── docker-compose.yml
├── backend/          # FastAPI：上传/压缩/随机/权限/限流/webhook
│   └── app/          # 新增配置项：db.DEFAULT_SETTINGS 加键即可，前后端自动生效
└── frontend/         # Vue3 SPA（三态主题/树形后台）+ nginx
```

扩展性说明：配置项集中注册（`db.DEFAULT_SETTINGS` + `main.py` 规则表），后台树形面板按分组渲染——后续加插件化主题、新存储后端只需注册新配置组，不动核心逻辑。
