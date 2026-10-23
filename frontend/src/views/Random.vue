<script setup>
import { ref, onUnmounted } from 'vue'
import { getRandom, copyText, randomImageUrl } from '../api.js'
import { absUrl, site } from '../site.js'
import { store } from '../auth.js'
import { t } from '../i18n.js'

const variant = ref('compressed')
const item = ref(null)
const loading = ref(false)
const error = ref('')
const copyMessage = ref('')
let requestVersion = 0

async function next() {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  try {
    const result = await getRandom(variant.value, store.token)
    if (version === requestVersion) item.value = result
  } catch (e) {
    if (version !== requestVersion) return
    item.value = null
    if (e.status !== 404) error.value = e.status === 429 ? t('请求太频繁，已被临时封禁') : e.message
  } finally { if (version === requestVersion) loading.value = false }
}
function src(it) {
  return variant.value === 'original' ? it.url : (it.compressed || it.url)
}
async function copy(v) {
  try {
    await copyText(absUrl(v === 'original' ? item.value.url : (item.value.compressed || item.value.url)))
    copyMessage.value = t('已复制链接')
  } catch (e) { copyMessage.value = e.message }
}
next()
onUnmounted(() => { requestVersion++ })
</script>

<template>
  <div class="randbox">
    <div class="actions" style="margin-bottom:16px">
      <label><input type="radio" value="compressed" v-model="variant" @change="next" /> {{ t('压缩图（省流量）') }}</label>
      <label><input type="radio" value="original" v-model="variant" @change="next" /> {{ t('原始图') }}</label>
    </div>

    <div v-if="loading" class="spinner"></div>
    <img v-else-if="item" :src="src(item)" :alt="item.key" @click="next" />
    <p v-else-if="error" class="tag-err" role="alert">{{ error }} <button class="ghost" @click="next">{{ t('重试加载') }}</button></p>
    <p v-else class="muted">{{ t('还没有图片') }}{{ t('，先去 Upload 传几张') }}</p>

    <div class="actions" v-if="item">
      <button @click="next">{{ t('再来一张') }}</button>
      <button class="ghost" @click="copy(variant)">{{ t('复制当前图 URL') }}</button>
      <button class="ghost" @click="copy('original')">{{ t('复制原图 URL') }}</button>
      <a :href="src(item)" target="_blank" rel="noopener noreferrer" class="link-button">{{ t('新窗口打开') }}</a>
    </div>
    <p class="muted mono" v-if="item">
      {{ t('直链：') }}<code>{{ randomImageUrl('compressed') }}</code> / <code>{{ randomImageUrl('original') }}</code>
      <span v-if="site.random_public !== '1'">{{ t('（当前仅登录可用，后台可开放）') }}</span>
    </p>
    <p v-if="copyMessage" class="muted" role="status">{{ copyMessage }}</p>
  </div>
</template>
