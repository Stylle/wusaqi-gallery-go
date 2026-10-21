<script setup>
import { ref } from 'vue'
import { uploadOne } from '../api.js'
import { store, checkAuth } from '../auth.js'

const token = ref(store.token)
const msg = ref('')
const over = ref(false)
const fileInput = ref(null)
const queue = ref([]) // {name, status: pending|uploading|done|error, progress, item?, error?}

async function doVerify() {
  msg.value = ''
  try {
    localStorage.setItem('lg_token', token.value)
    store.token = token.value
    await checkAuth()
    msg.value = store.ok ? 'Token 有效，已登录 ✓' : 'Token 无效'
  } catch (e) { msg.value = '验证失败：' + e.message }
}

async function handleFiles(files) {
  if (!store.ok || !files?.length) return
  for (const f of files) {
    const entry = { name: f.name, status: 'uploading', progress: 0, item: null, error: '', preview: URL.createObjectURL(f) }
    queue.value.unshift(entry)
    try {
      entry.item = await uploadOne(store.token, f, (p) => { entry.progress = p })
      entry.status = 'done'
    } catch (e) {
      entry.status = 'error'
      entry.error = e.message
    }
  }
}

function pick(e) { handleFiles(e.target.files); e.target.value = '' }

function onDrop(e) { over.value = false; handleFiles(e.dataTransfer.files) }
</script>

<template>
  <!-- 登录面板：游客也看得到，方便进店登录 -->
  <div class="panel" v-if="!store.ok">
    <h3>管理员登录</h3>
    <div class="row">
      <input v-model="token" placeholder="ADMIN_TOKEN" type="password" style="min-width:260px"
        @keyup.enter="doVerify" />
      <button @click="doVerify">登录</button>
      <span class="muted">{{ msg }}</span>
    </div>
  </div>

  <template v-else>
    <div
      class="drop" :class="{ over }"
      @click="fileInput.click()"
      @dragover.prevent="over = true"
      @dragleave="over = false"
      @drop.prevent="onDrop">
      拖拽图片到这里，或点击选择（可多选，逐个上传并显示进度）
      <input ref="fileInput" type="file" accept="image/*" multiple hidden @change="pick" />
    </div>

    <div class="prog-list">
      <div v-for="(e, i) in queue" :key="i" class="prog-item">
        <img :src="e.item?.thumb || e.preview" alt="" />
        <div class="info">
          <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">
            <span>{{ e.name }}</span>
            <span :class="e.status === 'done' ? 'tag-ok' : e.status === 'error' ? 'tag-err' : 'muted'">
              {{ e.status === 'uploading' ? Math.round(e.progress * 100) + '%'
                : e.status === 'done' ? '✓ ' + (e.item.size / 1024).toFixed(0) + 'KB → 压缩 '
                  + (e.item.compressedSize ? (e.item.compressedSize / 1024).toFixed(0) + 'KB' : '跳过')
                : '✗ ' + e.error }}
            </span>
          </div>
          <div class="bar" :class="{ done: e.status === 'done' }">
            <div :style="{ width: (e.status === 'done' ? 100 : e.progress * 100) + '%' }"></div>
          </div>
          <div class="mono muted" v-if="e.item" style="margin-top:3px">{{ e.item.key }}</div>
        </div>
      </div>
    </div>
  </template>
</template>
