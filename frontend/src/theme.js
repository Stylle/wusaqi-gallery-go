import { reactive, watch } from 'vue'

// 主题三态：light / dark / system（跟随系统）
export const theme = reactive({
  pref: localStorage.getItem('lg_theme') || 'system',
  resolved: 'light',
})

const media = window.matchMedia('(prefers-color-scheme: dark)')

function apply() {
  theme.resolved = theme.pref === 'system' ? (media.matches ? 'dark' : 'light') : theme.pref
  document.documentElement.dataset.theme = theme.resolved
  document.documentElement.style.colorScheme = theme.resolved
}

export function setTheme(pref) {
  theme.pref = pref
  localStorage.setItem('lg_theme', pref)
  apply()
}

media.addEventListener('change', () => { if (theme.pref === 'system') apply() })
apply()

watch(() => theme.pref, apply)
