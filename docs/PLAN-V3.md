# lolis-gallery v3 开发规划

> 依据主人 7 条需求拆解。原则：不破坏现有 API 契约（`/api/images`、`/api/random*` 保持），新增能力以增量方式加入；数据目录向后兼容（旧 key 不动，新上传用新日期目录）。

---

## 一、需求拆解与实现方案

### R1 默认分享链接

- 后台新增配置 `share_base_url`：复制链接时使用的站点基址。
- 未配置（空）→ 前端用 `location.origin`（当前访问 URL）。
- 前端 `absUrl()` 统一走此逻辑，画廊右键 / 随机页 / 上传结果全部生效。

### R2 标签体系（可点筛选 + 上传默认标签 + 粘贴上传）

- 顶部标签从「装饰」变「筛选器」：点击启用（高亮），再点取消；同时只有一个标签生效（`activeTag`）。
- 后端 `GET /api/images?tag=xxx` 精确过滤；`GET /api/tags` 返回「配置的标签 + 实际计数」。
- 上传页：多选标签 chips，默认勾选后台配置的 `upload_default_tags`（第一个为默认）。上传时以 `Form(tag)` 提交。
- 粘贴上传：`document paste` 事件读取 `clipboardData.items` 里的 image，直接入队。

### R3 图片重命名 + 存储按日期分类

- 存储路径改为 `uploads/YYYYMMDD/<ts>-<rand>.<ext>`（原 `/YYYY/MM/DD/` 旧数据不迁移，reindex 兼容）。
- 重命名 API：`PATCH /api/images/{id}` `{filename}` → 同时改原图、压缩图、缩略图三者文件名（同目录内改名），更新 `key/c_key/orig_name`。
- 文件名做白名单清洗（去路径符、控制字符，长度 ≤ 80），扩展名沿用原图。
- 权限：管理员改全部，普通用户只改自己的。

### R4 画廊排列（按原尺寸 + 三档尺寸）

- 网格从「正方形裁切」改为**瀑布流**：CSS multi-column + 图片原始宽高比（数据里已有 `width/height`，无需等图加载）。
- 三档尺寸档位切换：小 / 中 / 大（列宽 130 / 200 / 320px），持久化到 localStorage。
- 缩略图仍用 600px WebP（大档位也不糊），点击看大图。

### R5 用户体系与配额

- 新表 `users`：`id / username / pwd(pbkdf2) / role(admin|user) / quota_mb / max_upload_mb / comp_format / comp_quality / comp_max_width / enabled`。
- 新表 `sessions`：`token / user_id / expires_at / remember`。
- 后台「用户管理」：创建 / 编辑（配额、压缩覆盖参数、角色）/ 重置密码 / 启用停用 / 删除（默认把图片转交管理员，可选一并清除）。
- 配额：`used = SUM(images.size) WHERE owner_id=?`；上传前校验，超限该文件失败并返回明确原因（`quota exceeded`）。
- 压缩参数优先级：用户覆盖值 > 全局设置。
- 普通用户后台：只能看到「我的用量（已用/配额/剩余）+ 上传入口」，无站点配置、无用户管理、无封禁列表。
- 画廊「仅我的」筛选项：仅登录用户可见可用（`mine=1`）。

### R6 右键删除

- `DELETE /api/images/{id}`：删原图 + 压缩图 + 缩略图 + 数据库记录。
- 权限：管理员删全部；普通用户只删自己上传的；未登录右键菜单不出现「删除」（且后端 401/403 双保险）。

### R7 登录规则（常规站点标准）

- 账号密码登录，`记住我`：
  - 勾选 → token 存 `localStorage`，有效期 `remember_days`（默认 30 天）
  - 不勾选 → token 存 `sessionStorage`，有效期 `session_hours`（默认 12 小时），关浏览器即丢
- 顶栏右上角显示用户名 / 角色，**退出登录**按钮（调后端销 token + 清本地）。
- 登录失败计入防爆破计数（沿用 v2 阈值）。
- 保留 ADMIN_TOKEN 直登作为兼容后门（等价 admin 身份）。
- 首次迁移：自动创建 `admin` 账号，密码 = 环境变量 `ADMIN_TOKEN`。

---

## 二、数据模型变更

```sql
-- images 新增列（ALTER TABLE 迁移，旧库自动补齐）
owner_id TEXT, tag TEXT, orig_name TEXT

-- 新表
users(id, username UNIQUE, pwd, role, quota_mb, max_upload_mb,
      comp_format, comp_quality, comp_max_width, enabled, created_at)
sessions(token PK, user_id, expires_at, remember, created_at)

-- settings 新增键
share_base_url, upload_default_tags, session_hours, remember_days
```

迁移动作：旧 `images.owner_id IS NULL` 统一归到 admin；admin 账号不存在则按 `ADMIN_TOKEN` 播种。

---

## 三、API 变更清单

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/auth/login` | 公开 | `{username,password,remember}` → token |
| POST | `/api/auth/logout` | 登录 | 销 session |
| GET | `/api/auth/me` | 登录 | 用户信息 + 用量 |
| POST | `/api/auth/password` | 登录 | 改自己密码 |
| GET | `/api/users` | 管理员 | 用户列表 + 用量 |
| POST | `/api/users` | 管理员 | 建用户 |
| PATCH | `/api/users/{id}` | 管理员 | 改配额/压缩/角色/密码/启用 |
| DELETE | `/api/users/{id}?purge=` | 管理员 | 删用户（默认图片转交 admin） |
| POST | `/api/upload` | 登录 | multipart `files` + `tag`；`/api/admin/upload` 保留为别名 |
| DELETE | `/api/images/{id}` | 本人/管理员 | 删图（三份文件 + 记录） |
| PATCH | `/api/images/{id}` | 本人/管理员 | `{filename?, tag?}` 重命名/改标签 |
| GET | `/api/tags` | 公开 | 标签 + 计数 |
| GET | `/api/images` | 公开 | 新增 `tag`、`mine` 参数 |

兼容：`/api/random*`、`/api/public/settings`、`/api/admin/settings`、`/api/admin/reindex`、`/api/admin/bans` 全部保留。

---

## 四、前端改动

| 文件 | 改动 |
|---|---|
| `api.js` | 新增 auth/users/tags/patch/delete 请求；`absUrl` 走 `share_base_url` |
| `auth.js` | token 双存储（remember）、`user` 对象、`isAdmin`、`logout`、`refreshMe`；`ui` 状态（activeTag / viewSize / onlyMine） |
| `App.vue` | 顶栏用户菜单 + 退出登录；标签 chips 可点筛选 + 计数；尺寸档位切换；导航按角色显隐 |
| `views/Login.vue` | **新增**：账号密码 + 记住我 + 管理员 Token 兼容入口 |
| `views/Gallery.vue` | 瀑布流 + 三档尺寸 + 标签/我的筛选 + 右键重命名/删除 + 灯箱内操作 |
| `views/Upload.vue` | 标签多选（默认值）、粘贴上传、配额条、结果可复制（走分享基址） |
| `views/Admin.vue` | 新增「分享与标签」「用户管理」两组；无权限时只渲染「我的用量」 |
| `views/ApiDoc.vue` | 补新接口文档 |
| `components/LockGate.vue` | 引导到登录页 |
| `style.css` | 瀑布流、用户菜单、chips、配额条、右键菜单分隔线等样式 |

---

## 五、验收清单（逐条跑）

1. 未配置 `share_base_url` → 复制链接为当前 origin；配置后 → 使用配置值。
2. 点标签 → 只显示该标签图；再点取消；`/api/tags` 计数正确。
3. 上传页默认标签预选；粘贴剪贴板图片能上传。
4. 新上传文件落在 `uploads/YYYYMMDD/`；PATCH 重命名后原图/压缩/缩略图三者同名且 URL 可访问。
5. 画廊为瀑布流（不裁切），三档尺寸切换生效。
6. 管理员建用户配额 1MB → 该用户上传超限被拒；压缩参数覆盖生效；普通用户后台只看到用量与上传。
7. 右键删除：本人成功、他人 403、游客无菜单项；文件确实被删。
8. 登录：不勾记住 → sessionStorage + 12h；勾选 → localStorage + 30d；退出后 token 失效（`/api/auth/me` 401）。
9. `vite build` 通过；后端 `python -c "import app.main"` 无错。

---

## 六、不在本次范围

- 用户注册（仍由管理员建号，符合私人图床定位）
- 图片编辑/裁切、相册分组、对象存储多后端
- Docker 相关（本机无 Docker，NAS 侧逻辑不变）
