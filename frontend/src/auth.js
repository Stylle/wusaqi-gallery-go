import { reactive } from 'vue'
import { verifyToken, getPublicSettings } from './api.js'

// 登录态 + 站点公开配置（后台可自定义部分）
export const store = reactive({
  token: localStorage.getItem('lg_token') || '',
  ok: false,        // 已验证登录
  checked: false,   // 完成首次验证
  site: { site_title: 'lolis-gallery', site_icon: '', site_tags: '', site_footer: '', random_public: '0' },
})

export function setToken(t) {
  store.token = t
  localStorage.setItem('lg_token', t)
}

export async function checkAuth() {
  if (store.token) {
    try { await verifyToken(store.token); store.ok = true }
    catch { store.ok = false }
  } else {
    store.ok = false
  }
  store.checked = true
}

export async function loadSite() {
  try { Object.assign(store.site, await getPublicSettings()) } catch { /* 后端未起也不断页 */ }
  applySite()
}

export function applySite() {
  const s = store.site
  document.title = `${s.site_title} — ギャラリー`
  // 动态 favicon：后台可配 URL 或 emoji
  const link = document.querySelector("link[rel='icon']") || document.createElement('link')
  link.rel = 'icon'
  if (s.site_icon.startsWith('http')) {
    link.href = s.site_icon
    link.type = ''
  } else if (s.site_icon) {
    link.href = 'data:image/svg+xml,' + encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#534AB7"/><text x="16" y="22" font-size="16" text-anchor="middle" fill="#fff">${s.site_icon}</text></svg>`)
    link.type = 'image/svg+xml'
  } else {
    link.href = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23534AB7'/%3E%3Cpath d='M8 22V10h3.2v9.2H24V22H8z' fill='%23fff'/%3E%3C/svg%3E"
  }
  document.head.appendChild(link)
}

export const siteTags = () =>
  (store.site.site_tags || '').split(',').map(t => t.trim()).filter(Boolean)
