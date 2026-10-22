<script setup>
import { ref } from 'vue'
import { getRandom, copyText, randomImageUrl } from '../api.js'
import { absUrl, site } from '../site.js'
import { store } from '../auth.js'
import { t } from '../i18n.js'

const variant = ref('compressed')
const item = ref(null)
const loading = ref(false)

async function next() {
  loading.value = true
  try { item.value = await getRandom(variant.value, store.token) }
  catch (e) { item.value = null; if (e.status === 429) alert(t('请求太频繁，已被临时封禁')) }
  finally { loading.value = false }
}
function src(it) {
  return variant.value === 'original' ? it.url : (it.compressed || it.url)
}
async function copy(v) {
  await copyText(absUrl(v === 'original' ? item.value.url : (item.value.compressed || item.value.url)))
}
next()
</script>

<template>
  <div class="randbox">
    <div class="actions" style="margin-bottom:16px">
      <label><input type="radio" value="compressed" v-model="variant" @change="next" /> {{ t('压缩图（省流量）') }}</label>
      <label><input type="radio" value="original" v-model="variant" @change="next" /> {{ t('原始图') }}</label>
    </div>

    <div v-if="loading" class="spinner"></div>
    <img v-else-if="item" :src="src(item)" :alt="item.key" @click="next" />
    <p v-else class="muted">{{ t('还没有图片') }}{{ t('，先去 Upload 传几张') }}</p>

    <div class="actions" v-if="item">
      <button @click="next">{{ t('再来一张') }}</button>
      <button class="ghost" @click="copy(variant)">{{ t('复制当前图 URL') }}</button>
      <button class="ghost" @click="copy('original')">{{ t('复制原图 URL') }}</button>
      <a :href="src(item)" target="_blank"><button class="ghost">{{ t('原窗口打开') }}</button></a>
    </div>
    <p class="muted mono" v-if="item">
      {{ t('直链：') }}<code>{{ randomImageUrl('compressed') }}</code> / <code>{{ randomImageUrl('original') }}</code>
      <span v-if="site.random_public !== '1'">{{ t('（当前仅登录可用，后台可开放）') }}</span>
    </p>
  </div>
</template>
