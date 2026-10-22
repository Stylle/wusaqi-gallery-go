<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { uploadOne, getTags, copyText, fmtSize } from '../api.js'
import { store, doLogout } from '../auth.js'
import { absUrl, defaultUploadTags, site } from '../site.js'
import { t } from '../i18n.js'

const msg = ref('')
const over = ref(false)
const fileInput = ref(null)
const queue = ref([])          // {id,name,status,progress,item,error,preview}
const tags = ref([])
const tag = ref('')
const customTag = ref('')
const busy = computed(() => queue.value.some(e => e.status === 'uploading'))

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
const upLimit = computed(() => store.user?.maxUploadMb || Number(site.upload_max_mb) || 0)
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

async function handleFiles(files) {
  if (!store.ok || !files?.length) return
  if (blocked.value) {
    msg.value = full.value ? t('容量已用满，请联系管理员扩容') : t('今日上传张数已达上限')
    return
  }
  for (const f of Array.from(files)) {
    if (!f.type.startsWith('image/')) {
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
    const entry = {
      id: Math.random(), name: f.name || 'clipboard.png', status: 'uploading',
      progress: 0, item: null, error: '', preview: URL.createObjectURL(f),
    }
    queue.value.unshift(entry)
    try {
      const d = await uploadOne(store.token, f, activeTag.value, (p) => { entry.progress = p })
      entry.item = d.results[0].item
      entry.status = 'done'
      if (d.usage) Object.assign(store.user, d.usage)   // 刷新配额
    } catch (e) {
      entry.status = 'error'
      entry.error = e.message
    }
  }
}

function pick(e) { handleFiles(e.target.files); e.target.value = '' }

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
  await copyText(absUrl(which === 'thumb' ? it.thumb : (which === 'original' ? it.url : it.compressed)))
  msg.value = t('已复制链接')
  setTimeout(() => { msg.value = '' }, 1500)
}

onMounted(() => {
  loadTags()
  window.addEventListener('paste', onPaste)
})
onUnmounted(() => window.removeEventListener('paste', onPaste))
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
        <span v-for="tg in tags" :key="tg" class="tag-chip" :class="{ on: activeTag === tg }"
          @click="customTag = ''; tag = (tag === tg ? '' : tg)">{{ tg }}</span>
        <input v-model="customTag" :placeholder="t('自定义标签…')" style="max-width:150px;padding:5px 10px" />
        <span class="muted" v-if="defaultUploadTags().length" style="font-size:12px">
          {{ t('默认：') }}{{ defaultUploadTags().join(' / ') }}
        </span>
      </div>
    </div>

    <div class="drop" :class="{ over, dis: blocked }"
      @click="!blocked && fileInput.click()"
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
      <input ref="fileInput" type="file" :accept="acceptAttr" multiple hidden @change="pick" />
    </div>

    <p class="hint muted">
      {{ t('支持') }} {{ formats }}{{ t('（推荐 JPG / PNG / WebP） · 单图 ≤ ') }} {{ upLimit || t('不限') }} {{ t('MB') }}
      <template v-if="daily"> · {{ t('今日') }} {{ daily.used }} / {{ daily.cap }} {{ t('张') }}</template>
      <template v-if="store.user?.uploadLimits?.weekly">
        · {{ t('本周') }} {{ store.user.uploadCounts?.week || 0 }} / {{ store.user.uploadLimits.weekly }} {{ t('张') }}
      </template>
    </p>

    <div class="prog-list">
      <div v-for="e in queue" :key="e.id" class="prog-item">
        <img :src="e.item?.thumb || e.preview" alt="" />
        <div class="info">
          <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">
            <span>{{ e.name }}</span>
            <span :class="e.status === 'done' ? 'tag-ok' : e.status === 'error' ? 'tag-err' : 'muted'">
              {{ e.status === 'uploading' ? Math.round(e.progress * 100) + '%'
                : e.status === 'done'
                  ? '✓ ' + fmtSize(e.item.size) + ' → ' + t('压缩') + ' '
                    + (e.item.compressedSize ? fmtSize(e.item.compressedSize) : '–')
                : '✗ ' + e.error }}
            </span>
          </div>
          <div class="bar" :class="{ done: e.status === 'done' }">
            <div :style="{ width: (e.status === 'done' ? 100 : e.progress * 100) + '%' }"></div>
          </div>
          <div class="mono muted" v-if="e.item" style="margin-top:4px;display:flex;gap:10px;flex-wrap:wrap">
            <span>{{ e.item.filename }}</span>
            <a href="javascript:void 0" @click="copyItem(e.item, 'compressed')">{{ t('复制压缩图') }}</a>
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
