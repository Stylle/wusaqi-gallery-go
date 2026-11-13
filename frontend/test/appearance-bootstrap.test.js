import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
const bootstrap = html.match(/<script>([\s\S]*?)<\/script>/)[1]
test('first paint resolves light, dark and system before loading the app', () => {
  assert.match(html, /<html[^>]*data-style="solid"/)
  assert.ok(html.indexOf(bootstrap) < html.indexOf('/src/main.js'))
  for (const [pref, systemDark, expected] of [
    [null, true, 'dark'], ['system', false, 'light'], ['light', true, 'light'],
    ['dark', false, 'dark'], ['obsolete', true, 'dark'],
  ]) {
    const document = { documentElement: { dataset: {} } }
    runInNewContext(bootstrap, { document, localStorage: { getItem: () => pref }, matchMedia: () => ({ matches: systemDark }) })
    assert.equal(document.documentElement.dataset.theme, expected)
  }
})
test('first paint still follows the system when browser storage is unavailable', () => {
  const document = { documentElement: { dataset: {} } }
  runInNewContext(bootstrap, { document, localStorage: { getItem: () => { throw new Error('denied') } }, matchMedia: () => ({ matches: true }) })
  assert.equal(document.documentElement.dataset.theme, 'dark')
})
