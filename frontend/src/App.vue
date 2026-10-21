<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import Gallery from './views/Gallery.vue'
import Random from './views/Random.vue'
import Upload from './views/Upload.vue'
import Admin from './views/Admin.vue'
import ApiDoc from './views/ApiDoc.vue'
import About from './views/About.vue'
import LockGate from './components/LockGate.vue'
import { theme, setTheme } from './theme.js'
import { store, checkAuth, loadSite, siteTags } from './auth.js'

const views = { gallery: Gallery, random: Random, upload: Upload, admin: Admin, api: ApiDoc, about: About }
// 需要登录的页面
const locked = { random: true, upload: true, admin: true, api: true }
const route = ref('gallery')

const isLocked = computed(() => locked[route.value] && !store.ok)

function sync() {
  const h = location.hash.replace(/^#\/?/, '') || 'gallery'
  route.value = views[h] ? h : 'gallery'
}
onMounted(async () => {
  sync()
  window.addEventListener('hashchange', sync)
  loadSite()
  await checkAuth()
})
onUnmounted(() => window.removeEventListener('hashchange', sync))
</script>

<template>
  <header class="topbar">
    <span class="logo" @click="location.hash = '#/gallery'">{{ store.site.site_title }}</span>
    <nav>
      <a href="#/gallery" :class="{ active: route === 'gallery' }">Gallery</a>
      <a href="#/random" :class="{ active: route === 'random', locked: isLocked && route !== 'random' }"
        @click="isLocked && route !== 'random' && $event.preventDefault()">Random</a>
      <a href="#/upload" :class="{ active: route === 'upload' }">Upload</a>
      <a href="#/admin" :class="{ active: route === 'admin' }">后台</a>
      <a href="#/api" :class="{ active: route === 'api' }">API</a>
      <a href="#/about" :class="{ active: route === 'about' }">About</a>
    </nav>
    <span class="auth-badge" :title="store.ok ? '已登录' : '游客模式：仅可浏览画廊'">
      <span class="dot" :class="store.ok ? 'on' : 'off'"></span>
      {{ store.ok ? '已登录' : '游客' }}
    </span>
    <div class="theme-switch" title="主题">
      <button :class="{ on: theme.pref === 'light' }" @click="setTheme('light')">☀️</button>
      <button :class="{ on: theme.pref === 'dark' }" @click="setTheme('dark')">🌙</button>
      <button :class="{ on: theme.pref === 'system' }" @click="setTheme('system')">💻</button>
    </div>
  </header>

  <main class="wrap">
    <div class="tags" v-if="siteTags().length">
      <span v-for="t in siteTags()" :key="t" class="tag">{{ t }}</span>
    </div>
    <LockGate v-if="isLocked" />
    <component v-else :is="views[route]" />
  </main>

  <footer class="site-footer" v-if="store.site.site_footer">{{ store.site.site_footer }}</footer>
</template>
