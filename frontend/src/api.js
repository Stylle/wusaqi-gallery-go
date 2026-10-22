// 纯 fetch 封装：token 由调用方显式传入，避免与 auth.js 循环依赖
import { t } from './i18n.js'

// 全局 401 通知：由 App.vue 注册，用于提示「登录已失效」
let unauthHandler = null
export const setUnauthHandler = (fn) => { unauthHandler = fn }

const json = async (res, opts = {}) => {
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    // 后端消息是中文原文，统一过一遍 i18n 表（未收录则原样显示）
    const err = new Error(t(d.detail || d.error || res.statusText))
    err.status = res.status
    if (res.status === 401 && !opts.noUnauth && unauthHandler) {
      try { unauthHandler(err) } catch { /* 忽略回调异常 */ }
    }
    throw err
  }
  return res.json()
}

// 没 token 就不要发空的 "Bearer "（后端会当成匿名 → 401 login required）
const auth = (token) => (token ? { Authorization: `Bearer ${token}` } : {})

// ---------- 站点 ----------
export const getPublicSettings = () =>
  fetch('/api/public/settings', { cache: 'no-store' }).then(json)
export const getTags = () => fetch('/api/tags').then(json)

export const getImages = ({ page = 1, limit = 36, sort = 'latest', tag = '', mine = false, token = '' } = {}) => {
  const q = new URLSearchParams({ page, limit, sort })
  if (tag) q.set('tag', tag)
  if (mine) q.set('mine', '1')
  return fetch(`/api/images?${q}`, { headers: auth(token) }).then(json)
}

// ---------- 账号 ----------
export const login = (username, password, remember) =>
  fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, remember: !!remember }),
  }).then(r => json(r, { noUnauth: true }))   // 密码输错不算「会话失效」

export const logout = (token) =>
  fetch('/api/auth/logout', { method: 'POST', headers: auth(token) }).then(json)

export const me = (token) => fetch('/api/auth/me', { headers: auth(token) }).then(json)

export const changePassword = (token, oldPwd, newPwd) =>
  fetch('/api/auth/password', {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ old: oldPwd, new: newPwd }),
  }).then(json)

// ---------- 随机图 ----------
export const getRandom = (variant, token) =>
  fetch(`/api/random?variant=${variant}`, { headers: auth(token) }).then(json)

export const randomImageUrl = (variant) => `/api/random/image?variant=${variant}`

// ---------- 图片 ----------
export const uploadOne = (token, file, tag, onProgress) => {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('files', file)
    if (tag) fd.append('tag', tag)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/upload')
    xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      try {
        const d = JSON.parse(xhr.responseText)
        if (xhr.status < 300 && d.results?.[0]?.ok) resolve(d)
        else reject(new Error(d.results?.[0]?.error || d.detail || `HTTP ${xhr.status}`))
      } catch { reject(new Error(`HTTP ${xhr.status}`)) }
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.send(fd)
  })
}

export const patchImage = (token, id, payload) =>
  fetch(`/api/images/${id}`, {
    method: 'PATCH',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(json)

export const deleteImage = (token, id) =>
  fetch(`/api/images/${id}`, { method: 'DELETE', headers: auth(token) }).then(json)

// ---------- 后台 ----------
export const getSettings = (token) =>
  fetch('/api/admin/settings', { headers: auth(token) }).then(json)

// 压缩方案运行态：自动探测结果 + 各档位参数 + 支持的格式
export const getSystem = (token) =>
  fetch('/api/admin/system', { headers: auth(token) }).then(json)

export const saveSettings = (token, patch) =>
  fetch('/api/admin/settings', {
    method: 'PUT',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).then(json)

export const reindex = (token) =>
  fetch('/api/admin/reindex', { method: 'POST', headers: auth(token) }).then(json)

// 本地图库：扫描 data/uploads 里未入库的原图（dryRun=true 只预览）
export const scanLocal = (token, dryRun = true, limit = 50) =>
  fetch(`/api/admin/local/scan?dry_run=${dryRun}&limit=${limit}`, {
    method: 'GET', headers: auth(token),
  }).then(json)

// 补生成缺失的压缩版/缩略图（limit = 单次张数，低配机器建议 3~5）
export const compressLocal = (token, dryRun = true, limit = 5) =>
  fetch(`/api/admin/local/compress?dry_run=${dryRun}&limit=${limit}`, {
    method: 'POST', headers: auth(token),
  }).then(json)

export const getBans = (token) =>
  fetch('/api/admin/bans', { headers: auth(token) }).then(json)

// 封禁 / 白名单 / 黑名单
export const banIp = (token, ip, minutes, reason) =>
  fetch('/api/admin/bans', {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip, minutes, reason }),
  }).then(json)

export const unbanIp = (token, ip) =>
  fetch(`/api/admin/bans/${encodeURIComponent(ip)}`, {
    method: 'DELETE', headers: auth(token),
  }).then(json)

export const addWhitelist = (token, pattern, note) =>
  fetch('/api/admin/whitelist', {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ pattern, note }),
  }).then(json)

export const removeWhitelist = (token, pattern) =>
  fetch(`/api/admin/whitelist/${encodeURIComponent(pattern)}`, {
    method: 'DELETE', headers: auth(token),
  }).then(json)

export const addBlacklist = (token, pattern, note) =>
  fetch('/api/admin/blacklist', {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ pattern, note }),
  }).then(json)

export const removeBlacklist = (token, pattern) =>
  fetch(`/api/admin/blacklist/${encodeURIComponent(pattern)}`, {
    method: 'DELETE', headers: auth(token),
  }).then(json)

// ---------- 备份 / 恢复 ----------
export const getBackupStats = (token) =>
  fetch('/api/admin/backup/stats', { headers: auth(token) }).then(json)

// 下载备份：必须带 Authorization，所以走 fetch → blob → 本地保存
export async function downloadBackup(token) {
  const res = await fetch('/api/admin/backup', { headers: auth(token) })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    const err = new Error(t(d.detail || d.error || res.statusText))
    err.status = res.status
    throw err
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename="([^"]+)"/)
  const name = m ? m[1] : `lolis-backup-${Date.now()}.zip`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
  return { name, bytes: blob.size }
}

export async function restoreBackup(token, file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/admin/restore', {
    method: 'POST', headers: auth(token), body: fd,
  })
  return json(res, { noUnauth: true })
}

// 访问统计（最近 3 天 PV/UV、Top IP 与归属地、热门接口）
export const getStats = (token) =>
  fetch('/api/admin/stats', { headers: auth(token) }).then(json)

// 通知测试（按后台「通知」配置发一条测试消息）
export const testNotify = (token) =>
  fetch('/api/admin/notify/test', { method: 'POST', headers: auth(token) }).then(json)

// ---------- 用户管理 ----------
export const listUsers = (token) =>
  fetch('/api/users', { headers: auth(token) }).then(json)

export const createUser = (token, payload) =>
  fetch('/api/users', {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(json)

export const updateUser = (token, id, payload) =>
  fetch(`/api/users/${id}`, {
    method: 'PATCH',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(json)

export const deleteUser = (token, id, purge = false) =>
  fetch(`/api/users/${id}?purge=${purge ? 'true' : 'false'}`, {
    method: 'DELETE', headers: auth(token),
  }).then(json)

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
    return true
  }
}

export const fmtSize = (b) => {
  if (b === null || b === undefined) return '-'
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
}
