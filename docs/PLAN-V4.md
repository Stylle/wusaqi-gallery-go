# PLAN-V4：移动端适配 + Docker 管理员账号配置

> 目标：手机能正常用；部署时用环境变量配置管理员账号密码，并可关闭 ADMIN_TOKEN 直登。
> 原则：不改数据模型、不破坏已有部署的升级路径。

---

## 一、需求拆解

### R1 移动端适配

| 子项 | 现状 | 目标 |
|---|---|---|
| R1.1 断点体系 | 全站 0 个 `@media` | 三档断点：`≤900`（窄桌面/平板）、`≤768`（手机横屏/大屏手机）、`≤560`（小屏手机） |
| R1.2 顶栏导航 | 6 个链接 + 主题 + 用户区平铺，手机上必然溢出 | `≤768` 折叠为汉堡菜单，展开为纵向面板（含导航 + 主题切换） |
| R1.3 画廊瀑布流 | 固定 `column-width: 130/200/320` | 手机三档改为 3 / 2 / 1 列 |
| R1.4 右键菜单 | 仅 `contextmenu`，触屏无法触发 | 增加长按 500ms 触发；灯箱「操作 ▾」保持可用 |
| R1.5 后台布局 | 左侧 tree 固定 190px + 内容区并排 | `≤768` 上下堆叠，tree 变横向滚动条 |
| R1.6 数据表格 | 6 列宽表直接撑破 | 外层 `overflow-x: auto` 横向滚动，不挤压页面 |
| R1.7 触控友好 | 按钮 ~34px、hover 位移 | 触屏按钮 ≥40px；`hover: none` 下关闭位移/阴影 |
| R1.8 iOS 输入缩放 | `input` 13~14px 会触发聚焦放大 | `≤768` 时表单控件 `font-size: 16px` |
| R1.9 刘海屏安全区 | 无 | footer / 灯箱补 `env(safe-area-inset-*)` |

### R2 Docker 化管理员账号

| 子项 | 现状 | 目标 |
|---|---|---|
| R2.1 账号密码可配 | 硬编码 `admin` + `ADMIN_TOKEN` 当初始密码 | `ADMIN_USERNAME` / `ADMIN_PASSWORD` 环境变量，首次启动播种 |
| R2.2 关闭 Token 直登 | `ADMIN_TOKEN` 永远可换正式会话 | `ALLOW_ADMIN_TOKEN=0` 关闭；未显式设置时按「是否配了 ADMIN_TOKEN」推断，旧部署不受影响 |
| R2.3 密码找回 | 无（改错只能删库） | `ADMIN_SYNC=1` 启动时把库里的管理员账号强制覆盖为环境变量值 |
| R2.4 前端入口 | 登录页永远显示「用 Token 登录」 | 由 `/api/public/settings` 的 `token_login` 控制显隐 |
| R2.5 配置可见性 | — | 启动日志打印当前管理员用户名 / Token 直登开关，不打印密码 |

**向后兼容**：老部署的 `.env` 只有 `ADMIN_TOKEN`，升级后
① 密码仍可用（`ADMIN_PASSWORD` 缺省回落到 `ADMIN_TOKEN`，且已有库不改密码）；
② Token 直登默认关闭（因为 compose 里 `ALLOW_ADMIN_TOKEN` 默认 0），需要时设 1 即恢复。

---

## 二、后端改动

### config.py
```python
ADMIN_USERNAME = env(ADMIN_USERNAME) or "admin"
ADMIN_PASSWORD = env(ADMIN_PASSWORD) or env(ADMIN_TOKEN) or "changeme"
ADMIN_TOKEN    = env(ADMIN_TOKEN) or ""
ALLOW_ADMIN_TOKEN = flag(ALLOW_ADMIN_TOKEN, default=bool(ADMIN_TOKEN))
ADMIN_SYNC = flag(ADMIN_SYNC, default=False)
```

### db.py `_migrate()`
- 播种改为 `INSERT (ADMIN_ID, config.ADMIN_USERNAME, hash(config.ADMIN_PASSWORD))`
- 用户名唯一冲突 → 回落 `admin`，不中断启动
- 已有管理员且 `ADMIN_SYNC=1` → 覆盖 `username` / `pwd`

### auth.py `resolve_token()`
- 增加 `config.ALLOW_ADMIN_TOKEN` 前置判断；关闭时 Token 不再换会话
- 取管理员用户时兼容 `ADMIN_ID` 与「按 role 查」两种方式

### main.py
- `public_settings()` 追加 `token_login: "1"|"0"`
- `logout()` 的 Token 特判同步加开关
- `lifespan` 启动时触发迁移并打印管理员配置摘要

---

## 三、前端改动

| 文件 | 改动 |
|---|---|
| `App.vue` | 汉堡按钮、`topbar.open` 状态、导航面板内附主题切换、点击空白关闭 |
| `Gallery.vue` | 长按 500ms 弹菜单（移动后取消，避免与滚动打架）；长按后吞掉本次 click |
| `Admin.vue` | 用户表格外层加 `.table-scroll` |
| `Login.vue` | `token_login === '1'` 才显示 Token 登录入口 |
| `site.js` | 增加 `token_login` 字段 |
| `style.css` | 新增「响应式」段落，覆盖 R1.1~R1.9 |

---

## 四、验收清单

**后端（脚本自动跑）**
1. 默认（无 env）管理员 = `admin`，密码 = `ADMIN_TOKEN`，Token 直登可用
2. `ADMIN_USERNAME=owner ADMIN_PASSWORD=Passw0rd ALLOW_ADMIN_TOKEN=0` 全新库 → 播种 `owner`
3. 上述环境 `ALLOW_ADMIN_TOKEN=0` → `Bearer <ADMIN_TOKEN>` 返回 401，账号密码登录返回 200
4. `ADMIN_SYNC=1` + 改密码 → 重启后新密码可登录、旧密码 401
5. `/api/public/settings` 的 `token_login` 与开关一致

**前端**
6. `vite build` 通过
7. jsdom 渲染：375×812 视口下无运行时报错，汉堡按钮存在，展开后 6 个导航项可见
8. 桌面断点下汉堡按钮隐藏（CSS 断言）

**Docker**
9. `docker compose config` 渲染出的环境变量与 `.env` 一致（无多余必填项阻塞）

---

## 五、风险与取舍

- **不删 `ADMIN_TOKEN` 机制**：仅增加开关，避免老部署升级即锁死。
- **`ADMIN_SYNC` 默认关闭**：否则后台改过的密码会在每次重启被环境变量覆盖，反而更危险。
- **长按菜单不与滚动冲突**：`touchmove` 立即取消计时器；长按触发后 `click` 事件被吞掉，不误开灯箱。
- **表格用横向滚动而非卡片化**：后台是低频管理界面，改造成本与收益不匹配。
