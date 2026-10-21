const json = async (res) => {
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

export const getImages = (page, limit, sort = 'latest') =>
  fetch(`/api/images?page=${page}&limit=${limit}&sort=${sort}`).then(json)

export const getRandom = (variant) =>
  fetch(`/api/random?variant=${variant}`).then(json)

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

export const uploadFiles = (token, files) => {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  return fetch('/api/admin/upload', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  }).then(json)
}

export const reindex = (token) =>
  fetch('/api/admin/reindex', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
    .then(json)

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
