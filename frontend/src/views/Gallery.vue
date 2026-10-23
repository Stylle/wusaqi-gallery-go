<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { columnsFor, masonryColumns } from '../layout.js'
import { getImages, getTags, copyText, patchImage, deleteImage, fmtSize } from '../api.js'
import { store, ui, setViewSize } from '../auth.js'
import { absUrl } from '../site.js'
import { t } from '../i18n.js'

const items = ref([])
const tags = ref([])
const cursor = ref('')
const total = ref(0)
const hasMore = ref(false)
const loading = ref(false)
const current = ref(null)
const ctx = ref(null)
const dialog = ref(null)     // {type:'rename'|'delete', item, value}
const dialogMsg = ref('')
const toast = ref('')
const error = ref('')
const sentinel = ref(null)
const grid = ref(null)
const gridWidth = ref(Math.max(1, Math.min(window.innerWidth - 24, 1094)))
const viewportWidth = ref(window.innerWidth)
const columnCount = computed(() => columnsFor(gridWidth.value, viewportWidth.value, ui.viewSize))
const columns = computed(() => masonryColumns(items.value, columnCount.value, gridWidth.value, viewportWidth.value <= 768 ? 8 : 12))
let resizeObserver = null
let observer = null
let controller = null
let generation = 0
let mounted = false

const LIMIT = 36
async function load(reset = false) {
  if (!reset && (loading.value || !hasMore.value || error.value)) return
  if (reset) {
    generation++
    controller?.abort()
    cursor.value = ''
    items.value = []
    hasMore.value = true
    current.value = null
  }
  const requestGeneration = generation
  controller = new AbortController()
  loading.value = true
  error.value = ''
  try {
    const d = await getImages({
      cursor: cursor.value, limit: LIMIT, signal: controller.signal,
      tag: ui.activeTag, mine: ui.onlyMine && store.ok, token: store.token,
    })
    if (requestGeneration !== generation) return
    const seen = new Set(items.value.map(it => it.id))
    items.value.push(...d.items.filter(it => !seen.has(it.id)))
    cursor.value = d.nextCursor || ''
    total.value = d.total
    hasMore.value = d.hasMore
  } catch (e) {
    if (e.name === 'AbortError' || requestGeneration !== generation) return
    if (e.status === 401) { ui.onlyMine = false }
    error.value = e.message
  } finally {
    if (requestGeneration === generation) {
      loading.value = false
      await nextTick()
      // Reobserve after layout so a short first batch can fill the viewport.
      if (mounted && observer && sentinel.value) {
        observer.unobserve(sentinel.value)
        observer.observe(sentinel.value)
      }
    }
  }
}

function retry() { error.value = ''; load() }

function flash(msg) {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 1800)
}

function open(item) {
  // 长按唤出菜单后，手指抬起产生的 click 不该顺带打开灯箱（只吞掉这一次）
  if (swallowClick) { swallowClick = false; clearTimeout(swallowTimer); return }
  current.value = item
}

function closeAll() {
  // 长按触发菜单时，手指抬起产生的 click 会立刻把菜单关掉 —— 短时间内的 click 忽略
  if (Date.now() - ctxOpenedAt < 400) return
  ctx.value = null
}

function menu(e, item = current.value) {
  e.preventDefault()
  if (!item) return
  ctx.value = {
    x: Math.min(e.clientX, window.innerWidth - 250),
    y: Math.min(e.clientY, window.innerHeight - 300),
    item,
  }
}

// ---- 手机端：长按 500ms 唤出同一个菜单（右键在触屏上不可达）----
let pressTimer = null
let swallowClick = false      // 长按后吞掉一次 click
let swallowTimer = null
let ctxOpenedAt = 0

function touchStart(e, item) {
  if (e.touches.length > 1) return
  const t0 = e.touches[0]
  swallowClick = false
  clearTimeout(swallowTimer)
  pressTimer = setTimeout(() => {
    pressTimer = null
    swallowClick = true
    // 有些浏览器长按后不派发 click，兜底自动复位，避免下一次点击被误吞
    swallowTimer = setTimeout(() => { swallowClick = false }, 700)
    ctxOpenedAt = Date.now()
    ctx.value = {
      x: Math.max(8, Math.min(t0.clientX, window.innerWidth - 250)),
      y: Math.max(8, Math.min(t0.clientY, window.innerHeight - 300)),
      item,
    }
    navigator.vibrate?.(15)
  }, 500)
}

function touchEnd() {
  if (pressTimer) { clearTimeout(pressTimer); pressTimer = null }
}

async function copyUrl(which) {
  const it = ctx.value?.item || current.value
  ctx.value = null
  if (!it) return
  if (!store.ok) { flash(t('游客不能复制链接，请先登录')); return }
  const map = { original: it.url, compressed: it.compressed, thumb: it.thumb }
  const p = map[which]
  if (!p) { flash(t('该图没有这个版本')); return }
  try { await copyText(absUrl(p)); flash(t('已复制链接')) }
  catch (e) { flash(e.message) }
}

/** 下载原图 / 压缩图（同源直接触发保存；跨域时浏览器可能改为新窗口打开） */
function downloadUrl(which) {
  const it = ctx.value?.item || current.value
  ctx.value = null
  if (!it) return
  const p = which === 'original' ? it.url : it.compressed
  if (!p) { flash(t('该图没有压缩版')); return }
  const name = which === 'original'
    ? it.filename
    : it.filename.replace(/(\.[^.]+)?$/, '') + (it.compressed || '').match(/(\.[^.]+)$/)?.[1] || it.filename
  const a = document.createElement('a')
  a.href = p
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  flash(t('已开始下载'))
}

function startRename(it) {
  ctx.value = null
  const base = (it.filename || '').replace(/\.[^.]+$/, '')
  dialog.value = { type: 'rename', item: it, value: base }
  dialogMsg.value = ''
}

function startDelete(it) {
  ctx.value = null
  dialog.value = { type: 'delete', item: it }
  dialogMsg.value = ''
}

function startTag(it) {
  ctx.value = null
  dialog.value = { type: 'tag', item: it, value: it.tag || '' }
  dialogMsg.value = ''
}

async function confirmDialog() {
  const d = dialog.value
  if (!d) return
  dialogMsg.value = t('处理中…')
  try {
    if (d.type === 'tag') {
      const updated = await patchImage(store.token, d.item.id, { tag: d.value.trim() })
      const i = items.value.findIndex(x => x.id === updated.id)
      if (i >= 0) items.value[i] = updated
      if (current.value?.id === updated.id) current.value = updated
      dialog.value = null
      await reloadTags()
      // Removing a label from the last image also clears a stale filter.
      if (ui.activeTag && updated.tag !== ui.activeTag) await load(true)
      flash(t('标签已更新'))
    } else if (d.type === 'rename') {
      const name = (d.value || '').trim()
      if (!name) { dialogMsg.value = t('文件名不能为空'); return }
      const updated = await patchImage(store.token, d.item.id, { filename: name })
      const i = items.value.findIndex(x => x.id === updated.id)
      if (i >= 0) items.value[i] = updated
      if (current.value?.id === updated.id) current.value = updated
      dialog.value = null
      flash(t('已重命名'))
    } else {
      await deleteImage(store.token, d.item.id)
      items.value = items.value.filter(x => x.id !== d.item.id)
      total.value = Math.max(0, total.value - 1)
      if (current.value?.id === d.item.id) current.value = null
      dialog.value = null
      await reloadTags()
      flash(t('已删除（原图 + 压缩图 + 缩略图）'))
    }
  } catch (e) {
    dialogMsg.value = t('失败：') + e.message
  }
}

function closeLightbox() { current.value = null; ctx.value = null }

function onKey(e) {
  if (e.key === 'Escape') { if (dialog.value) dialog.value = null; else closeLightbox() }
}

watch(() => [ui.activeTag, ui.onlyMine, store.token], () => { if (mounted) load(true) })
watch(grid, (el, old) => {
  if (old) resizeObserver?.unobserve(old)
  if (el) resizeObserver?.observe(el)
})

async function reloadTags() {
  try {
    tags.value = (await getTags()).tags || []
    if (ui.activeTag && !tags.value.some(tg => tg.name === ui.activeTag)) ui.activeTag = ''
  } catch { /* keep existing tags on a transient error */ }
}

function pickTag(name) {
  ui.activeTag = ui.activeTag === name ? '' : name
}

onMounted(() => {
  mounted = true
  resizeObserver = new ResizeObserver(entries => {
    gridWidth.value = entries[0].contentRect.width
    viewportWidth.value = window.innerWidth
  })
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) load()
  }, { rootMargin: '500px' })
  if (sentinel.value) observer.observe(sentinel.value)
  load(true)
  reloadTags()
  document.addEventListener('click', closeAll)
  document.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  mounted = false
  generation++
  controller?.abort()
  observer?.disconnect()
  resizeObserver?.disconnect()
  clearTimeout(pressTimer)
  clearTimeout(swallowTimer)
  document.removeEventListener('click', closeAll)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <!-- 标签筛选（仅画廊页） -->
  <div class="tagbar">
    <span class="tag-chip all" :class="{ on: !ui.activeTag }" @click="ui.activeTag = ''">
      {{ t('全部') }}
    </span>
    <span v-for="tg in tags" :key="tg.name" class="tag-chip" :class="{ on: ui.activeTag === tg.name }"
      @click="pickTag(tg.name)">
      {{ tg.name }}<em v-if="tg.count">{{ tg.count }}</em>
    </span>
    <span class="spacer"></span>
    <label class="mine-toggle" v-if="store.ok" :class="{ on: ui.onlyMine }">
      <input type="checkbox" v-model="ui.onlyMine" /> {{ t('仅我的') }}
    </label>
    <div class="size-switch">
      <button v-for="sz in [['s', '小'], ['m', '中'], ['l', '大']]" :key="sz[0]"
        :class="{ on: ui.viewSize === sz[0] }" @click="setViewSize(sz[0])">{{ t(sz[1]) }}</button>
    </div>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
    <h2 class="page-title">
      {{ t('画廊') }}
      <span class="filter-hint" v-if="ui.activeTag"># {{ ui.activeTag }}</span>
      <span class="filter-hint" v-if="ui.onlyMine && store.ok">· {{ t('仅我的') }}</span>
    </h2>
    <span class="muted">
      {{ t('共') }} {{ total }} {{ t('张 · 点击看大图') }}{{ store.ok ? t('· 右键/长按可复制、重命名、删除') : '' }}
    </span>
  </div>

  <div v-if="loading && !items.length" class="masonry" :class="'size-' + ui.viewSize">
    <div v-for="i in 9" :key="i" class="skel" :style="{ aspectRatio: i % 3 === 0 ? '3/4' : '1' }"></div>
  </div>
  <div v-else-if="!items.length && !error" class="lockbox">
    <div class="icon">🖼️</div>
    <p class="muted">
      {{ ui.activeTag || ui.onlyMine ? t('该筛选下还没有图片') : t('还没有图片') }}
    </p>
  </div>
  <div v-else ref="grid" class="masonry stable-grid" :class="'size-' + ui.viewSize" :style="{ '--columns': columnCount }">
    <div v-for="(column, columnIndex) in columns" :key="columnIndex" class="masonry-column">
    <div v-for="it in column" :key="it.id" class="cell" role="button" tabindex="0" :aria-label="t('查看图片') + ' ' + it.filename"
      :style="{ aspectRatio: `${it.width} / ${it.height}` }" @click="open(it)"
      @keydown.enter="open(it)" @keydown.space.prevent="open(it)"
      @touchstart="touchStart($event, it)" @touchend="touchEnd"
      @touchmove="touchEnd" @touchcancel="touchEnd">
      <img :src="it.thumb || it.compressed || it.url" :alt="it.filename" loading="lazy"
        @contextmenu="menu($event, it)" />
      <span class="tag-on-img" v-if="it.tag">{{ it.tag }}</span>
      <span class="own" v-if="store.ok && it.mine">{{ t('我的') }}</span>
    </div>
    </div>
  </div>

  <div ref="sentinel" class="load-sentinel" role="status" aria-live="polite">
    <template v-if="error">
      <span class="tag-err">{{ error }}</span>
      <button class="ghost" @click="retry">{{ t('重试加载') }}</button>
    </template>
    <span v-else-if="loading" class="muted">{{ t('正在加载…') }}</span>
    <span v-else-if="items.length && !hasMore" class="muted">{{ t('已经到底了') }} · {{ items.length }} / {{ total }}</span>
  </div>

  <!-- 灯箱 -->
  <div v-if="current" class="lightbox" @click.self="closeLightbox">
    <img :src="current.compressed || current.url" :alt="current.filename" @contextmenu="menu" />
    <div class="meta mono">
      <span>{{ current.filename }}</span>
      <span>{{ current.width }}×{{ current.height }}</span>
      <span>{{ fmtSize(current.size) }}</span>
      <span v-if="current.compressedSize">{{ t('压缩') }} {{ fmtSize(current.compressedSize) }}</span>
      <span v-if="current.tag">#{{ current.tag }}</span>
      <span v-if="current.owner">by {{ current.owner }}</span>
    </div>
    <div class="actions">
      <button @click.stop="menu($event, current)">{{ t('操作 ▾') }}</button>
      <button class="ghost" v-if="current.canEdit" @click="startRename(current)">{{ t('重命名') }}</button>
      <button class="ghost" v-if="current.canEdit" @click="startTag(current)">{{ t('编辑标签') }}</button>
      <button class="ghost danger" v-if="current.canEdit" @click="startDelete(current)">{{ t('删除') }}</button>
      <button class="ghost" @click="closeLightbox">{{ t('关闭 (Esc)') }}</button>
    </div>
  </div>

  <!-- 右键菜单 -->
  <div v-if="ctx" class="ctxmenu" :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }" @click.stop>
    <button :disabled="!store.ok" @click="copyUrl('original')">{{ t('复制原图 URL') }}</button>
    <button :disabled="!store.ok || !ctx.item.compressed" @click="copyUrl('compressed')">
      {{ t('复制压缩图 URL') }}{{ ctx.item.compressed ? '' : t('（无）') }}
    </button>
    <button :disabled="!store.ok" @click="copyUrl('thumb')">{{ t('复制缩略图 URL') }}</button>
    <div class="sep"></div>
    <button @click="downloadUrl('original')">⬇️ {{ t('下载原图') }}</button>
    <button :disabled="!ctx.item.compressed" @click="downloadUrl('compressed')">
      ⬇️ {{ t('下载压缩图') }}{{ ctx.item.compressed ? '' : t('（无）') }}
    </button>
    <div class="sep" v-if="ctx.item.canEdit"></div>
    <button v-if="ctx.item.canEdit" @click="startRename(ctx.item)">{{ t('✏️ 重命名') }}</button>
    <button v-if="ctx.item.canEdit" @click="startTag(ctx.item)">{{ t('编辑标签') }}</button>
    <button v-if="ctx.item.canEdit" class="danger" @click="startDelete(ctx.item)">{{ t('🗑️ 删除图片') }}</button>
    <div v-if="!store.ok" class="muted" style="padding:4px 12px 6px;font-size:12px">{{ t('登录后可复制链接') }}</div>
  </div>

  <!-- 重命名 / 删除确认 -->
  <div v-if="dialog" class="lightbox" @click.self="dialog = null">
    <div class="modal">
      <template v-if="dialog.type === 'rename'">
        <h3>{{ t('重命名') }}</h3>
        <p class="muted" style="margin-top:-4px">
          {{ t('会同时重命名原图、压缩图与缩略图（扩展名保持不变）。') }}
        </p>
        <div class="field">
          <input v-model="dialog.value" @keyup.enter="confirmDialog" :placeholder="t('新文件名（不含扩展名）')" />
        </div>
        <p class="mono muted">{{ dialog.item.filename }}</p>
      </template>
      <template v-else-if="dialog.type === 'tag'">
        <h3>{{ t('编辑标签') }}</h3>
        <div class="field">
          <input v-model="dialog.value" maxlength="40" list="gallery-tags" @keyup.enter="confirmDialog" :placeholder="t('留空可移除标签')" />
          <datalist id="gallery-tags"><option v-for="tg in tags" :key="tg.name" :value="tg.name" /></datalist>
        </div>
      </template>
      <template v-else>
        <h3>{{ t('删除这张图？') }}</h3>
        <p class="muted">{{ t('原图、压缩图、缩略图都会被删除，且不可恢复。') }}</p>
        <p class="mono">{{ dialog.item.filename }}</p>
      </template>
      <p class="tag-err">{{ dialogMsg }}</p>
      <div class="row">
        <button v-if="dialog.type === 'delete'" class="danger-btn" @click="confirmDialog">{{ t('确认删除') }}</button>
        <button v-else @click="confirmDialog">{{ t('保存') }}</button>
        <button class="ghost" @click="dialog = null">{{ t('取消') }}</button>
      </div>
    </div>
  </div>

  <div v-if="toast" class="toast">{{ toast }}</div>
</template>
