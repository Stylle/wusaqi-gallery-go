import { reactive } from 'vue'

// 站点公开配置（后台可自定义部分）+ 分享基址逻辑
export const site = reactive({
  site_title: 'lolis-gallery',
  site_icon: '',
  site_tags: '',
  site_footer: '',
  random_public: '0',
  share_base_url: '',
  upload_default_tags: '',
  upload_max_mb: '',     // 全局单图上限（MB），后端算好下发
  upload_formats: '',    // 支持的扩展名，逗号分隔
  token_login: '0',      // '1' = 允许用管理员 Token 直登（由后端环境变量决定）
})

export function setSite(obj) {
  if (obj) Object.assign(site, obj)
  applySite()
}

export function applySite() {
  // 标题完全由后台「站点标题」配置决定（不再附加任何后缀）
  document.title = site.site_title
  const link = document.querySelector("link[rel='icon']") || document.createElement('link')
  link.rel = 'icon'
  if (site.site_icon.startsWith('http')) {
    link.href = site.site_icon
    link.type = ''
  } else if (site.site_icon) {
    link.href = 'data:image/svg+xml,' + encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#534AB7"/><text x="16" y="22" font-size="16" text-anchor="middle" fill="#fff">${site.site_icon}</text></svg>`)
    link.type = 'image/svg+xml'
  } else {
    // 默认使用站点 logo（public/logo.svg）
    link.href = '/logo.svg'
    link.type = 'image/svg+xml'
  }
  document.head.appendChild(link)
}

/** 分享基址：后台配置优先，未配置则用当前访问 URL。 */
export function shareBase() {
  const b = (site.share_base_url || '').trim().replace(/\/+$/, '')
  return b || location.origin
}

export function absUrl(p) {
  if (!p) return ''
  return /^https?:\/\//i.test(p) ? p : shareBase() + p
}

export const siteTags = () =>
  (site.site_tags || '').split(',').map(t => t.trim()).filter(Boolean)

export const defaultUploadTags = () =>
  (site.upload_default_tags || '').split(',').map(t => t.trim()).filter(Boolean)
