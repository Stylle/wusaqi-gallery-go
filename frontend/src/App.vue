<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import Gallery from './views/Gallery.vue'
import Random from './views/Random.vue'
import Upload from './views/Upload.vue'
import Admin from './views/Admin.vue'
import Login from './views/Login.vue'
import About from './views/About.vue'
import ThemeSwitch from './components/ThemeSwitch.vue'
import ScrollControls from './components/ScrollControls.vue'
import LockGate from './components/LockGate.vue'
import {
  store, ui, isAdmin, ensureAuth, loadSite, doLogout, setViewSize, clearToken,
} from './auth.js'
import { site } from './site.js'
import { changePassword, fmtSize, setUnauthHandler } from './api.js'
import { i18n, t, setLang } from './i18n.js'

const views = {
  gallery: Gallery, random: Random, upload: Upload,
  admin: Admin, login: Login, about: About,
}
// 需要登录的页面
const locked = { random: true, upload: true, admin: true }
const route = ref('gallery')
// A single state prevents the account and navigation panels opening together.
const openMenu = ref(null)
const menuOpen = computed(() => openMenu.value === 'user')
const navOpen = computed(() => openMenu.value === 'nav')
const navTrigger = ref(null)
const userTrigger = ref(null)
function closeMenus() { openMenu.value = null }
function toggleMenu(name) { openMenu.value = openMenu.value === name ? null : name }
const pwdOpen = ref(false)
const pwdMsg = ref('')
const pwdBusy = ref(false)
const pwdForm = ref({ old: '', new: '' })

// 校验中（有 token 但还没验完）不闪锁屏：交给页面内的 ensureAuth 处理
const needsLogin = computed(() => !!locked[route.value] || (site.site_public !== '1' && !['login', 'about'].includes(route.value)))
const isLocked = computed(() =>
  needsLogin.value && !(route.value === 'random' && site.random_public === '1' && site.site_public === '1') && !store.ok && (store.checked || !store.token))
const authPending = computed(() => needsLogin.value && !!store.token && !store.checked && !store.ok)

// 全局「登录已失效」提示
const authNotice = ref('')
let noticeTimer = null
function showAuthNotice(text) {
  authNotice.value = text
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { authNotice.value = '' }, 4000)
}
const usedPct = computed(() => {
  const u = store.user
  if (!u || !u.quotaMb) return 0
  return Math.min(100, Math.round(u.usedBytes / (u.quotaMb * 1024 * 1024) * 100))
})

function go(r) {
  location.hash = `#/${r}`
  closeMenus()
}

function sync() {
  closeMenus()
  const h = location.hash.replace(/^#\/?/, '') || 'gallery'
  const next = views[h] ? h : 'gallery'
  if (next !== route.value) {
    route.value = next
    window.scrollTo({ top: 0, behavior: 'instant' })
  }
}

async function logout() {
  await doLogout()
  closeMenus()
  go('gallery')
}

async function submitPwd() {
  if (pwdBusy.value) return
  pwdBusy.value = true
  pwdMsg.value = t('提交中…')
  try {
    await changePassword(store.token, pwdForm.value.old, pwdForm.value.new)
    pwdMsg.value = t('密码已修改 ✓')
    pwdForm.value = { old: '', new: '' }
  } catch (e) {
    pwdMsg.value = t('失败：') + e.message
  } finally { pwdBusy.value = false }
}

function toggleLang() {
  setLang(i18n.lang === 'zh' ? 'en' : 'zh')
}

function onDocClick() { closeMenus() }
function onKeydown(event) {
  if (event.key !== 'Escape' || !openMenu.value) return
  const trigger = openMenu.value === 'nav' ? navTrigger.value : userTrigger.value
  closeMenus()
  trigger?.focus()
}

// 当前是否还持有 token（401 回调里用来区分「会话过期」和「密码输错」）
function readTokenExists() {
  return !!(localStorage.getItem('lg_token') || sessionStorage.getItem('lg_token') || store.token)
}

onMounted(() => {
  sync()
  window.addEventListener('hashchange', sync)
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
  loadSite()
  // 任意请求返回 401 → 提示并回到未登录态（登录页输错密码不算）
  setUnauthHandler(() => {
    if (!readTokenExists()) return
    clearToken()
    showAuthNotice(t('登录已失效，请重新登录'))
  })
  ensureAuth()
})
onUnmounted(() => {
  window.removeEventListener('hashchange', sync)
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <header class="topbar" :class="{ open: navOpen }">
    <span class="logo" @click="go('gallery')">
      <img src="/logo.svg" alt="" class="logo-img" />
      <span>{{ site.site_title }}</span>
    </span>

    <button ref="navTrigger" class="hamburger" :aria-expanded="navOpen" :aria-label="t('菜单')" aria-controls="site-navigation"
      @click.stop="toggleMenu('nav')">{{ navOpen ? '✕' : '☰' }}</button>

    <nav id="site-navigation" @click="closeMenus">
      <a href="#/gallery" :class="{ active: route === 'gallery' }">{{ t('画廊') }}</a>
      <a href="#/random" :class="{ active: route === 'random' }">{{ t('随机图') }}</a>
      <a href="#/upload" :class="{ active: route === 'upload' }">{{ t('上传') }}</a>
      <a href="#/about" :class="{ active: route === 'about' }">{{ t('关于') }}</a>

      <!-- 手机端导航面板内附主题 / 语言切换（桌面隐藏） -->
      <div class="nav-mobile" @click.stop>
        <ThemeSwitch />
        <div class="theme-switch lang-switch">
          <button :class="{ on: i18n.lang === 'zh' }" @click="setLang('zh')">中文</button>
          <button :class="{ on: i18n.lang === 'en' }" @click="setLang('en')">English</button>
        </div>
      </div>
    </nav>

    <div class="desk-theme appearance-controls">
      <ThemeSwitch compact />
      <button class="ghost lang-toggle" :title="t('切换语言')" :aria-label="t('切换语言')" @click="toggleLang">{{ i18n.lang === 'zh' ? '中' : 'EN' }}</button>
    </div>

    <div class="user-area" v-if="store.ok" @click.stop>
      <button ref="userTrigger" class="user-chip" :aria-expanded="menuOpen" :aria-label="t('账户菜单')" aria-controls="account-menu" @click="toggleMenu('user')">
        <span class="avatar">{{ (store.user?.username || '?')[0].toUpperCase() }}</span>
        <span class="uname">{{ store.user?.username }}</span>
        <span class="role-badge" v-if="isAdmin">{{ t('管理员') }}</span>
        <span class="role-badge user" v-else>{{ t('用户') }}</span>
        <span class="caret">▾</span>
      </button>
      <div id="account-menu" class="user-menu" v-if="menuOpen">
        <div class="um-head">
          <div class="um-name">{{ store.user?.username }}</div>
          <div class="um-quota" v-if="store.user?.quotaMb">
            {{ t('已用') }} {{ fmtSize(store.user.usedBytes) }} / {{ store.user.quotaMb }} MB
            <div class="bar"><div :style="{ width: usedPct + '%' }"></div></div>
          </div>
          <div class="um-quota" v-else>{{ t('不限容量') }} · {{ store.user?.imageCount || 0 }} {{ t('张') }}</div>
        </div>
        <button @click="go('admin')">⚙️ {{ isAdmin ? t('后台管理') : t('我的空间') }}</button>
        <button @click="pwdOpen = true; closeMenus()">🔑 {{ t('修改密码') }}</button>
        <button class="danger" @click="logout">🚪 {{ t('退出登录') }}</button>
      </div>
    </div>
    <button v-else class="ghost login-btn" @click="go('login')">{{ t('登录') }}</button>
  </header>

  <main class="wrap" :class="{ 'gallery-wrap': route === 'gallery' && !isLocked && !authPending }">
    <div v-if="authPending" class="lockbox" role="status">{{ t('正在验证登录…') }}</div>
    <LockGate v-else-if="isLocked" :server-error="store.authError === 'server'" />
    <component v-else :is="views[route]" />
  </main>

  <footer class="site-footer" v-if="site.site_footer || site.copyright_notice || site.copyright_contact">
    <div v-if="site.site_footer">{{ site.site_footer }}</div>
    <p v-if="site.copyright_notice" class="copyright-notice">{{ site.copyright_notice }}</p>
    <p v-if="site.copyright_contact" class="copyright-contact">{{ t('联系方式') }}：{{ site.copyright_contact }}</p>
  </footer>

  <ScrollControls />

  <div v-if="authNotice" class="auth-notice" @click="authNotice = ''">
    {{ authNotice }}
    <a href="#/login">{{ t('去登录') }}</a>
  </div>

  <!-- 修改密码 -->
  <div v-if="pwdOpen" class="lightbox" @click.self="pwdOpen = false">
    <div class="modal">
      <h3>{{ t('修改密码') }}</h3>
      <div class="field">
        <label>{{ t('当前密码') }}</label>
        <input v-model="pwdForm.old" type="password" autocomplete="current-password" />
      </div>
      <div class="field">
        <label>{{ t('新密码（至少 6 位）') }}</label>
        <input v-model="pwdForm.new" type="password" autocomplete="new-password" @keyup.enter="submitPwd" />
      </div>
      <p class="hint muted">{{ pwdMsg }}</p>
      <div class="row">
        <button :disabled="pwdBusy" @click="submitPwd">{{ pwdBusy ? t('提交中…') : t('确认修改') }}</button>
        <button class="ghost" @click="pwdOpen = false">{{ t('取消') }}</button>
      </div>
    </div>
  </div>
</template>
