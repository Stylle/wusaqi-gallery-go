# wusaqi-gallery

二次元图片收藏画廊 + 随机图片 API。单容器部署（nginx + FastAPI 同镜像），内置可配置压缩管线（原图/压缩版/缩略图三份产物）、流量防御（限流 + webhook 告警 + IP 封禁）、账号体系与树形管理后台。

## Compose 粘贴式部署（推荐）

把下面整段粘进 飞牛 Docker → Compose / Portainer / `docker compose up -d`：

```yaml
services:
  gallery:
    image: stylle/wusaqi-gallery:latest
    container_name: wusaqi-gallery
    restart: unless-stopped
    ports:
      - "8300:80"                         # 左边=对外端口；右边 80 固定
    volumes:
      - ./data:/data                      # 数据目录（图片+数据库），建议绝对路径
    environment:
      - ADMIN_PASSWORD=change-me-please   # 必改：管理员初始密码（仅首次建库播种）
      - ADMIN_USERNAME=admin              # 可省，默认 admin
      - ADMIN_SYNC=0                      # 1=启动时强制用上面的密码覆盖库里（忘记密码救援，救完改回 0）
      - RATE_LIMIT=120                    # 随机图每 IP 每分钟限流，0=关闭
      - TZ=Asia/Shanghai
```

访问 `http://<主机IP>:8300` 登录。所有数据在挂载的 `data` 目录里，备份/迁移 = 拷走该目录。

升级：重新 pull 镜像后重建容器（`docker compose pull && docker compose up -d`），数据不受影响。

### 环境变量说明

| 变量 | 必备 | 默认 | 说明 |
|---|---|---|---|
| `ADMIN_PASSWORD` | ✅ | `changeme` | 管理员初始密码，仅首次建库时播种 |
| `ADMIN_USERNAME` | | `admin` | 管理员用户名 |
| `ADMIN_SYNC` | | `0` | `1` = 每次启动强制覆盖库里的账号密码（忘记密码救援，用完改回） |
| `RATE_LIMIT` | | `120` | 随机图 API 每 IP 每分钟上限，超出 webhook 告警 + 临时封禁；`0` 关闭 |
| `TZ` | | 容器默认 | 时区，影响定时汇报与日志时间戳 |

压缩参数、webhook、站点标题/图标/页脚等更多配置全部在**后台管理面板**设置（存数据库，热生效），无需环境变量。

### 源码构建部署（自改代码场景）

```bash
git clone https://github.com/Stylle/wusaqi-gallery.git && cd wusaqi-gallery
cp .env.example .env && vi .env
docker compose up -d --build
```

## 随机图 API

```bash
GET /api/random?variant=compressed     # JSON 元数据（variant=compressed|original）
GET /api/random/image?variant=compressed   # 302 直链，Markdown/外链直接用
```

默认仅登录可用；后台「流量与权限」可开启公开访问。

## 链接

- GitHub: https://github.com/Stylle/wusaqi-gallery
- 完整文档见仓库 README
