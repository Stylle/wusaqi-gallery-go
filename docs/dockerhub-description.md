# wusaqi-gallery

二次元图片收藏画廊 + 随机图片 API。单容器部署（nginx + FastAPI 同镜像），内置可配置压缩管线（原图/压缩版/缩略图三份产物）、流量防御（限流 + webhook 告警 + IP 封禁）、账号体系与树形管理后台。

## Compose 部署（推荐）

```bash
mkdir -p /opt/wusaqi-gallery && cd /opt/wusaqi-gallery

# 1. 拉取 compose 与环境变量模板
curl -fO https://raw.githubusercontent.com/Stylle/wusaqi-gallery/main/docker-compose.hub.yml
curl -fso .env https://raw.githubusercontent.com/Stylle/wusaqi-gallery/main/.env.example

# 2. 修改 .env（必改 ADMIN_PASSWORD）
vi .env

# 3. 启动（数据落在 ./data）
docker compose -f docker-compose.hub.yml up -d
```

访问 `http://<主机IP>:8300`，用 `.env` 里的账号密码登录。

### .env 最小配置

```ini
ADMIN_USERNAME=admin
ADMIN_PASSWORD=please-change-me   # 必改
ADMIN_SYNC=0                      # 忘记密码时：改密码 + 设 1 重启一次
WEB_PORT=8300                     # 对外端口
RATE_LIMIT=120                    # 随机图每 IP 每分钟限流，0 = 关闭
```

### 日常管理

```bash
# 升级到最新镜像
docker compose -f docker-compose.hub.yml pull && docker compose -f docker-compose.hub.yml up -d

# 日志 / 状态
docker compose -f docker-compose.hub.yml logs -f
docker compose -f docker-compose.hub.yml ps

# 备份：打包 ./data 一个目录即可（图片 + SQLite 元数据）
```

### 导入已有图片

把图片直接放进 `./data/uploads/`（保持任意目录结构），后台「本地图库导入」页点「一键导入全部」——后台任务自动全量入库（生成缩略图与压缩版），失败的自动进入重试队列，下次导入优先重试。

## 源码构建部署（自改代码场景）

```bash
git clone https://github.com/Stylle/wusaqi-gallery.git && cd wusaqi-gallery
cp .env.example .env && vi .env
docker compose up -d --build
```

## 随机图 API

```bash
# JSON 元数据（variant=compressed|original）
GET /api/random?variant=compressed

# 302 直链（Markdown/外链直接用）
GET /api/random/image?variant=compressed
```

默认仅登录可用；后台「流量与权限」里可开启公开访问（`random_public`）。

## 链接

- GitHub: https://github.com/Stylle/wusaqi-gallery
- 完整文档见仓库 README
