<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import Gallery from './views/Gallery.vue'
import Random from './views/Random.vue'
import Upload from './views/Upload.vue'
import Admin from './views/Admin.vue'
import Login from './views/Login.vue'
import LockGate from './components/LockGate.vue'
import { theme, setTheme } from './theme.js'
import {
  store, ui, isAdmin, checkAuth, loadSite, doLogout, setViewSize,
} from './auth.js'
import { site } from './site.js'
import { changePassword, fmtSize } from './api.js'
import { i18n, t, setLang } from './i18n.js'

const views = {
  gallery: Gallery, random: Random, upload: Upload,
  admin: Admin, login: Login,
}
// 需要登录的页面
const locked = { random: true, upload: true, admin: true }
const route = ref('gallery')
const menuOpen = ref(false)        // 用户下拉
const navOpen = ref(false)         // 手机端汉堡菜单
const pwdOpen = ref(false)
const pwdMsg = ref('')
const pwdForm = ref({ old: '', new: '' })

const isLocked = computed(() => locked[route.value] && !store.ok)
const usedPct = computed(() => {
  const u = store.user
  if (!u || !u.quotaMb) return 0
  return Math.min(100, Math.round(u.usedBytes / (u.quotaMb * 1024 * 1024) * 100))
})

function go(r) {
  location.hash = `#/${r}`
  menuOpen.value = false
  navOpen.value = false
}

function sync() {
  const h = location.hash.replace(/^#\/?/, '') || 'gallery'
  route.value = views[h] ? h : 'gallery'
}

async function logout() {
  await doLogout()
  menuOpen.value = false
  go('gallery')
}

async function submitPwd() {
  pwdMsg.value = t('提交中…')
  try {
    await changePassword(store.token, pwdForm.value.old, pwdForm.value.new)
    pwdMsg.value = t('密码已修改 ✓')
    pwdForm.value = { old: '', new: '' }
  } catch (e) {
    pwdMsg.value = t('失败：') + e.message
  }
}

function toggleLang() {
  setLang(i18n.lang === 'zh' ? 'en' : 'zh')
}

function onDocClick() { menuOpen.value = false; navOpen.value = false }

onMounted(() => {
  sync()
  window.addEventListener('hashchange', sync)
  document.addEventListener('click', onDocClick)
  loadSite()
  checkAuth()
})
onUnmounted(() => {
  window.removeEventListener('hashchange', sync)
  document.removeEventListener('click', onDocClick)
})
</script>

<template>
  <header class="topbar" :class="{ open: navOpen }">
    <span class="logo" @click="go('gallery')">
      <img src="/logo.svg" alt="" class="logo-img" />
      <span>{{ site.site_title }}</span>
    </span>

    <button class="hamburger" :aria-expanded="navOpen" :aria-label="t('菜单')"
      @click.stop="navOpen = !navOpen">{{ navOpen ? '✕' : '☰' }}</button>

    <nav @click="navOpen = false">
      <a href="#/gallery" :class="{ active: route === 'gallery' }">{{ t('画廊') }}</a>
      <a href="#/random" :class="{ active: route === 'random' }">{{ t('随机图') }}</a>
      <a href="#/upload" :class="{ active: route === 'upload' }">{{ t('上传') }}</a>

      <!-- 手机端导航面板内附主题切换（桌面隐藏） -->
      <div class="nav-mobile" @click.stop>
        <div class="theme-switch">
          <button :class="{ on: theme.pref === 'light' }" @click="setTheme('light')">☀️ {{ t('亮色') }}</button>
          <button :class="{ on: theme.pref === 'dark' }" @click="setTheme('dark')">🌙 {{ t('暗色') }}</button>
          <button :class="{ on: theme.pref === 'system' }" @click="setTheme('system')">💻 {{ t('跟随系统') }}</button>
        </div>
      </div>
    </nav>

    <div class="theme-switch desk-theme" title="Theme / 语言">
      <button :class="{ on: theme.pref === 'light' }" @click="setTheme('light')">☀️</button>
      <button :class="{ on: theme.pref === 'dark' }" @click="setTheme('dark')">🌙</button>
      <button :class="{ on: i18n.lang === 'zh' }" @click="toggleLang">{{ i18n.lang === 'zh' ? '中' : 'EN' }}</button>
    </div>

    <div class="user-area" v-if="store.ok" @click.stop>
      <button class="user-chip" @click="menuOpen = !menuOpen">
        <span class="avatar">{{ (store.user?.username || '?')[0].toUpperCase() }}</span>
        <span class="uname">{{ store.user?.username }}</span>
        <span class="role-badge" v-if="isAdmin">{{ t('管理员') }}</span>
        <span class="role-badge user" v-else>{{ t('用户') }}</span>
        <span class="caret">▾</span>
      </button>
      <div class="user-menu" v-if="menuOpen">
        <div class="um-head">
          <div class="um-name">{{ store.user?.username }}</div>
          <div class="um-quota" v-if="store.user?.quotaMb">
            {{ t('已用') }} {{ fmtSize(store.user.usedBytes) }} / {{ store.user.quotaMb }} MB
            <div class="bar"><div :style="{ width: usedPct + '%' }"></div></div>
          </div>
          <div class="um-quota" v-else>{{ t('不限容量') }} · {{ store.user?.imageCount || 0 }} {{ t('张') }}</div>
        </div>
        <button @click="go('upload'); menuOpen = false">⬆️ {{ t('上传') }}</button>
        <button @click="go('admin'); menuOpen = false">⚙️ {{ isAdmin ? t('后台管理') : t('我的空间') }}</button>
        <button @click="pwdOpen = true; menuOpen = false">🔑 {{ t('修改密码') }}</button>
        <button class="danger" @click="logout">🚪 {{ t('退出登录') }}</button>
      </div>
    </div>
    <button v-else class="ghost login-btn" @click="go('login')">{{ t('登录') }}</button>
  </header>

  <main class="wrap">
    <LockGate v-if="isLocked" />
    <component v-else :is="views[route]" />
  </main>

  <footer class="site-footer" v-if="site.site_footer">{{ site.site_footer }}</footer>

  <!-- 修改密码 -->
  <div v-if="pwdOpen" class="lightbox" @click.self="pwdOpen = false">
    <div class="modal">
      <h3>{{ t('修改密码') }}</h3>
      <div class="field">
        <label>{{ t('当前密码') }}</label>
        <input v-model="pwdForm.old" type="password" />
      </div>
      <div class="field">
        <label>{{ t('新密码（至少 6 位）') }}</label>
        <input v-model="pwdForm.new" type="password" @keyup.enter="submitPwd" />
      </div>
      <p class="hint muted">{{ pwdMsg }}</p>
      <div class="row">
        <button @click="submitPwd">{{ t('确认修改') }}</button>
        <button class="ghost" @click="pwdOpen = false">{{ t('取消') }}</button>
      </div>
    </div>
  </div>
</template>
