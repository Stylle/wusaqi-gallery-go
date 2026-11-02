import { sha256 } from '@noble/hashes/sha2.js'
import { uploadSessionRequest } from './api.js'

const hex = bytes => Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
export const hashBytes = bytes => hex(sha256(bytes))
const checkAbort = signal => { if (signal?.aborted) throw new DOMException('Aborted', 'AbortError') }
export function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    checkAbort(signal)
    const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, ms)
    signal?.addEventListener('abort', abort, { once: true })
  })
}
export async function fileChecksum(file, signal) {
  const h = sha256.create()
  for (let offset = 0; offset < file.size; offset += 1 << 20) {
    checkAbort(signal)
    h.update(new Uint8Array(await file.slice(offset, offset + (1 << 20)).arrayBuffer()))
  }
  checkAbort(signal)
  return hex(h.digest())
}
export function pendingClientId(owner, checksum, name, tag) {
  const key = 'wusaqi-pending:' + hashBytes(new TextEncoder().encode(JSON.stringify([owner, checksum, name, tag])))
  let clientId
  try { clientId = localStorage.getItem(key) } catch { /* private browsing */ }
  if (!clientId) clientId = hex(crypto.getRandomValues(new Uint8Array(16)))
  try { localStorage.setItem(key, clientId) } catch { /* this page still retains the ID */ }
  return { key, clientId }
}
export function forgetPending(key) { try { if (key) localStorage.removeItem(key) } catch { /* private browsing */ } }

// Request-level retries are bounded separately from server-side codec retries.
// Every mutation carries the same session ID and offset when its response is lost.
export async function retryRequest(fn, { signal, wait = delay, onRetry = () => {} } = {}) {
  for (let n = 0; ; n++) {
    checkAbort(signal)
    try { return await fn() }
    catch (e) {
      checkAbort(signal)
      if (e.status && e.status < 500 && e.status !== 429) throw e
      if (n >= 3) { e.networkRetryExhausted = true; throw e }
      onRetry(n + 1)
      await wait(750 * (2 ** n), signal)
    }
  }
}
export async function transferFile(token, file, meta, options = {}) {
  const { signal, onState = () => {}, onProgress = () => {}, wait = delay } = options
  const request = options.request || ((method, path, value, headers) => uploadSessionRequest(token, method, path, value, headers, signal))
  const call = (method, path, value, headers) => retryRequest(() => request(method, path, value, headers), {
    signal, wait, onRetry: n => onState({ status: 'network-retry', retry: n }),
  })
  let session = await call('POST', '/api/uploads', meta)
  onState(session)
  if (['expired', 'cancelled', 'deleted'].includes(session.status)) throw Object.assign(new Error('上传任务已取消、过期或图片已删除，请重新上传'), { terminalUpload: true })
  while (session.status === 'receiving' && session.received < file.size) {
    checkAbort(signal)
    const offset = session.received
    const chunk = file.slice(offset, Math.min(file.size, offset + session.chunkSize))
    const hash = hashBytes(new Uint8Array(await chunk.arrayBuffer()))
    try {
      session = await call('PUT', `/api/uploads/${session.id}/chunk`, chunk,
        { 'Upload-Offset': String(offset), 'X-Chunk-SHA256': hash })
    } catch (e) {
      if (e.status !== 409) throw e
      session = await call('GET', `/api/uploads/${session.id}`)
      if (session.status === 'receiving' && session.received <= offset) throw e
    }
    onProgress(session.received / file.size); onState(session)
  }
  if (session.status === 'receiving') session = await call('POST', `/api/uploads/${session.id}/complete`)
  return monitorUpload(token, session, { ...options, request, call })
}
export async function monitorUpload(token, session, options = {}) {
  const { signal, onState = () => {}, wait = delay } = options
  const request = options.request || ((method, path, value) => uploadSessionRequest(token, method, path, value, {}, signal))
  const call = options.call || ((...args) => retryRequest(() => request(...args), { signal, wait }))
  while (true) {
    checkAbort(signal); onState(session)
    if (session.status === 'done' && session.item) return session.item
    if (['failed', 'deleted', 'expired', 'cancelled'].includes(session.status)) {
      const e = new Error(session.error || '上传任务已取消、过期或图片已删除'); e.session = session; throw e
    }
    if (session.status === 'receiving') throw new Error('请重新选择同一文件继续上传')
    await wait(1000, signal)
    session = await call('GET', `/api/uploads/${session.id}`)
  }
}
