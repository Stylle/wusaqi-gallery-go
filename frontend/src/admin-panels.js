export const panels = [
  { id: 'site', icon: '🏷️', label: '站点外观', fields: [
    { k: 'site_title', label: '站点标题', hint: '浏览器标签页与顶栏显示' },
    { k: 'site_icon', label: '站点图标', hint: '填图片 URL 或单个 emoji（如 🌶️）；留空使用默认 logo' },
    { k: 'site_tags', label: '标签池', hint: '逗号分隔，作为上传候选；画廊只显示有图片的标签' },
    { k: 'site_footer', label: '底部文字', hint: '页脚展示，可留空隐藏' },
    { k: 'theme_style', label: '配色风格', type: 'select',
      options: [{ v: 'solid', label: '纯色' }, { v: 'gradient', label: '炫彩' }],
      hint: '纯色 = 单一主色，素净清爽；炫彩 = 渐变彩色，更活泼' },
  ] },
  { id: 'share', icon: '🔗', label: '访问分享', fields: [
    { k: 'site_public', label: '允许站点公开访问', type: 'switch', hint: '关闭后画廊、标签、随机图与全部外链均需登录或停止公开服务；登录入口保留' },
    { k: 'external_links_enabled', label: '允许图片外链', type: 'switch', hint: '关闭后原图、压缩图、缩略图的分享地址全部失效；站内浏览不受影响' },
    { k: 'share_base_url', label: '分享基址', hint: '复制链接用的域名，如 https://img.example.com；留空 = 用当前访问地址' },
    { k: 'upload_default_tags', label: '上传默认标签', hint: '逗号分隔，上传页默认选中第一个' },
  ] },
  { id: 'copyright', icon: '©', label: '版权联系', fields: [
    { k: 'copyright_notice', label: '版权与违规说明', type: 'textarea', hint: '显示在页脚，留空可隐藏；最多 500 字' },
    { k: 'copyright_contact', label: '联系方式', hint: '如邮箱、QQ 或其他联系方式，最多 500 字；以纯文字显示' },
  ] },
  { id: 'compress', icon: '🗜️', label: '图片压缩', custom: 'compress' },
  { id: 'limits', icon: '📤', label: '上传限制', fields: [
    { k: 'upload_max_mb', label: '全局单图上限 (MB，0=不限)', type: 'number',
      hint: '默认 5MB；用户级「单图上限」优先于此项，管理员不受限' },
    { k: 'new_user_quota_mb', label: '新用户默认容量配额 (MB，0=不限)', type: 'number' },
    { k: 'new_user_max_upload_mb', label: '新用户默认单图上限 (MB，0=跟随全局)', type: 'number' },
    { k: 'new_user_daily', label: '新用户每日上传张数 (0=不限)', type: 'number' },
    { k: 'new_user_weekly', label: '新用户每周上传张数 (0=不限)', type: 'number' },
    { k: 'new_user_monthly', label: '新用户每月上传张数 (0=不限)', type: 'number' },
  ], hint: '上面 5 项只是「新建用户」时表单的默认值，建好后可在用户管理里单独改；管理员始终不受上传张数、单图与容量限制。' },
  { id: 'login', icon: '🔐', label: '登录设置', fields: [
    { k: 'session_hours', label: '未勾「记住我」有效期 (小时)', type: 'number' },
    { k: 'remember_days', label: '勾选「记住我」有效期 (天)', type: 'number' },
    { k: 'random_public', label: '随机图 API 对游客开放', type: 'switch', hint: '同时受站点公开访问、外链总开关与标签外链规则限制；私密图片不对外开放' },
  ] },
  { id: 'users', icon: '👥', label: '用户管理', custom: 'users' },
  { id: 'traffic', icon: '🚦', label: '流量限制', fields: [
    { k: 'rate_limit', label: '随机图限流 (次/分钟/IP，0=关闭)', type: 'number' },
    { k: 'rate_ban_minutes', label: '超限封禁时长 (分钟)', type: 'number' },
  ] },
  { id: 'stats', icon: '📊', label: '访问统计', custom: 'stats' },
  { id: 'security', icon: '🛡️', label: '登录防护', fields: [
    { k: 'auth_max_fails', label: '鉴权失败次数阈值 (10分钟内)', type: 'number' },
    { k: 'auth_ban_minutes', label: '触发后封禁时长 (分钟)', type: 'number' },
  ] },
  { id: 'notify', icon: '📣', label: '事件通知', custom: 'notify' },
  { id: 'telegram', icon: '✈️', label: '电报接入', custom: 'telegram' },
  { id: 'bans', icon: '🚫', label: '封禁名单', custom: 'bans' },
  { id: 'local', icon: '📥', label: '图库维护', custom: 'local' },
  { id: 'backup', icon: '💾', label: '备份恢复', custom: 'backup' },
  { id: 'apidoc', icon: '📡', label: '接口文档', custom: 'apidoc' },
]

// Navigation order and grouping are independent of the panel field definitions.
export const groups = [
  { title: '站点设置', items: ['site', 'share', 'copyright', 'stats'] },
  { title: '图片管理', items: ['compress', 'limits', 'local', 'backup'] },
  { title: '账号安全', items: ['login', 'users', 'traffic', 'security', 'bans'] },
  { title: '消息接入', items: ['notify', 'telegram'] },
  { title: '开发工具', items: ['apidoc'] },
].map(group => ({ ...group, items: group.items.map(id => panels.find(panel => panel.id === id)) }))

