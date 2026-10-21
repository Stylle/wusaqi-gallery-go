<template>
  <div class="lockbox">
    <div class="icon">🔒</div>
    <h2 class="page-title">需要管理员登录</h2>
    <p class="muted">游客模式只能浏览画廊；复制链接、随机图、上传与后台配置都需要登录。</p>
    <button @click="location.hash = '#/upload'">去登录（Upload 页输入 Token）</button>
  </div>
</template>
