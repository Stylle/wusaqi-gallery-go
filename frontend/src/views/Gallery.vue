<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getImages, copyText, absUrl } from '../api.js'

const items = ref([])
const page = ref(1)
const total = ref(0)
const hasMore = ref(false)
const loading = ref(false)

const current = ref(null)
const ctx = ref(null) // {x, y, urls: [...]}

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
  ctx.value = { x: Math.min(e.clientX, innerWidth - 230), y: e.clientY, urls }
}

async function pick(u) {
  if (u.url) await copyText(u.url)
  ctx.value = null
}

function closeAll() { ctx.value = null; }
function closeLightbox() { current.value = null; ctx.value = null }

onMounted(() => {
  load()
  document.addEventListener('click', closeAll)
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLightbox() })
})
</script>

<template>
  <p class="muted">共 {{ total }} 张 · 点击看大图 · 大图上右键可复制原图 / 压缩图链接</p>
  <div class="grid">
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
      <button @click="menu($event, current)">复制链接 ▾</button>
      <button class="ghost" @click="closeLightbox">关闭 (Esc)</button>
    </div>
  </div>

  <div v-if="ctx" class="ctxmenu" :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }">
    <button v-for="(u, i) in ctx.urls" :key="i" :disabled="!u.url" @click="pick(u)">{{ u.label }}</button>
  </div>
</template>
