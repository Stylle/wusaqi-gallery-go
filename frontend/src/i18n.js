import { reactive } from 'vue'

// 轻量 i18n：中文原文作键，英文映射查表；查不到回落显示中文原文。
// 用法：模板里 {{ t('登录') }}；语言切换即时生效（t 读取 reactive 状态）。
export const i18n = reactive({
  lang: localStorage.getItem('lg_lang')
    || (navigator.language?.toLowerCase().startsWith('zh') ? 'zh' : 'en'),
})

const EN = {
  // 顶栏 / 通用
  '画廊': 'Gallery', '随机图': 'Random', '上传': 'Upload', '登录': 'Sign in',
  '亮色': 'Light', '暗色': 'Dark', '跟随系统': 'System', '菜单': 'Menu',
  '管理员': 'Admin', '用户': 'User', '后台管理': 'Dashboard', '我的空间': 'My space',
  '修改密码': 'Change password', '退出登录': 'Sign out',
  '当前密码': 'Current password', '新密码（至少 6 位）': 'New password (min 6 chars)',
  '确认修改': 'Save', '取消': 'Cancel', '保存': 'Save',
  '密码已修改 ✓': 'Password changed ✓', '提交中…': 'Submitting…',
  '失败：': 'Failed: ',
  '登录已失效，请重新登录': 'Session expired, please sign in again',
  '去登录': 'Sign in',
  '设置已保存 ✓': 'Settings saved ✓',
  '保存中…': 'Saving…',
  '已保存 ✓（压缩方案对新上传生效）': 'Saved ✓ (compression applies to new uploads)',
  '发送失败 ✗': 'Send failed ✗',
  '未知错误': 'Unknown error',
  // 登录页
  '登录后可上传图片、复制链接与使用随机图 API。': 'Sign in to upload, copy links and use the random API.',
  '用户名': 'Username', '密码': 'Password', '管理员 Token': 'Admin Token',
  '请填写 Token': 'Token required', '请填写用户名': 'Username required',
  '记住我（30 天内免登录；不勾选则关闭浏览器失效）': 'Remember me (30 days; otherwise ends with the browser session)',
  '登录中…': 'Signing in…',
  '尝试次数过多，已临时封禁，请稍后再试': 'Too many attempts, temporarily banned. Try later.',
  '← 用账号密码登录': '← Sign in with password', '用管理员 Token 登录': 'Sign in with admin token',
  '没有账号？联系管理员开通。': 'No account? Ask the administrator.',
  // 画廊
  '全部': 'All', '仅我的': 'Mine only', '小': 'S', '中': 'M', '大': 'L',
  '共': 'Total', '张 · 点击看大图': ' images · click to enlarge',
  '· 右键/长按可复制、重命名、删除': ' · right-click / long-press to copy, rename, delete',
  '上一页': 'Prev', '下一页': 'Next',
  '我的': 'Mine', '操作 ▾': 'Actions ▾', '重命名': 'Rename', '删除': 'Delete',
  '关闭 (Esc)': 'Close (Esc)',
  '复制原图 URL': 'Copy original URL', '复制压缩图 URL': 'Copy compressed URL',
  '复制缩略图 URL': 'Copy thumbnail URL', '下载原图': 'Download original', '下载压缩图': 'Download compressed',
  '✏️ 重命名': '✏️ Rename', '🗑️ 删除图片': '🗑️ Delete',
  '登录后可复制链接': 'Sign in to copy links',
  '该图没有这个版本': 'This version is not available', '已复制链接': 'Link copied',
  '游客不能复制链接，请先登录': 'Guests cannot copy links. Sign in first.',
  '该图没有压缩版': 'No compressed version',
  '已重命名': 'Renamed', '已删除（原图 + 压缩图 + 缩略图）': 'Deleted (original + compressed + thumbnail)',
  '处理中…': 'Working…', '文件名不能为空': 'Filename cannot be empty',
  '重命名': 'Rename', '会同时重命名原图、压缩图与缩略图（扩展名保持不变）。':
    'Renames original, compressed and thumbnail at once (extension kept).',
  '新文件名（不含扩展名）': 'New name (without extension)',
  '删除这张图？': 'Delete this image?',
  '原图、压缩图、缩略图都会被删除，且不可恢复。': 'Original, compressed and thumbnail will be removed. Irreversible.',
  '确认删除': 'Delete', '该筛选下还没有图片': 'No images under this filter', '还没有图片': 'No images yet',
  '压缩': 'zip', 'by ': 'by ',
  // 上传
  '需要登录': 'Sign-in required', '请先': 'Please', '登录': 'sign in', '后再上传。': ' before uploading.',
  '已用': 'Used', '剩余': 'Left', '不限容量': 'Unlimited',
  '标签': 'Tags', '无': 'None', '自定义标签…': 'Custom tag…', '默认：': 'Default: ',
  '拖拽图片到这里 / 点击选择 /': 'Drag images here / click to browse /',
  '直接粘贴上传': ' to paste',
  '可多选，逐个上传并显示进度；当前标签「': 'Multi-select supported. Current tag: "',
  '」': '"',
  '容量已用满（': 'Quota full (',
  '），请联系管理员扩容': '), contact the administrator',
  '今日上传已达上限（': 'Daily limit reached (',
  ' 张），明天再来或联系管理员调整': ' images). Try tomorrow or ask the administrator.',
  '支持': 'Formats: ', '（推荐 JPG / PNG / WebP） · 单图 ≤ ': '(JPG / PNG / WebP recommended) · max ',
  ' MB': ' MB', '不限': 'unlimited', '今日': 'Today', '本周': 'This week',
  ' 张': ' imgs', '复制压缩图': 'Copy compressed', '复制原图': 'Copy original', '复制缩略图': 'Copy thumb',
  '不是图片文件': 'Not an image file', '分享链接基址：': 'Share base URL: ',
  // 随机图
  '压缩图（省流量）': 'Compressed (saves traffic)', '原始图': 'Original',
  '，先去 Upload 传几张': '. Upload some first.',
  '再来一张': 'Another one', '复制当前图 URL': 'Copy image URL', '原窗口打开': 'Open in tab',
  '直链：': 'Direct link: ',
  '（当前仅登录可用，后台可开放）': '(sign-in required; can be made public in dashboard)',
  '请求太频繁，已被临时封禁': 'Too many requests, temporarily banned',
  // 后台
  '后台配置': 'Dashboard', '站点信息': 'Site', '图片处理': 'Images', '账号与权限': 'Accounts',
  '流量与安全': 'Traffic & Security', '媒体维护': 'Maintenance', '开发者': 'Developer',
  '站点与外观': '🏷️ Site & Look', '分享与上传': '🔗 Share & Upload',
  '站点标题': 'Site title', '站点图标': 'Site icon', '标签池': 'Tag pool', '底部文字': 'Footer text',
  '分享基址': 'Share base URL', '上传默认标签': 'Default upload tags',
  '压缩方案': '🗜️ Compression profile', '上传限制': '📤 Upload limits',
  '登录规则': '🔐 Login rules', '用户管理': '👥 Users',
  '流量防御': '🚦 Rate limiting', '访问统计': '📊 Access stats', '通知': '📣 Notifications',
  '防爆破': '🛡️ Brute-force guard', '本地图库导入': '📥 Local import', 'API 文档': '📡 API docs',
  '保存全部设置': 'Save all', '保存并应用': 'Save & apply', '刷新封禁列表': 'Refresh bans',
  '当前封禁': 'Active bans', '已保存 ✓': 'Saved ✓',
  '已保存 ✓（压缩方案对新上传生效）': 'Saved ✓ (applies to new uploads)',
  '新建用户': 'New user', '编辑用户': 'Edit user',
  '角色': 'Role', '普通用户': 'User', '容量配额 (MB，0=不限)': 'Quota (MB, 0 = unlimited)',
  '单图上限 (MB，0=跟随全局)': 'Per-image limit (MB, 0 = global)',
  '每日上传张数 (0=不限)': 'Daily uploads (0 = unlimited)',
  '每周上传张数 (0=不限)': 'Weekly uploads (0 = unlimited)',
  '每月上传张数 (0=不限)': 'Monthly uploads (0 = unlimited)',
  '压缩格式覆盖': 'Compression format', '跟随全局': 'Follow global',
  '压缩质量覆盖 (1-100，空=全局)': 'Quality override (1-100, empty = global)',
  '创建用户': 'Create user', '保存修改': 'Save changes', '取消编辑': 'Cancel',
  '提交中…': 'Submitting…', '已创建 ✓': 'created ✓', '已更新 ✓': 'Updated ✓',
  '编辑': 'Edit', '停用': 'Disable', '启用': 'Enable',
  '用量 / 配额': 'Usage / quota', '上传限制': 'Upload limits', '压缩参数': 'Compression', '状态': 'Status',
  '删除用户时其图片会转交给管理员（不丢图）。': 'Deleting a user transfers their images to the administrator.',
  '全局': 'Global', '正常': 'Active', '已停用': 'Disabled',
  '压缩格式（所有方案共用）': 'Compression format (shared by all profiles)',
  '方案对照': 'Profile comparison', '当前生效': 'Active profile',
  '自定义参数': 'Custom parameters', '支持的图片格式': 'Supported formats',
  '质量 (1-100)': 'Quality (1-100)', '最大宽度 px (0=不缩放)': 'Max width px (0 = no resize)',
  'webp 编码强度 (0-6)': 'webp effort (0-6)', '单图分辨率上限 (MP，0=不限)': 'Max megapixels (MP, 0 = unlimited)',
  '压缩并发数 (1-8)': 'Compression concurrency (1-8)',
  '推荐': 'Recommended', '可用': 'OK',
  '扫描本地原图': 'Scan local originals', '重新扫描': 'Rescan', '每次导入': 'Per batch',
  '导入': 'Import', '张': ' imgs', '补齐压缩版': 'Backfill compressed versions', '检查': 'Check',
  '每次处理': 'Per batch', '开始补': 'Backfill', '尚未扫描': 'Not scanned yet', '尚未检查': 'Not checked yet',
  '扫描中…': 'Scanning…', '导入中（会生成缩略图与压缩版，请稍候）…': 'Importing (generates thumbnails & compressed)…',
  '压缩中…': 'Compressing…', '检查中…': 'Checking…',
  '今日 PV': 'Today PV', '今日 UV': 'Today UV', '今日上传': 'Uploads today', '昨日上传': 'Uploads yesterday',
  '最近 3 天': 'Last 3 days', 'Top IP（请求数）': 'Top IPs (by requests)',
  '热门接口': 'Top endpoints', '归属地': 'Location', '请求数': 'Requests',
  '发送测试': 'Send test', '发送中…': 'Sending…',
  '测试通知已发送，请查收 ✓': 'Test notification sent ✓',
  '系统探测': 'Auto-detected', '探测到': 'Detected', '核 /': 'cores /',
  '自动选「': 'suggests "', '」': '"',
}

export function t(s) {
  return i18n.lang === 'zh' ? s : (EN[s] || s)
}

export function setLang(l) {
  i18n.lang = l
  localStorage.setItem('lg_lang', l)
  document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en'
}
