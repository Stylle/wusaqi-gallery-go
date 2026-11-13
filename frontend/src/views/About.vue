<script setup>
import { t } from '../i18n.js'
const repository = 'https://github.com/Stylle/wusaqi-gallery-go'
</script>

<template>
  <section class="about-page" aria-labelledby="about-title">
    <header class="about-header">
      <img src="/logo.svg" alt="" width="52" height="52" />
      <div><p class="about-eyebrow">Wusaqi Gallery</p><h1 id="about-title">{{ t('关于项目') }}</h1></div>
    </header>
    <p class="about-lead">{{ t('轻量、自部署的图片画廊与随机图服务，让图片管理更简单。') }}</p>
    <div class="about-features">
      <article><h2>{{ t('浏览与整理') }}</h2><p>{{ t('瀑布流浏览、标签筛选、批量管理与图片下载，适配桌面和手机。') }}</p></article>
      <article><h2>{{ t('上传与处理') }}</h2><p>{{ t('支持断点上传、照片元数据清理，以及缩略图和压缩图的后台处理。') }}</p></article>
      <article><h2>{{ t('访问与分享') }}</h2><p>{{ t('提供私密标签、可撤销外链、随机图 API 和管理员 Telegram 机器人。') }}</p></article>
    </div>
    <section class="about-repository">
      <h2>{{ t('项目仓库') }}</h2>
      <p>{{ t('在 GitHub 查看源代码、部署文档和更新，或提交问题与建议。') }}</p>
      <a class="about-repo-address mono" :href="repository" target="_blank" rel="noopener noreferrer">{{ repository }}</a>
      <div class="about-actions">
        <a class="link-button about-primary" :href="repository" target="_blank" rel="noopener noreferrer">{{ t('打开 GitHub 仓库') }} ↗</a>
        <a class="link-button" :href="repository + '/blob/main/docs/guide.md'" target="_blank" rel="noopener noreferrer">{{ t('使用与部署指南') }} ↗</a>
      </div>
    </section>
    <p class="about-note muted">{{ t('项目使用 Go、Vue 3 与 SQLite 构建，支持 Docker 单容器部署。站点内容及图片由部署者管理。') }}</p>
  </section>
</template>
