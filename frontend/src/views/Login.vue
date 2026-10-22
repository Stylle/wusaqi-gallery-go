<script setup>
import { ref } from 'vue'
import { doLogin, doTokenLogin } from '../auth.js'
import { site } from '../site.js'
import { t } from '../i18n.js'

const username = ref('')
const password = ref('')
const remember = ref(true)
const msg = ref('')
const busy = ref(false)

// 管理员 Token 兼容入口
const tokenMode = ref(false)
const token = ref('')

async function submit() {
  if (busy.value) return
  busy.value = true
  msg.value = ''
  try {
    if (tokenMode.value) {
      if (!token.value.trim()) throw new Error(t('请填写 Token'))
      await doTokenLogin(token.value.trim(), remember.value)
    } else {
      if (!username.value.trim()) throw new Error(t('请填写用户名'))
      await doLogin(username.value.trim(), password.value, remember.value)
    }
    location.hash = '#/gallery'
  } catch (e) {
    msg.value = e.status === 429 ? t('尝试次数过多，已临时封禁，请稍后再试') : e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <h2 class="page-title" style="display:flex;align-items:center;gap:10px">
        <img src="/logo.svg" alt="" style="width:30px;height:30px" />
        {{ site.site_title }}
      </h2>
      <p class="muted" style="margin-top:-6px">{{ t('登录后可上传图片、复制链接与使用随机图 API。') }}</p>

      <div class="field" v-if="!tokenMode">
        <label>{{ t('用户名') }}</label>
        <input v-model="username" autocomplete="username" placeholder="username" @keyup.enter="submit" />
      </div>
      <div class="field" v-else>
        <label>{{ t('管理员 Token') }}</label>
        <input v-model="token" type="password" placeholder="ADMIN_TOKEN" @keyup.enter="submit" />
      </div>

      <div class="field">
        <label>{{ tokenMode ? '' : t('密码') }}</label>
        <input v-if="!tokenMode" v-model="password" type="password" autocomplete="current-password"
          placeholder="password" @keyup.enter="submit" />
      </div>

      <label class="remember">
        <input type="checkbox" v-model="remember" />
        {{ t('记住我（30 天内免登录；不勾选则关闭浏览器失效）') }}
      </label>

      <button style="width:100%;margin-top:6px" :disabled="busy" @click="submit">
        {{ busy ? t('登录中…') : t('登录') }}
      </button>
      <p class="tag-err" style="min-height:20px">{{ msg }}</p>

      <div class="login-foot">
        <a href="javascript:void 0" v-if="site.token_login === '1'" @click="tokenMode = !tokenMode">
          {{ tokenMode ? t('← 用账号密码登录') : t('用管理员 Token 登录') }}
        </a>
        <span class="muted">{{ t('没有账号？联系管理员开通。') }}</span>
      </div>
    </div>
  </div>
</template>
