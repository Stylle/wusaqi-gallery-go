<script setup>
import { theme, setTheme } from '../theme.js'
import { t } from '../i18n.js'

defineProps({ compact: Boolean })
const options = [
  { value: 'light', label: '亮色', path: 'M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42' },
  { value: 'dark', label: '暗色', path: 'M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z' },
  { value: 'system', label: '跟随系统', path: 'M4 3h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm4 18h8m-4-4v4' },
]
</script>

<template>
  <div class="theme-switch" role="group" :aria-label="t('主题')">
    <button v-for="option in options" :key="option.value" type="button"
      :class="{ on: theme.pref === option.value }" :aria-pressed="theme.pref === option.value"
      :aria-label="t(option.label)" :title="t(option.label)" @click="setTheme(option.value)">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle v-if="option.value === 'light'" cx="12" cy="12" r="4" />
        <path :d="option.path" />
      </svg>
      <span v-if="!compact">{{ t(option.label) }}</span>
    </button>
  </div>
</template>
