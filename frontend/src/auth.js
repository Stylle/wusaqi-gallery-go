import { reactive, computed } from 'vue'
import * as api from './api.js'
import { setSite } from './site.js'

// 登录态
export const store = reactive({
  token: '',
  user: null,
  ok: false,        // 已验证登录
  checked: false,   // 完成首次验证
  authError: '',    // '' | 'expired'（登录失效）| 'server'（后端不可达/5xx）
})

// 关键：模块加载时就把 token 读出来（同步）。
// 子组件（如后台 Admin）的 onMounted 早于 App 的 onMounted，
// 若等 checkAuth() 再赋值，首屏发出的请求会带着空 token → 401 "login required"。
store.token = localStorage.getItem('lg_token') || sessionStorage.getItem('lg_token') || ''

// 界面状态（画廊筛选 / 尺寸档位）
export const ui = reactive({
  activeTag: '',
  onlyMine: false,
  viewSize: localStorage.getItem('lg_size') || 'm',
})

export const isAdmin = computed(() => store.user?.role === 'admin')

export function setViewSize(s) {
  ui.viewSize = s
  localStorage.setItem('lg_size', s)
}

// ---------- token 存取：勾「记住我」→ localStorage(长效)，否则 sessionStorage(关浏览器失效) ----------
export function readToken() {
  return localStorage.getItem('lg_token') || sessionStorage.getItem('lg_token') || ''
}

export function setToken(t, remember) {
  store.token = t
  authPromise = null          // 新 token → 重新校验
  if (remember) {
    localStorage.setItem('lg_token', t)
    sessionStorage.removeItem('lg_token')
  } else {
    sessionStorage.setItem('lg_token', t)
    localStorage.removeItem('lg_token')
  }
}

export function clearToken() {
  localStorage.removeItem('lg_token')
  sessionStorage.removeItem('lg_token')
  store.token = ''
  store.user = null
  store.ok = false
  authPromise = null
}

/** 启动时恢复登录态（服务端 5xx/断连会自动重试，不当作登录失效） */
export async function checkAuth() {
  const t = readToken()
  if (t) store.token = t
  store.authError = ''
  if (store.token) {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        store.user = await api.me(store.token)
        store.ok = true
        store.authError = ''
        break
      } catch (e) {
        const status = e && e.status
        if (status === 401 || status === 403) {
          clearToken()
          store.authError = 'expired'
          break
        }
        // 网络错误 / 后端 5xx：token 保留，稍后重试一次再说
        store.authError = 'server'
        store.ok = false
        if (attempt < 2) await new Promise((r) => setTimeout(r, 400 * (attempt + 1)))
      }
    }
  }
  store.checked = true
  return store.ok
}

// 全局只跑一次的登录校验，任何组件都能 await 它再发请求
let authPromise = null
export function ensureAuth() {
  if (!authPromise) authPromise = checkAuth()
  return authPromise
}

/** 手动重试（后端刚重启/网络恢复时用） */
export function retryAuth() {
  authPromise = null
  return ensureAuth()
}

export async function doLogin(username, password, remember) {
  const d = await api.login(username, password, remember)
  setToken(d.token, remember)
  store.user = d.user
  store.ok = true
  return d
}

export async function doLogout() {
  try { await api.logout(store.token) } catch { /* 后端不可达也照常退出 */ }
  clearToken()
}

export async function refreshMe() {
  if (!store.token) return
  try {
    store.user = await api.me(store.token)
    store.ok = true
  } catch { store.ok = false }
}

export async function loadSite() {
  try { setSite(await api.getPublicSettings()) } catch { /* 后端未起也不断页 */ }
}
