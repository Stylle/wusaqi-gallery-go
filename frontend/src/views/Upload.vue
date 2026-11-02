<script setup>
import { ref, reactive, onMounted, onUnmounted, computed, watch } from 'vue'
import { uploadSessionRequest, getTags, copyText, fmtSize } from '../api.js'
import { store, ensureAuth, refreshMe } from '../auth.js'
import { fileChecksum, pendingClientId, forgetPending, transferFile, monitorUpload } from '../upload-flow.js'
import { absUrl, defaultUploadTags, site } from '../site.js'
import { t } from '../i18n.js'

const msg = ref('')
const over = ref(false)
const fileInput = ref(null)
const queue = ref([])          // {id,name,status,progress,item,error,preview}
const resumeTarget = ref(null)
let alive = true
let draining = false
let currentController = null
const tags = ref([])
const tagOptions = computed(() => [...new Set([
  ...(site.site_tags || '').split(',').map(x => x.trim()).filter(Boolean),
  ...tags.value,
])])
const tag = ref('')
const customTag = ref('')

const quota = computed(() => {
  const u = store.user
  if (!u) return null
  const total = u.quotaMb ? u.quotaMb * 1024 * 1024 : 0
  return {
    total,
    used: u.usedBytes,
    left: total ? Math.max(0, total - u.usedBytes) : -1,
    pct: total ? Math.min(100, u.usedBytes / total * 100) : 0,
  }
})

const full = computed(() => quota.value && quota.value.left === 0)

// 单图上限：管理员不限；普通用户 用户级覆盖 > 全局设置（后端算好下发）
const upLimit = computed(() => store.user?.maxUploadMb ?? Number(site.upload_max_mb) ?? 0)
// 今日张数（未配置上限则不限）
const daily = computed(() => {
  const u = store.user
  const cap = u?.uploadLimits?.daily || 0
  if (!cap) return null
  return { used: u.uploadCounts?.day ?? 0, cap }
})
const dayFull = computed(() => !!daily.value && daily.value.used >= daily.value.cap)
const blocked = computed(() => !!full.value || dayFull.value)

const formats = computed(() => (site.upload_formats || 'jpg,png,webp').split(',').join(' / '))
const acceptAttr = computed(() => (site.upload_formats || 'jpg,png,webp')
  .split(',').map(e => '.' + e.trim()).join(',') + ',image/*')

const activeTag = computed(() => (customTag.value.trim() || tag.value || ''))

async function loadTags() {
  try {
    const d = await getTags()
    tags.value = (d.tags || []).map(x => x.name)
    const def = defaultUploadTags()
    tag.value = def[0] || ''
  } catch { /* 后端未起 */ }
}

function handleFiles(files) {
  if (!store.ok || !files?.length) return
  if (blocked.value) {
    msg.value = full.value ? t('容量已用满，请联系管理员扩容') : t('今日上传张数已达上限')
    return
  }
  for (const f of Array.from(files)) {
    if (!f.type.startsWith('image/') && !/\.(jpe?g|png|webp|avif|gif|bmp)$/i.test(f.name)) {
      queue.value.unshift({ id: Math.random(), name: f.name, status: 'error', error: t('不是图片文件'), progress: 1 })
      continue
    }
    if (upLimit.value && f.size > upLimit.value * 1024 * 1024) {
      queue.value.unshift({
        id: Math.random(), name: f.name, status: 'error',
        error: `${t('超过单图上限')} ${upLimit.value}MB`, progress: 1,
      })
      continue
    }
    const entry = reactive({
      id: Math.random(), name: f.name || 'clipboard.png', status: 'waiting', file: f, tag: activeTag.value,
      progress: 0, item: null, error: '', preview: URL.createObjectURL(f), busy: false,
    })
    queue.value.unshift(entry)
  }
  drain()
}

async function completed(entry, item) {
  entry.item = item; entry.status = 'done'; entry.progress = 1; entry.error = ''
  entry.file = null
  // Keep the task ID after success: selecting a bulk batch again can reuse
  // acknowledged receipts instead of uploading its completed members twice.
  if (entry.preview) URL.revokeObjectURL(entry.preview)
  entry.preview = ''
  if (alive) await refreshMe()
}
function applySession(entry, session) {
  if (session.id) {
    queue.value = queue.value.filter(e => e === entry || e.sessionId !== session.id || e.busy)
    entry.session = session; entry.sessionId = session.id; entry.clientId = session.clientId
    entry.progress = session.received / session.size
  }
  entry.status = session.status
  entry.retry = session.retry || 0
}
async function drain() {
  if (draining || !alive) return
  draining = true
  try {
    let entry
    while (alive && (entry = queue.value.find(e => e.status === 'waiting'))) {
      entry.busy = true; entry.cancelRequested = false; entry.error = ''; currentController = new AbortController()
      const signal = currentController.signal
      try {
        const options = { signal, onState: s => applySession(entry, s), onProgress: p => { entry.progress = p } }
        let item
        if (entry.file) {
          entry.status = 'hashing'
          const checksum = await fileChecksum(entry.file, signal)
          if (entry.session && (entry.session.sha256 !== checksum || entry.session.size !== entry.file.size || entry.name !== (entry.file.name || 'clipboard.png'))) throw new Error(t('文件与原上传任务不一致，请选择同一文件'))
          const mapping = pendingClientId(store.user.id, checksum, entry.name, entry.tag)
          entry.pendingKey = mapping.key
          entry.clientId ||= mapping.clientId
          item = await transferFile(store.token, entry.file, { clientId: entry.clientId, filename: entry.name, size: entry.file.size, tag: entry.tag, sha256: checksum }, options)
        } else {
          let session = await uploadSessionRequest(store.token, 'GET', `/api/uploads/${entry.sessionId}`, undefined, {}, signal)
          if (session.status === 'failed' && entry.retryProcessing) session = await uploadSessionRequest(store.token, 'POST', `/api/uploads/${entry.sessionId}/retry`, undefined, {}, signal)
          item = await monitorUpload(store.token, session, options)
        }
        await completed(entry, item)
      } catch (e) {
        entry.status = entry.cancelRequested ? 'cancelled' : e.name === 'AbortError' ? 'paused' : 'error'
        entry.error = e.name === 'AbortError' ? t('已暂停，可继续；已提交的后台处理不会中止') : e.networkRetryExhausted ? t('网络或服务暂时不可用，自动重试已用完；可点击继续查询或续传') + ': ' + e.message : e.message
        if (e.session) entry.session = e.session
        if (e.terminalUpload) { forgetPending(entry.pendingKey); entry.session = null; entry.sessionId = null; entry.clientId = null }
      } finally { entry.busy = false; entry.retryProcessing = false; currentController = null }
    }
  } finally { draining = false }
}
function retry(entry) {
  if (entry.busy) return
  entry.retryProcessing = entry.session?.status === 'failed'
  if (entry.retryProcessing) entry.file = null
  entry.status = 'waiting'; drain()
}
async function cancelEntry(entry) {
  entry.cancelRequested = true
  if (entry.busy) currentController?.abort()
  try {
    if (entry.sessionId) await uploadSessionRequest(store.token, 'DELETE', `/api/uploads/${entry.sessionId}`)
    forgetPending(entry.pendingKey || (entry.session?.sha256 && pendingClientId(store.user.id, entry.session.sha256, entry.name, entry.tag).key))
    entry.status = 'cancelled'; entry.file = null
    if (entry.preview) URL.revokeObjectURL(entry.preview)
    entry.preview = ''
  } catch (e) {
    // Completion may win the race with cancellation; reconcile its receipt.
    const s = entry.sessionId && await uploadSessionRequest(store.token, 'GET', `/api/uploads/${entry.sessionId}`).catch(() => null)
    if (s?.status === 'done') await completed(entry, s.item)
    else { entry.status = 'error'; entry.error = e.message }
  }
}
function chooseResume(entry) { resumeTarget.value = entry; fileInput.value.click() }
function pick(e) {
  if (resumeTarget.value && e.target.files?.[0]) {
    const entry = resumeTarget.value
    entry.file = e.target.files[0]; entry.status = 'waiting'; drain()
  } else if (!resumeTarget.value) handleFiles(e.target.files)
  resumeTarget.value = null; e.target.value = ''
}
async function restoreTasks() {
  try {
    const d = await uploadSessionRequest(store.token, 'GET', '/api/uploads')
    if (!alive) return
    for (const s of d.items) {
      if (s.status === 'deleted') continue
      if (queue.value.some(e => e.clientId === s.clientId)) continue
      const entry = reactive({ id: s.id, sessionId: s.id, clientId: s.clientId, name: s.name, tag: s.tag,
        session: s, status: ['queued', 'processing'].includes(s.status) ? 'waiting' : s.status,
        progress: s.received / s.size, item: s.item, file: null, error: s.error, preview: '', busy: false })
      queue.value.push(entry)
    }
    drain()
  } catch (e) { if (alive) msg.value = t('上传任务恢复失败，可刷新重试') + ': ' + e.message }
}
const statusLabel = entry => {
  const labels = { waiting: '等待上传', hashing: '校验文件中…', receiving: '上传中', queued: '等待图片处理', processing: '图片处理中…', paused: '已暂停', failed: '处理失败', cancelled: '已取消' }
  if (entry.status === 'network-retry') return `${t('网络重试')} ${entry.retry}/3`
  return t(labels[entry.status] || entry.status)
}

function onDrop(e) { over.value = false; handleFiles(e.dataTransfer.files) }

function onPaste(e) {
  const files = []
  for (const item of e.clipboardData?.items || []) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) {
        // 粘贴的图没有文件名，给个可读的
        const ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
        files.push(new File([f], `paste-${Date.now()}.${ext}`, { type: f.type }))
      }
    }
  }
  if (files.length) {
    e.preventDefault()
    handleFiles(files)
  }
}

async function copyItem(it, which) {
  const path = which === 'thumb' ? it.thumb : (which === 'original' ? it.url : it.compressed)
  if (!path) { msg.value = t('该图没有这个版本'); return }
  try { await copyText(absUrl(path)); msg.value = t('已复制链接') }
  catch (e) { msg.value = e.message }
  setTimeout(() => { msg.value = '' }, 1500)
}

onMounted(async () => {
  await ensureAuth()
  if (!alive || !store.ok) return
  loadTags()
  restoreTasks()
  window.addEventListener('paste', onPaste)
})
onUnmounted(() => {
  alive = false; currentController?.abort()
  window.removeEventListener('paste', onPaste)
  queue.value.forEach(entry => { if (entry.preview) URL.revokeObjectURL(entry.preview) })
})
watch(() => store.token, (token, previous) => {
  if (!previous) return
  currentController?.abort()
  queue.value.forEach(e => { if (e.preview) URL.revokeObjectURL(e.preview); e.file = null })
  queue.value = []
})
</script>

<template>
  <!-- 未登录兜底（正常由 LockGate 拦住） -->
  <div class="panel" v-if="!store.ok">
    <h3>{{ t('需要登录') }}</h3>
    <p class="muted">{{ t('请先') }}<a href="#/login">{{ t('登录') }}</a>{{ t('后再上传。') }}</p>
  </div>

  <template v-else>
    <div class="upload-head">
      <h2 class="page-title">{{ t('上传') }}</h2>
      <div class="quota" v-if="quota">
        <template v-if="quota.total">
          <span>{{ t('已用') }} {{ fmtSize(quota.used) }} / {{ store.user.quotaMb }} MB</span>
          <div class="bar quota-bar"><div :style="{ width: quota.pct + '%' }" :class="{ full: quota.pct >= 90 }"></div></div>
          <span class="muted">{{ t('剩余') }} {{ fmtSize(quota.left) }}</span>
        </template>
        <span v-else class="muted">{{ t('不限容量') }} · {{ t('已用') }} {{ fmtSize(quota.used) }}</span>
        <span class="muted" v-if="daily">{{ t('今日') }} {{ daily.used }} / {{ daily.cap }} {{ t('张') }}</span>
      </div>
    </div>

    <div class="panel tag-picker">
      <div class="row" style="margin:0;gap:8px;align-items:center">
        <span class="muted">{{ t('标签') }}</span>
        <span class="tag-chip" :class="{ on: !activeTag }" @click="tag = ''; customTag = ''">{{ t('无') }}</span>
        <span v-for="tg in tagOptions" :key="tg" class="tag-chip" :class="{ on: activeTag === tg }"
          @click="customTag = ''; tag = (tag === tg ? '' : tg)">{{ tg }}</span>
        <input v-model="customTag" :placeholder="t('自定义标签…')" style="max-width:150px;padding:5px 10px" />
        <span class="muted" v-if="defaultUploadTags().length" style="font-size:12px">
          {{ t('默认：') }}{{ defaultUploadTags().join(' / ') }}
        </span>
      </div>
    </div>

    <div class="drop" :class="{ over, dis: blocked }" role="button" :tabindex="blocked ? -1 : 0" :aria-disabled="blocked"
      @click="!blocked && (resumeTarget = null, fileInput.click())"
      @keydown.enter.prevent="!blocked && (resumeTarget = null, fileInput.click())" @keydown.space.prevent="!blocked && (resumeTarget = null, fileInput.click())"
      @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
      <div v-if="!blocked">
        {{ t('拖拽图片到这里 / 点击选择 /') }} <b>Ctrl+V {{ t('直接粘贴上传') }}</b>
        <div class="muted" style="font-size:12.5px;margin-top:6px">
          {{ t('可多选，逐个上传并显示进度；当前标签「') }}{{ activeTag || t('无') }}{{ t('」') }}
        </div>
      </div>
      <div v-else-if="full">
        {{ t('容量已用满（') }}{{ fmtSize(quota.used) }} / {{ store.user.quotaMb }} MB{{ t('），请联系管理员扩容') }}
      </div>
      <div v-else>
        {{ t('今日上传已达上限（') }}{{ daily.used }} / {{ daily.cap }} {{ t('张），明天再来或联系管理员调整') }}
      </div>
      <input ref="fileInput" type="file" :accept="acceptAttr" :multiple="!resumeTarget" hidden @change="pick" @cancel="resumeTarget = null" />
    </div>

    <p class="hint muted">
      {{ t('支持') }} {{ formats }}{{ t('（推荐 JPG / PNG / WebP） · 单图 ≤ ') }} {{ upLimit || t('不限') }} {{ t('MB') }}
      <template v-if="daily"> · {{ t('今日') }} {{ daily.used }} / {{ daily.cap }} {{ t('张') }}</template>
      <template v-if="store.user?.uploadLimits?.weekly">
        · {{ t('本周') }} {{ store.user.uploadCounts?.week || 0 }} / {{ store.user.uploadLimits.weekly }} {{ t('张') }}
      </template>
    </p>

    <div class="prog-list">
      <p class="hint muted">{{ t('分块上传支持断点续传；网络失败最多自动重试三次。传输完成后继续等待图片处理，只有全部成功才进入画廊。关闭页面后可恢复任务；未传完的文件需要重新选择同一文件，暂存保留 24 小时。') }}</p>
      <div v-for="e in queue" :key="e.id" class="prog-item">
        <img v-if="e.item?.thumb || e.item?.url || e.preview" :src="e.item?.thumb || e.item?.url || e.preview" alt="" />
        <div class="info">
          <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">
            <span>{{ e.name }}</span>
            <span :class="e.status === 'done' ? 'tag-ok' : e.status === 'error' ? 'tag-err' : 'muted'">
              {{ e.status === 'done'
                  ? '✓ ' + fmtSize(e.item.size) + ' → ' + t('压缩') + ' '
                    + (e.item.compressedSize ? fmtSize(e.item.compressedSize) : '–')
                : e.status === 'error' || e.status === 'failed' ? '✗ ' + e.error
                : statusLabel(e) + (e.status === 'receiving' ? ' ' + Math.round(e.progress * 100) + '%' : '') }}
            </span>
          </div>
          <div v-if="e.status !== 'done' && e.status !== 'cancelled'" class="row" style="margin-top:8px;gap:8px;flex-wrap:wrap">
            <button v-if="e.busy" class="ghost sm" @click="currentController?.abort()">{{ t('暂停传输或状态查询') }}</button>
            <template v-else>
              <button v-if="!e.file && e.session?.status === 'receiving'" class="ghost sm" @click="chooseResume(e)">{{ t('重新选择同一文件续传') }}</button>
              <button v-else-if="e.file || e.sessionId" class="ghost sm" @click="retry(e)">{{ t(e.session?.status === 'failed' ? '重试图片处理' : '继续或查询结果') }}</button>
              <button class="ghost danger sm" @click="cancelEntry(e)">{{ t('取消任务') }}</button>
            </template>
            <span v-if="e.session?.attempts" class="muted">{{ t('处理尝试') }} {{ e.session.attempts }}/4</span>
          </div>
          <p v-if="e.status === 'paused'" class="hint muted">{{ e.error }}</p>
          <div class="bar" :class="{ done: e.status === 'done' }">
            <div :style="{ width: (e.status === 'done' ? 100 : e.progress * 100) + '%' }"></div>
          </div>
          <div class="mono muted" v-if="e.item" style="margin-top:4px;display:flex;gap:10px;flex-wrap:wrap">
            <span>{{ e.item.filename }}</span>
            <a v-if="e.item.compressed" href="javascript:void 0" @click="copyItem(e.item, 'compressed')">{{ t('复制压缩图') }}</a>
            <a href="javascript:void 0" @click="copyItem(e.item, 'original')">{{ t('复制原图') }}</a>
            <a href="javascript:void 0" @click="copyItem(e.item, 'thumb')">{{ t('复制缩略图') }}</a>
          </div>
        </div>
      </div>
    </div>

    <p class="muted" v-if="msg">{{ msg }}</p>
    <p class="hint muted" v-if="site.share_base_url">
      {{ t('分享链接基址：') }}<code>{{ site.share_base_url }}</code>
    </p>
  </template>
</template>
