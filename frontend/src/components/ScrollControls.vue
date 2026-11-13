<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { t } from '../i18n.js'

const visible = ref(false)
const atTop = ref(true)
const atBottom = ref(false)
let frame = 0
let observer

function update() {
  frame = 0
  const end = Math.max(0, document.documentElement.scrollHeight - window.innerHeight)
  visible.value = end > 64
  atTop.value = window.scrollY <= 4
  atBottom.value = window.scrollY >= end - 4
}
function schedule() {
  if (!frame) frame = requestAnimationFrame(update)
}
function scroll(toBottom) {
  window.scrollTo({
    top: toBottom ? document.documentElement.scrollHeight : 0,
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
  })
}
onMounted(() => {
  window.addEventListener('scroll', schedule, { passive: true })
  window.addEventListener('resize', schedule)
  observer = new ResizeObserver(schedule)
  observer.observe(document.body)
  schedule()
})
onUnmounted(() => {
  window.removeEventListener('scroll', schedule)
  window.removeEventListener('resize', schedule)
  observer?.disconnect()
  cancelAnimationFrame(frame)
})
</script>

<template>
  <div v-if="visible" class="scroll-controls" role="group" :aria-label="t('页面滚动')">
    <button class="ghost" :disabled="atTop" :title="t('回到顶部')" :aria-label="t('回到顶部')" @click="scroll(false)">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h14M6 14l6-6 6 6M12 8v12" /></svg>
    </button>
    <button class="ghost" :disabled="atBottom" :title="t('前往底部')" :aria-label="t('前往底部')" @click="scroll(true)">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 20h14M6 10l6 6 6-6M12 4v12" /></svg>
    </button>
  </div>
</template>
