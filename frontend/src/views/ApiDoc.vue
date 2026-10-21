<template>
  <h2 class="page-title">API</h2>
  <p class="muted">默认随机图接口仅登录可用（Header 带 Bearer Token）；后台「流量与权限 → 访问权限」开启公开后可裸外链。</p>

  <h3>公开接口（游客）</h3>
  <pre>GET /api/public/settings     站点公开信息（标题/标签/页脚/图标）
GET /api/images?page=1&amp;limit=24&amp;sort=latest|random
  → { items: [...], page, limit, total, hasMore }
  item: { id, key, url(原图), thumb(缩略图), compressed(压缩图), width, height,
          mimeType, size, compressedSize, createdAt }</pre>

  <h3>随机图（登录可用；后台可开放为公开）</h3>
  <pre>GET /api/random?variant=compressed|original[&amp;redirect=true]
GET /api/random/image?variant=compressed|original   # 302 直链</pre>

  <h3>管理接口（Header: <code>Authorization: Bearer &lt;ADMIN_TOKEN&gt;</code>）</h3>
  <pre>POST /api/admin/upload     multipart: files=@a.png（单文件循环上传可获得逐文件进度）
POST /api/admin/verify
GET  /api/admin/settings   全部配置
PUT  /api/admin/settings   {"site_title":"...","comp_quality":80,"rate_limit":120,...}
POST /api/admin/reindex
GET  /api/admin/bans       当前封禁列表</pre>

  <h3>用法示例</h3>
  <pre># 随机压缩图直链（开放公开后可直接用于 Markdown）
![random](https://your-host/api/random/image?variant=compressed)

# 上传（带进度建议前端逐文件调用）
curl -H "Authorization: Bearer $TOKEN" \
     -F "files=@pic.jpg" http://your-host/api/admin/upload

# 后台改任意配置（键见 /api/admin/settings 返回值）
curl -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"site_title":"我的画廊","comp_format":"webp","rate_limit":60,"webhook_url":"https://..."}' \
     http://your-host/api/admin/settings</pre>

  <h3>防御机制</h3>
  <p>
    随机图接口每 IP 每分钟限流（后台可调），超限 → webhook 通知 + 封禁 10 分钟（可调）；
    鉴权失败 10 分钟内累计超阈值 → 封禁；所有静态文件路径由框架白名单伺服，无目录遍历面；
    图片 URL 一年期 immutable 缓存，重复访问不耗流量。
  </p>
</template>
