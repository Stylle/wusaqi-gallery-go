<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { telegramStatus, telegramAction } from '../api.js'
import { store } from '../auth.js'
import { t } from '../i18n.js'

const props = defineProps({ settings: Object, saved: Object, saving: Boolean, message: String, messageBad: Boolean })
const emit = defineEmits(['save', 'settings', 'testing'])
const status = ref(null)
const error = ref('')
const busy = ref(false)
const loading = ref(false)
const command = ref('')
const expiry = ref(0)
const clock = ref(Date.now())
const clearDialog = ref(null)
const dirty = computed(() => Object.keys(props.settings).some(k => props.settings[k] !== props.saved[k]))
const telegramDirty = computed(() => ['telegram_enabled', 'telegram_bot_token', 'telegram_include_private']
  .some(k => props.settings[k] !== props.saved[k]))
const remaining = computed(() => Math.max(0, Math.ceil((expiry.value - clock.value) / 1000)))
const canPair = computed(() => status.value?.bot && props.saved.telegram_enabled === '1' && !telegramDirty.value && !props.saving && !busy.value)
let alive = true
let poll, tick

async function refresh() {
  if (!alive || loading.value || !store.token) return
  loading.value = true
  try {
    const value = await telegramStatus(store.token)
    if (!alive) return
    if (status.value && JSON.stringify(status.value.bindings) !== JSON.stringify(value.bindings)) command.value = ''
    status.value = value
    error.value = ''
  } catch (e) { if (alive) error.value = e.message }
  finally { loading.value = false }
}
async function action(name, value) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await telegramAction(store.token, name, value)
    if (!alive) return
    if (name === 'pair') {
      command.value = result.command
      clock.value = Date.now()
      expiry.value = clock.value + result.expiresIn * 1000
    }
    if (name === 'token/clear') {
      command.value = ''
      emit('settings', result)
    }
    await refresh()
  } catch (e) { if (alive) error.value = e.message }
  finally { busy.value = false }
}
watch(busy, value => emit('testing', value), { flush: 'sync' })
watch(() => props.saved, () => { command.value = ''; refresh() })
onMounted(() => {
  refresh()
  poll = setInterval(refresh, 5000)
  tick = setInterval(() => { clock.value = Date.now() }, 1000)
})
onUnmounted(() => { emit('testing', false); alive = false; clearInterval(poll); clearInterval(tick) })
</script>

<template>
  <div class="telegram-panel">
    <section class="telegram-settings">
    <p class="muted">{{ t('通过私聊指令获取随机图。仅绑定且仍处于启用状态的站点管理员可用，普通用户和群聊请求均被忽略。') }}</p>
    <div class="field">
      <label class="check-line"><input type="checkbox" :checked="settings.telegram_enabled === '1'" @change="settings.telegram_enabled = $event.target.checked ? '1' : '0'" />{{ t('开启 Telegram 机器人') }}</label>
      <span class="hint">{{ t('使用长轮询，无需公网域名、额外端口或 Webhook。一个 Bot 只供一个实例使用。') }}</span>
    </div>
    <div class="field">
      <label for="telegram-token">Telegram Bot Token</label>
      <input id="telegram-token" v-model="settings.telegram_bot_token" type="password" autocomplete="new-password" spellcheck="false" :placeholder="t(status?.configured ? 'Token 已保存，留空保留' : '填入 BotFather 提供的 Token')" />
      <span class="hint">{{ t('在 Telegram 的 BotFather 创建 Bot。Token 仅用于服务器出站请求，保存后不会回显。') }} <a href="https://core.telegram.org/bots/features#creating-a-new-bot" target="_blank" rel="noopener noreferrer">{{ t('创建说明') }}</a></span>
    </div>
    <div class="field">
      <label class="check-line"><input type="checkbox" :checked="settings.telegram_include_private === '1'" @change="settings.telegram_include_private = $event.target.checked ? '1' : '0'" />{{ t('允许通过 Telegram 获取私密标签图片') }}</label>
      <span class="hint">{{ t('默认关闭。开启后须明确发送 /random 私密；不带参数始终排除私密图。图片会上传至 Telegram，已发送的内容无法通过站点开关撤回。') }}</span>
    </div>
    <div class="row form-actions">
      <button :disabled="saving || busy" @click="emit('save')">{{ t(saving ? '保存中…' : '保存全部设置') }}</button>
      <span class="msg-line" :class="{ bad: messageBad }" role="status">{{ message || (dirty ? t('有未保存的修改') : '') }}</span>
    </div>

    </section>

    <section class="telegram-section">
      <h3>{{ t('连接与管理员绑定') }}</h3>
      <p v-if="status" class="connection-status" role="status">
        <span v-if="!status.enabled">{{ t('机器人已关闭') }}</span>
        <span v-else-if="!status.configured">{{ t('尚未配置 Token') }}</span>
        <a v-else-if="status.bot" :href="'https://t.me/' + status.bot" target="_blank" rel="noopener noreferrer">{{ t('已连接') }} @{{ status.bot }}</a>
        <span v-else>{{ t('正在连接 Telegram…') }}</span>
      </p>
      <p v-if="status?.error || error" class="tag-err" role="alert">{{ error || t(status.error) }}</p>
      <p class="hint muted">{{ t('先保存配置，再生成绑定码。使用自己的 Telegram 账号私聊机器人，发送下方完整指令；绑定码五分钟有效、仅可使用一次。每次生成会替换上一个码，请勿分享。') }}</p>
      <div class="row">
        <button :disabled="!canPair" @click="action('pair')">{{ t(busy ? '处理中…' : '生成我的绑定码') }}</button>
      </div>
      <p v-if="telegramDirty" class="hint muted">{{ t('请先保存 Telegram 设置再绑定') }}</p>
      <div v-if="command && remaining" class="field">
        <label for="telegram-bind-command">{{ t('发送给机器人的绑定指令') }} · {{ remaining }}s</label>
        <input id="telegram-bind-command" :value="command" readonly class="mono" data-no-i18n @focus="$event.target.select()" />
      </div>
      <p v-else-if="command" class="hint muted">{{ t('绑定码已过期，请重新生成') }}</p>
      <ul v-if="status?.bindings.length" class="telegram-bindings">
        <li v-for="binding in status.bindings" :key="binding.telegramId">
          <div><strong>{{ binding.username || t('已删除的账号') }}</strong> · {{ t(binding.active ? '有效' : '已失效') }}<br /><span class="mono">Telegram ID: {{ binding.telegramId }}</span></div>
          <button class="ghost danger" :disabled="busy" @click="action('unbind', { telegramId: binding.telegramId })">{{ t('解除绑定') }}</button>
        </li>
      </ul>
      <p v-else-if="status" class="muted">{{ t('暂无已绑定管理员') }}</p>
      <p class="hint muted">{{ t('停用、删除或降级站点管理员会立即停止其机器人权限。关闭公开访问或外链不影响已绑定管理员取图。') }}</p>
    </section>

    <section class="telegram-section">
      <h3>{{ t('机器人指令') }}</h3>
      <dl class="telegram-commands">
        <dt><code>/random</code></dt><dd>{{ t('随机获取一张非私密图片') }}</dd>
        <dt><code>/random 标签名</code></dt><dd>{{ t('按完整标签精确匹配，支持中文和空格') }}</dd>
        <dt><code>/tags</code></dt><dd>{{ t('查看可用标签与图片数') }}</dd>
        <dt><code>/help</code></dt><dd>{{ t('查看指令帮助') }}</dd>
      </dl>
      <p class="hint muted">{{ t('JPG/PNG 优先以照片发送，GIF 以动图发送；其他格式或超出照片限制时作为文件发送，单个文件最大 50 MB。直接流式上传文件，无需开放图片外链。') }}</p>
    </section>
    <div class="row">
      <button class="ghost danger" :disabled="busy || saving || dirty || !status?.configured" @click="clearDialog.showModal()">{{ t('删除 Token 并关闭机器人') }}</button>
    </div>
    <dialog ref="clearDialog" class="modal" aria-labelledby="telegram-clear-title">
      <h3 id="telegram-clear-title">{{ t('删除 Telegram Token') }}</h3>
      <p>{{ t('将关闭机器人、删除保存的 Token 并解除全部绑定。重新接入时需要再次绑定。') }}</p>
      <div class="row"><button class="ghost" autofocus @click="clearDialog.close()">{{ t('取消') }}</button><button class="danger-btn" @click="clearDialog.close(); action('token/clear')">{{ t('确认删除') }}</button></div>
    </dialog>
  </div>
</template>

<style scoped>
.telegram-panel { min-width: 0; }
.telegram-section { border-top: 1px solid var(--border); margin-top: 24px; padding-top: 8px; }
.telegram-bindings { padding: 0; list-style: none; }
.telegram-bindings li { display: flex; gap: 12px; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border); overflow-wrap: anywhere; }
.telegram-bindings button { flex-shrink: 0; }
.telegram-commands { display: grid; grid-template-columns: max-content 1fr; gap: 12px 16px; font-size: 13px; }
.telegram-commands dd { margin: 0; color: var(--muted); }
.connection-status { overflow-wrap: anywhere; }
@media (max-width: 480px) {
  .telegram-commands { grid-template-columns: 1fr; gap: 6px; }
  .telegram-commands dd { margin-bottom: 10px; }
  .telegram-bindings li { align-items: flex-start; flex-wrap: wrap; }
}
</style>
