<script setup>
function go() { location.hash = '#/login' }
</script>

<template>
  <div class="lockbox">
    <div class="icon">🔒</div>
    <h2 class="page-title">需要登录</h2>
    <p class="muted">游客可以浏览画廊；上传、随机图、复制链接与后台需要登录。</p>
    <button @click="go">去登录</button>
  </div>
</template>
