<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getImages, copyText, absUrl } from '../api.js'
import { store } from '../auth.js'

const items = ref([])
const page = ref(1)
const total = ref(0)
const hasMore = ref(false)
const loading = ref(false)
const current = ref(null)
const ctx = ref(null)

async function load(p = 1) {
  loading.value = true
  try {
    const d = await getImages(p, 36, 'latest')
    items.value = d.items
    page.value = d.page
    total.value = d.total
    hasMore.value = d.hasMore
  } finally {
    loading.value = false
  }
}

function open(item) { current.value = item }

function menu(e, item = current.value) {
  e.preventDefault()
  if (!item) return
  const urls = [
    { label: '复制原始图 URL', url: absUrl(item.url) },
    { label: `复制压缩图 URL${item.compressed ? '' : '（无压缩版）'}`, url: item.compressed ? absUrl(item.compressed) : null },
    { label: '复制缩略图 URL', url: absUrl(item.thumb) },
  ]
  ctx.value = { x: Math.min(e.clientX, innerWidth - 240), y: e.clientY, urls }
}

async function pick(u) {
  ctx.value = null
  if (!store.ok) { alert('游客不能复制链接，请先登录'); return }
  if (u.url) await copyText(u.url)
}

// 「复制链接」按钮：阻止冒泡，避免 document click 立刻把菜单关掉
function openMenu(e, item) {
  e.stopPropagation()
  menu(e, item)
}

function closeLightbox() { current.value = null; ctx.value = null }

onMounted(() => {
  load()
  document.addEventListener('click', () => { ctx.value = null })
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLightbox() })
})
onUnmounted(() => {
  document.removeEventListener('click', () => { ctx.value = null })
  document.removeEventListener('keydown', closeLightbox)
})
</script>

<template>
  <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
    <h2 class="page-title">Gallery</h2>
    <span class="muted">共 {{ total }} 张 · 点击看大图{{ store.ok ? ' · 右键复制链接' : '' }}</span>
  </div>

  <div v-if="loading" class="grid">
    <div v-for="i in 12" :key="i" class="skel" style="aspect-ratio:1"></div>
  </div>
  <div v-else-if="!items.length" class="lockbox">
    <div class="icon">🖼️</div>
    <p class="muted">空っぽ / 还没有图片</p>
  </div>
  <div v-else class="grid">
    <div v-for="it in items" :key="it.id" class="cell" @click="open(it)">
      <img :src="it.thumb || it.compressed || it.url" :alt="it.key" loading="lazy"
        @contextmenu="menu($event, it)" />
    </div>
  </div>

  <div class="pager">
    <button class="ghost" :disabled="page <= 1 || loading" @click="load(page - 1)">← 上一页</button>
    <span class="muted">{{ page }} / {{ Math.max(1, Math.ceil(total / 36)) }}</span>
    <button class="ghost" :disabled="!hasMore || loading" @click="load(page + 1)">下一页 →</button>
  </div>

  <div v-if="current" class="lightbox" @click.self="closeLightbox">
    <img :src="current.compressed || current.url" :alt="current.key" @contextmenu="menu" />
    <div class="meta mono">
      <span>{{ current.width }}×{{ current.height }}</span>
      <span>{{ (current.size / 1024).toFixed(0) }} KB</span>
      <span v-if="current.compressedSize">{{ (current.compressedSize / 1024).toFixed(0) }} KB(压缩)</span>
    </div>
    <div class="actions">
      <button @click="openMenu($event, current)">复制链接 ▾</button>
      <button class="ghost" @click="closeLightbox">关闭 (Esc)</button>
    </div>
  </div>

  <div v-if="ctx" class="ctxmenu" :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }" @click.stop>
    <button v-for="(u, i) in ctx.urls" :key="i" :disabled="!u.url || !store.ok"
      @click="pick(u)">{{ u.label }}{{ !store.ok ? ' 🔒' : '' }}</button>
    <div v-if="!store.ok" class="muted" style="padding:4px 12px 6px;font-size:12px">登录后可复制链接</div>
  </div>
</template>
