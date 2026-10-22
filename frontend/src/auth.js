import { reactive, computed } from 'vue'
import * as api from './api.js'
import { setSite } from './site.js'

// 登录态
export const store = reactive({
  token: '',
  user: null,
  ok: false,        // 已验证登录
  checked: false,   // 完成首次验证
})

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
}

/** 启动时恢复登录态 */
export async function checkAuth() {
  const t = readToken()
  store.token = t
  if (t) {
    try {
      store.user = await api.me(t)
      store.ok = true
    } catch {
      clearToken()
    }
  }
  store.checked = true
}

export async function doLogin(username, password, remember) {
  const d = await api.login(username, password, remember)
  setToken(d.token, remember)
  store.user = d.user
  store.ok = true
  return d
}

/** 管理员 Token 直登（兼容入口） */
export async function doTokenLogin(token, remember) {
  const d = await api.verifyToken(token)
  setToken(token, remember)
  store.user = d.user || { id: 'admin', username: 'admin', role: 'admin' }
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
