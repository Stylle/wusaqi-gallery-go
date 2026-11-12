# Wusaqi Gallery

图片随手上传，画廊轻松管理。

轻量自部署图片画廊与随机图 API，适合 NAS、本机电脑和小型 VPS。Go + SQLite 为唯一常驻应用服务，图片处理使用按需启动的 Pillow 子进程。

## 核心功能

- 瀑布流、标签筛选、灯箱、手机导航与亮暗主题。
- 多选、拖放、粘贴上传；分块续传、校验、失败重试与后台处理。
- 原图、压缩图、缩略图链接与随机图 API；私密标签、可撤销外链。
- 自动清除新图片个人元数据；已有图库可在备份后手动批量清理。
- 用户配额、批量下载与编辑、持久化图片任务、Webhook 和整站备份。
- Telegram 管理员机器人：私聊随机图、按标签取图，一次性绑定、实时撤销权限。

## 最简 Docker Compose

镜像 [stylle/wusaqi-gallery](https://hub.docker.com/r/stylle/wusaqi-gallery) 支持 `linux/amd64` / `linux/arm64`。将以下内容保存为 `compose.yaml`，或粘贴到 NAS Compose 页面，**必须修改初始密码**；无需 `.env`：

```yaml
services:
  gallery:
    image: stylle/wusaqi-gallery:latest # 可改为已发布的固定版本标签
    container_name: wusaqi-gallery     # 可省略或改名
    restart: unless-stopped
    ports:
      - "8300:80"                      # 左侧访问端口可改，右侧 80 保留
    environment:
      ADMIN_PASSWORD: "change-me-please" # 必改：首次创建管理员的密码
    volumes:
      - ./data:/data                  # 必须保留；左侧可改为专用绝对目录
```

```bash
docker compose up -d
```

打开 `http://服务器IP:8300`，使用 `admin` 和设置的初始密码登录。已有账号不会被环境变量覆盖；需要救援重置时见指南。所有图片、数据库和配置保存在 `/data`。

仓库中同一最简模板为 [docker-compose.minimal.yml](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docker-compose.minimal.yml)，使用时执行 `docker compose -f docker-compose.minimal.yml up -d`；[完整可选参数模板](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docker-compose.hub.yml) 包含健康检查与调优参数。

## 使用与维护

| 内容 | 文档 |
| --- | --- |
| 全部环境变量、上传、配额、外链与私密标签 | [使用指南](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#配置与使用) |
| 上传中断、续传与失败恢复 | [传输说明](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#上传断线失败与恢复) |
| 本地图库、索引维护、后台队列 | [批量处理](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#批量处理与索引维护) |
| 旧 Python 版本迁移、升级注意事项 | [迁移指南](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#从旧-python-版本升级) |
| Telegram 机器人配置、绑定与指令 | [机器人接入](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#telegram-管理员机器人) |
| API、随机图与调用示例 | [接口说明](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#api) |
| 开发、构建与发布 | [开发说明](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#本地运行和验证) · [发布流程](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/release.md) |
| 内存测量方法与原始结果 | [架构与内存](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/architecture.md) |

## Telegram 管理员机器人

后台打开「Telegram 机器人」，填写独立 Bot 的 BotFather Token、开启并保存。连接成功后生成绑定码，用自己的 Telegram 账号私聊 Bot 发送完整绑定指令。

绑定管理员可发送 `/random`、`/random 风景`、`/tags`；普通用户和群聊无响应，站点账号停用/降级或解除绑定后立即失效。私密图片默认禁止发送，开启后只能明确使用 `/random 私密` 获取。

Go 进程长轮询，无需新增端口或公开图片外链。图片会上传到 Telegram，已发送的内容无法通过站点开关撤回。完整步骤、代理和文件限制见 [接入指南](https://github.com/Stylle/wusaqi-gallery-go/blob/main/docs/guide.md#telegram-管理员机器人)。

## 更新与备份

升级前通过后台导出整站备份，或停容器后备份完整 `data/`。然后执行：

```bash
docker compose pull
docker compose up -d
```

保留原数据挂载。恢复备份会替换现有数据库和图片，先另做备份。旧 Python 镜像保留为 `legacy-python-20261023`，`latest` 已使用 Go 架构。

## 使用边界

内存随图片尺寸和任务变化，不承诺固定占用；`GOMEMLIMIT` 不是容器硬上限。照片元数据清理不处理画面中的人脸、地址或水印，也不能撤回已经下载的图片。

沿用项目原有使用约定：仅供学习与自部署使用，仓库未新增开源许可证授权。
