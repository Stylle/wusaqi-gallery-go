<script setup>
import { ref } from 'vue'
import { getRandom, copyText, absUrl, randomImageUrl } from '../api.js'
import { store } from '../auth.js'

const variant = ref('compressed')
const item = ref(null)
const loading = ref(false)

async function next() {
  loading.value = true
  try { item.value = await getRandom(variant.value) }
  catch (e) { item.value = null; if (String(e.message).includes('429')) alert('请求太频繁，已被临时封禁') }
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
      <label><input type="radio" value="compressed" v-model="variant" @change="next" /> 压缩图（省流量）</label>
      <label><input type="radio" value="original" v-model="variant" @change="next" /> 原始图</label>
    </div>

    <div v-if="loading" class="spinner"></div>
    <img v-else-if="item" :src="src(item)" :alt="item.key" @click="next" />
    <p v-else class="muted">空っぽ / 还没有图片，先去 Upload 传几张</p>

    <div class="actions" v-if="item">
      <button @click="next">再来一张</button>
      <button class="ghost" @click="copy(variant)">复制当前图 URL</button>
      <button class="ghost" @click="copy('original')">复制原图 URL</button>
      <a :href="src(item)" target="_blank"><button class="ghost">原窗口打开</button></a>
    </div>
    <p class="muted mono" v-if="item">
      直链：<code>{{ randomImageUrl('compressed') }}</code> / <code>{{ randomImageUrl('original') }}</code>
      <span v-if="store.site.random_public !== '1'">（当前仅登录可用，后台可开放）</span>
    </p>
  </div>
</template>
