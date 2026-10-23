import test from 'node:test'
import assert from 'node:assert/strict'
import { columnsFor, masonryColumns } from '../src/layout.js'

const storage = () => {
  const values = new Map()
  return { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) }
}
globalThis.localStorage = storage()
globalThis.sessionStorage = storage()
globalThis.document = { documentElement: { lang: 'zh-CN', dataset: {} }, createElement: () => ({}) }
const api = await import('../src/api.js')
const auth = await import('../src/auth.js')

test('appending gallery batches keeps every existing image in the same column', () => {
  const items = Array.from({ length: 83 }, (_, id) => ({ id, width: 400, height: [300, 600, 400][id % 3] }))
  const first = masonryColumns(items.slice(0, 36), 3, 900, 12)
  const all = masonryColumns(items, 3, 900, 12)
  first.forEach((column, index) => assert.deepEqual(all[index].slice(0, column.length), column))
  assert.equal(all.flat().length, 83)
  assert.equal(new Set(all.flat().map(item => item.id)).size, 83)
  assert.equal(columnsFor(296, 320, 'l'), 1)
  assert.ok(columnsFor(1000, 1200, 's') > columnsFor(1000, 1200, 'l'))
})

test('wrong old password is an action error and does not expire the session', async () => {
  let expired = 0
  api.setUnauthHandler(() => expired++)
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: '原密码错误' }), { status: 401 })
  await assert.rejects(api.changePassword('valid-session', 'wrong', 'new-pass'), { status: 401 })
  assert.equal(expired, 0)
})

test('an old failed session request cannot clear a newer login', async () => {
  let resolve
  globalThis.fetch = () => new Promise(done => { resolve = done })
  api.setUnauthHandler(() => auth.clearToken())
  auth.setToken('old-session', true)
  const pending = auth.checkAuth()
  auth.setToken('new-session', true)
  auth.store.ok = true
  auth.store.user = { id: 'new-user' }
  resolve(new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }))
  await pending
  assert.equal(auth.store.token, 'new-session')
  assert.equal(auth.store.user.id, 'new-user')
  assert.equal(auth.store.ok, true)
})

test('a late successful session request cannot log a user back in after logout', async () => {
  let resolve
  globalThis.fetch = () => new Promise(done => { resolve = done })
  auth.setToken('old-session', true)
  const pending = auth.checkAuth()
  auth.clearToken()
  resolve(new Response(JSON.stringify({ id: 'old-user', role: 'admin' })))
  await pending
  assert.equal(auth.store.token, '')
  assert.equal(auth.store.user, null)
  assert.equal(auth.store.ok, false)
})
