<script setup>
import { ref } from 'vue'
import { verifyToken, uploadFiles, getSettings, saveSettings, reindex } from '../api.js'

const token = ref(localStorage.getItem('lg_token') || '')
const verified = ref(false)
const msg = ref('')
const over = ref(false)
const results = ref([])
const fileInput = ref(null)

const settings = ref(null)
const sMsg = ref('')

async function doVerify() {
  msg.value = ''
  try {
    await verifyToken(token.value)
    localStorage.setItem('lg_token', token.value)
    verified.value = true
    msg.value = 'Token 有效'
    settings.value = await getSettings(token.value)
  } catch (e) { msg.value = 'Token 无效：' + e.message }
}

async function doUpload(files) {
  if (!files?.length || !verified.value) return
  msg.value = '上传中…'
  try {
    const d = await uploadFiles(token.value, [...files])
    results.value = [...d.results, ...results.value]
    msg.value = `完成：${d.results.filter(r => r.ok).length} 成功 / ${d.results.filter(r => !r.ok).length} 失败`
  } catch (e) { msg.value = '上传失败：' + e.message }
}

async function doSave() {
  sMsg.value = '保存中…'
  try {
    settings.value = await saveSettings(token.value, {
      format: settings.value.comp_format,
      quality: Number(settings.value.comp_quality),
      max_width: Number(settings.value.comp_max_width),
    })
    sMsg.value = '已保存（仅对新上传生效，历史压缩版不变）'
  } catch (e) { sMsg.value = '保存失败：' + e.message }
}

async function doReindex() {
  sMsg.value = '扫描中…'
  try {
    const d = await reindex(token.value)
    sMsg.value = `扫描 ${d.scanned} 个文件，补录 ${d.added} 条`
  } catch (e) { sMsg.value = '失败：' + e.message }
}
</script>

<template>
  <div class="panel" v-if="!verified">
    <h3>管理员登录</h3>
    <div class="row">
      <input v-model="token" placeholder="ADMIN_TOKEN" type="password" style="min-width:260px"
        @keyup.enter="doVerify" />
      <button @click="doVerify">验证</button>
      <span class="muted">{{ msg }}</span>
    </div>
  </div>

  <template v-else>
    <div
      class="drop" :class="{ over }"
      @click="fileInput.click()"
      @dragover.prevent="over = true"
      @dragleave="over = false"
      @drop.prevent="over = false; doUpload($event.dataTransfer.files)">
      拖拽图片到这里，或点击选择（可多选）
      <input ref="fileInput" type="file" accept="image/*" multiple hidden
        @change="doUpload($event.target.files); $event.target.value = ''" />
    </div>
    <p class="muted">{{ msg }}</p>

    <div class="result-list">
      <div v-for="(r, i) in results" :key="i" class="result-item">
        <img v-if="r.ok" :src="r.item.thumb || r.item.url" alt="" />
        <div class="info">
          <div>{{ r.name }} <span :class="r.ok ? 'tag-ok' : 'tag-err'">{{ r.ok ? '✓' : '✗ ' + r.error }}</span></div>
          <div class="mono muted" v-if="r.ok">{{ r.item.key }} · {{ (r.item.size / 1024).toFixed(0) }}KB
            → 压缩 {{ r.item.compressedSize ? (r.item.compressedSize / 1024).toFixed(0) + 'KB' : '跳过' }}</div>
        </div>
      </div>
    </div>

    <div class="panel" v-if="settings">
      <h3>压缩设置（对新上传生效）</h3>
      <div class="row">
        <label>格式
          <select v-model="settings.comp_format">
            <option value="webp">WebP（推荐，最小）</option>
            <option value="jpeg">JPEG</option>
            <option value="png">PNG（无损）</option>
          </select>
        </label>
        <label>质量 <input type="number" min="1" max="100" v-model="settings.comp_quality" style="width:80px" /></label>
        <label>最大宽度 <input type="number" min="0" step="100" v-model="settings.comp_max_width" style="width:100px" /> px（0=不缩放）</label>
        <button @click="doSave">保存设置</button>
      </div>
      <div class="row">
        <button class="ghost" @click="doReindex">重建索引（reindex）</button>
        <span class="muted">{{ sMsg }}</span>
      </div>
      <p class="muted">历史图片的压缩版保持不变；改完设置后新上传按新参数生成。</p>
    </div>
  </template>
</template>
