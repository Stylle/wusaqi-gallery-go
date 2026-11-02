import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
const storageValues = new Map()
globalThis.localStorage = { getItem: k => storageValues.get(k) || null, setItem: (k,v) => storageValues.set(k,v), removeItem: k => storageValues.delete(k) }
globalThis.document = { documentElement: {}, createElement: () => ({}) }
const { fileChecksum, retryRequest, transferFile, pendingClientId, forgetPending } = await import('../src/upload-flow.js')

const wait = async () => {}
test('reselecting a bulk batch retains same file task ID until explicitly cancelled', () => {
  const first = pendingClientId('owner', 'checksum', 'image.png', 'tag')
  assert.equal(pendingClientId('owner', 'checksum', 'image.png', 'tag').clientId, first.clientId)
  assert.notEqual(pendingClientId('other', 'checksum', 'image.png', 'tag').clientId, first.clientId)
  forgetPending(first.key)
  assert.notEqual(pendingClientId('owner', 'checksum', 'image.png', 'tag').clientId, first.clientId)
})
test('streamed checksum matches Node SHA256 across chunk boundaries', async () => {
  const bytes = new Uint8Array((1 << 20) + 17).fill(123)
  assert.equal(await fileChecksum(new Blob([bytes])), createHash('sha256').update(bytes).digest('hex'))
})
test('network retry is bounded to three retries; business errors are not retried', async () => {
  let n = 0
  await assert.rejects(retryRequest(async () => { n++; throw new TypeError('offline') }, { wait }))
  assert.equal(n, 4)
  n = 0
  await assert.rejects(retryRequest(async () => { n++; throw Object.assign(new Error('forbidden'), { status: 403 }) }, { wait }))
  assert.equal(n, 1)
})
test('lost create, chunk and commit responses retry the same task without duplicates', async () => {
  const file = new Blob(['abcdefgh'])
  const meta = { clientId: 'same-client-id', sha256: await fileChecksum(file) }
  const state = { id: 'session', status: 'receiving', received: 0, chunkSize: 4 }
  const lost = new Set()
  let createCount = 0, chunksWritten = 0, commits = 0
  const request = async (method, path, body, headers) => {
    if (method === 'POST' && path === '/api/uploads') {
      assert.equal(body.clientId, meta.clientId)
      createCount++
      if (!lost.has('init')) { lost.add('init'); throw new TypeError('lost response') }
    } else if (method === 'PUT') {
      const offset = Number(headers['Upload-Offset'])
      if (offset === state.received) { state.received += body.size; chunksWritten++ }
      if (!lost.has('chunk')) { lost.add('chunk'); throw new TypeError('lost chunk response') }
    } else if (path.endsWith('/complete')) {
      if (state.status !== 'done') { commits++; state.status = 'done'; state.item = { id: 'image' } }
      if (!lost.has('commit')) { lost.add('commit'); throw new TypeError('lost commit response') }
    }
    return { ...state }
  }
  assert.deepEqual(await transferFile('', file, meta, { request, wait }), { id: 'image' })
  assert.equal(createCount, 2)
  assert.equal(chunksWritten, 2)
  assert.equal(commits, 1)
})
test('resume starts at acknowledged offset and waits for codec completion', async () => {
  const file = new Blob(['abcdefgh'])
  const offsets = [], states = []
  let poll = 0
  const request = async (method, path, body, headers) => {
    if (path === '/api/uploads') return { id: 'resume', received: 4, chunkSize: 4, status: 'receiving' }
    if (method === 'PUT') { offsets.push(Number(headers['Upload-Offset'])); return { id: 'resume', received: 8, status: 'receiving' } }
    if (path.endsWith('/complete')) return { id: 'resume', status: 'queued' }
    return ++poll === 1 ? { id: 'resume', status: 'processing' } : { id: 'resume', status: 'done', item: { id: 'complete' } }
  }
  const item = await transferFile('', file, {}, { request, wait, onState: s => states.push(s.status) })
  assert.equal(item.id, 'complete')
  assert.deepEqual(offsets, [4])
  assert.ok(states.includes('processing'))
})
test('an already completed receipt never sends chunks or starts another codec task', async () => {
  let calls = 0
  const item = await transferFile('', new Blob(['data']), {}, { wait, request: async (method, path) => {
    calls++; assert.equal(path, '/api/uploads'); return { id: 'old', status: 'done', item: { id: 'original' } }
  } })
  assert.equal(calls, 1); assert.equal(item.id, 'original')
})
test('pausing prevents any further upload request', async () => {
  const controller = new AbortController(); controller.abort()
  let requests = 0
  await assert.rejects(transferFile('', new Blob(['data']), {}, { signal: controller.signal, wait, request: async () => { requests++ } }), { name: 'AbortError' })
  assert.equal(requests, 0)
})
