<script setup>
import { ref } from 'vue'
import { site } from '../site.js'
import { retryAuth } from '../auth.js'
import { t } from '../i18n.js'

const props = defineProps({ serverError: { type: Boolean, default: false } })
const busy = ref(false)
const failed = ref(false)

function go() { location.hash = '#/login' }

async function retry() {
  busy.value = true
  failed.value = false
  try {
    const ok = await retryAuth()
    if (!ok) failed.value = true
  } catch { failed.value = true }
  finally { busy.value = false }
}
</script>

<template>
  <div class="lockbox">
    <template v-if="serverError">
      <div class="icon">🛠️</div>
      <h2 class="page-title">{{ t('后端暂时连不上') }}</h2>
      <p class="muted">
        {{ t('登录状态还在，只是这次没能连上服务（可能是后端刚重启）。') }}
        {{ t('点下面重试一次即可，不用重新登录。') }}
      </p>
      <button :disabled="busy" @click="retry">{{ busy ? t('重试中…') : t('重试连接') }}</button>
      <p class="muted" v-if="failed" style="margin-top:10px">{{ t('仍然连不上，确认后端已启动后再试。') }}</p>
    </template>
    <template v-else>
      <div class="icon">🔒</div>
      <h2 class="page-title">{{ t('需要登录') }}</h2>
      <p class="muted">{{ site.site_public !== '1' ? t('站点未开放公开访问，请先登录') : t('上传、后台及受限功能需要登录。') }}</p>
      <button @click="go">{{ t('去登录') }}</button>
    </template>
  </div>
</template>
