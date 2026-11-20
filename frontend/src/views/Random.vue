<script setup>
import { shareUrl } from '../media.js'
import { ref, computed, watch, onUnmounted } from 'vue'
import { getRandom, getTags, copyText, getRandomToken } from '../api.js'
import { absUrl, site } from '../site.js'
import { store } from '../auth.js'
import { t } from '../i18n.js'
import { randomEndpoint } from '../random-url.js'

const variant = ref('compressed')
const tag = ref('')
const tags = ref([])
getTags(store.token).then(d => { tags.value = d.tags || [] }).catch(() => {})
const item = ref(null)
const loading = ref(false)
const error = ref('')
const copyMessage = ref('')
const apiBusy=ref(false)
const personalToken=ref('')
const tokenLoading=ref(false)
const publicAvailable=computed(()=>site.site_public==='1'&&site.external_links_enabled==='1')
const publicEndpoint=computed(()=>randomEndpoint(variant.value,tag.value))
watch(()=>store.ok ? store.token : '',async current=>{
 personalToken.value=''
 if(!current){tokenLoading.value=false;return}
 tokenLoading.value=true
 try{const result=await getRandomToken(current);if(store.token===current&&store.ok)personalToken.value=result.token}
 catch(e){if(store.token===current)copyMessage.value=e.message}
 finally{if(store.token===current)tokenLoading.value=false}
},{immediate:true})
async function copyEndpoint(personal=!!store.token){
 if(apiBusy.value)return
 apiBusy.value=true
 try {
  let token=''
  if(personal){
   const current=store.token
   if(!personalToken.value){const result=await getRandomToken(current);if(store.token!==current)return;personalToken.value=result.token}
   token=personalToken.value
  }
  await copyText(randomEndpoint(variant.value,tag.value,token))
  copyMessage.value=t(personal?'已复制个人随机接口':'已复制公开随机接口')
 }catch(e){copyMessage.value=e.message}finally{apiBusy.value=false}
}
let requestVersion = 0

async function next() {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  try {
    const result = await getRandom(variant.value, store.token, tag.value)
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
    const path = shareUrl(item.value, v) || (v === 'compressed' ? shareUrl(item.value, 'original') : '')
    if (!path) { copyMessage.value = t('此图片未开放外链'); return }
    await copyText(absUrl(path))
    copyMessage.value = t('已复制链接')
  } catch (e) { copyMessage.value = e.message }
}
next()
onUnmounted(() => { requestVersion++ })
</script>

<template>
  <div class="randbox">
    <div class="actions" style="margin-bottom:16px">
      <label>{{ t('标签') }} <select v-model="tag" @change="next"><option value="">{{ t('全部') }}</option><option v-for="tg in tags" :key="tg.name" :value="tg.name">{{ tg.name }}</option></select></label>
      <label><input type="radio" value="compressed" v-model="variant" @change="next" /> {{ t('压缩图（省流量）') }}</label>
      <label><input type="radio" value="original" v-model="variant" @change="next" /> {{ t('原始图') }}</label>
    </div>

    <div class="random-stage" aria-live="polite" :aria-busy="loading">
      <div v-if="loading" class="spinner"></div>
      <img v-else-if="item" :src="src(item)" :alt="item.origName || item.key" @click="next" />
      <p v-else-if="error" class="tag-err" role="alert">{{ error }} <button class="ghost" @click="next">{{ t('重试加载') }}</button></p>
      <p v-else class="muted">{{ t('还没有图片') }}{{ t('，先去 Upload 传几张') }}</p>
    </div>

    <div class="actions" v-if="item">
      <button @click="next">{{ t('再来一张') }}</button>
      <button class="ghost" :disabled="!shareUrl(item, 'original')" @click="copy(variant)">{{ t('复制当前图 URL') }}</button>
      <button class="ghost" :disabled="!shareUrl(item, 'original')" @click="copy('original')">{{ t('复制原图 URL') }}</button>
      <a :href="src(item)" target="_blank" rel="noopener noreferrer" class="link-button">{{ t('新窗口打开') }}</a>
    </div>
    <section class="random-api panel">
      <h3>{{ t('随机图接口') }}</h3>
      <p class="muted">{{ t(store.token ? '个人接口含只读取图 Token，修改密码后失效，账号停用期间不可用。请勿公开分享。' : '站点已开放，无需登录或 Token 即可获取公开随机图。') }}</p>
      <code class="random-endpoint">{{ publicEndpoint }}{{ store.token ? '&token=••••••' : '' }}</code>
      <div class="actions">
        <button :disabled="apiBusy || tokenLoading || (!store.token && !publicAvailable)" @click="copyEndpoint()">{{ t(store.token ? '复制个人随机接口' : '复制随机图接口') }}</button>
        <button v-if="store.token && publicAvailable" class="ghost" :disabled="apiBusy" @click="copyEndpoint(false)">{{ t('复制公开随机接口') }}</button>
      </div>
      <p v-if="!publicAvailable" class="muted">{{ t('公开接口需开启站点公开访问与图片外链；个人接口仍可凭 Token 取图。') }}</p>
    </section>
    <p v-if="copyMessage" class="muted" role="status">{{ copyMessage }}</p>
  </div>
</template>
