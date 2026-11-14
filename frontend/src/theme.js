import { reactive, watch } from 'vue'
import { readStorage, writeStorage } from './storage.js'

// 主题三态：light / dark / system（跟随系统）
export const theme = reactive({
  pref: ['light', 'dark', 'system'].includes(readStorage('localStorage', 'lg_theme')) ? readStorage('localStorage', 'lg_theme') : 'system',
  resolved: 'light',
})

const media = window.matchMedia('(prefers-color-scheme: dark)')

function apply() {
  theme.resolved = theme.pref === 'system' ? (media.matches ? 'dark' : 'light') : theme.pref
  document.documentElement.dataset.theme = theme.resolved
  document.documentElement.style.colorScheme = theme.resolved
}

export function setTheme(pref) {
  if (!['light', 'dark', 'system'].includes(pref)) return
  theme.pref = pref
  writeStorage('localStorage', 'lg_theme', pref)
  apply()
}

media.addEventListener('change', () => { if (theme.pref === 'system') apply() })
apply()

watch(() => theme.pref, apply)
