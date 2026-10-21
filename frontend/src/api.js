const json = async (res) => {
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

const authHeaders = () => ({ Authorization: `Bearer ${localStorage.getItem('lg_token') || ''}` })

export const getImages = (page, limit, sort = 'latest') =>
  fetch(`/api/images?page=${page}&limit=${limit}&sort=${sort}`).then(json)

export const getPublicSettings = () => fetch('/api/public/settings').then(json)

export const getRandom = (variant) =>
  fetch(`/api/random?variant=${variant}`, { headers: authHeaders() }).then(json)

export const randomImageUrl = (variant) => `/api/random/image?variant=${variant}`

export const verifyToken = (token) =>
  fetch('/api/admin/verify', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
    .then(json)

export const getSettings = (token) =>
  fetch('/api/admin/settings', { headers: { Authorization: `Bearer ${token}` } }).then(json)

export const saveSettings = (token, patch) =>
  fetch('/api/admin/settings', {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).then(json)

export const reindex = (token) =>
  fetch('/api/admin/reindex', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
    .then(json)

export const getBans = (token) =>
  fetch('/api/admin/bans', { headers: { Authorization: `Bearer ${token}` } }).then(json)

// 单文件上传 + 逐文件进度回调（0~1）
export function uploadOne(token, file, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('files', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/admin/upload')
    xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      try {
        const d = JSON.parse(xhr.responseText)
        if (xhr.status < 300 && d.results?.[0]?.ok) resolve(d.results[0].item)
        else reject(new Error(d.results?.[0]?.error || d.detail || `HTTP ${xhr.status}`))
      } catch { reject(new Error(`HTTP ${xhr.status}`)) }
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.send(fd)
  })
}

export const absUrl = (p) => (p ? location.origin + p : '')

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
