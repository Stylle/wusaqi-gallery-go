import assert from 'node:assert/strict'
import test from 'node:test'
// Import Vue before installing the minimal browser fixture, so runtime-dom
// does not mistake this fixture for a complete DOM implementation.
import 'vue'

test('default system theme follows OS changes; manual choices persist and override the OS', async () => {
  const values = new Map()
  let onSystemChange
  const media = { matches: true, addEventListener: (_, fn) => { onSystemChange = fn } }
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  globalThis.window = { matchMedia: () => media }
  globalThis.document = { documentElement: { dataset: {}, style: {} } }
  const { theme, setTheme } = await import('../src/theme.js')
  assert.equal(theme.pref, 'system')
  assert.equal(theme.resolved, 'dark')
  media.matches = false; onSystemChange()
  assert.equal(document.documentElement.dataset.theme, 'light')
  setTheme('dark')
  assert.equal(values.get('lg_theme'), 'dark')
  media.matches = true; onSystemChange()
  media.matches = false; onSystemChange()
  assert.equal(theme.resolved, 'dark')
  setTheme('system')
  assert.equal(theme.resolved, 'light')
  assert.equal(document.documentElement.style.colorScheme, 'light')
  setTheme('invalid')
  assert.equal(theme.pref, 'system')
  values.set('lg_theme', 'obsolete-theme')
  const reloaded = await import('../src/theme.js?invalid-stored-preference')
  assert.equal(reloaded.theme.pref, 'system')
  assert.equal(reloaded.theme.resolved, 'light')
})
