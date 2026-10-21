<template>
  <h2>API</h2>
  <p class="muted">所有响应与 lolis.im 原站结构对齐，前端/脚本可无缝替换。</p>

  <h3>公开接口</h3>
  <pre>GET /api/images?page=1&amp;limit=24&amp;sort=latest|random
  → { items: [...], page, limit, total, hasMore }
  item: { id, key, url(原图), thumb(缩略图), compressed(压缩图), width, height,
          mimeType, size, compressedSize, createdAt }

GET /api/random?variant=compressed|original
  → 随机一张，返回 JSON 元数据
GET /api/random?variant=compressed&amp;redirect=true
  → 302 跳到对应图片文件
GET /api/random/image?variant=compressed|original
  → 302 跳到对应图片文件（外链/Markdown 直链用）</pre>

  <h3>管理接口（Header: <code>Authorization: Bearer &lt;ADMIN_TOKEN&gt;</code>）</h3>
  <pre>POST /api/admin/upload     multipart: files=@a.png files=@b.jpg（批量）
POST /api/admin/verify     校验 Token
GET  /api/admin/settings   读取压缩设置
PUT  /api/admin/settings   {"format":"webp","quality":80,"max_width":2560}
POST /api/admin/reindex    扫描存储目录重建索引</pre>

  <h3>用法示例</h3>
  <pre># 随机压缩图直链（Markdown）
![random](https://your-host/api/random/image?variant=compressed)

# 上传
curl -H "Authorization: Bearer $TOKEN" \
     -F "files=@pic.jpg" http://your-host/api/admin/upload

# 调整压缩参数（之后上传的新图生效）
curl -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"format":"webp","quality":75,"max_width":1920}' \
     http://your-host/api/admin/settings</pre>

  <h3>省流量设计</h3>
  <p>
    每张图上传后生成三份文件：<code>files/</code> 原图、<code>compressed/</code> 压缩版（格式/质量/最大宽度后台可调）、
    <code>thumbs/</code> 缩略图。画廊只加载缩略图，外链默认给压缩图 URL，原图仅在明确请求时出网；
    nginx 对图片返回一年期 immutable 缓存，重复访问不走流量；随机接口带每 IP 限流。
  </p>
</template>
