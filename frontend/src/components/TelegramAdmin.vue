<script setup>
import '../draft-test.js'
import BotBindingPanel from './BotBindingPanel.vue'
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
const ownBindings = computed(() => status.value?.bindings?.filter(b=>b.active && b.username===store.user?.username) || [])
const remaining = computed(() => Math.max(0, Math.ceil((expiry.value - clock.value) / 1000)))
const canPair = computed(() => status.value?.bot && props.saved.telegram_enabled === '1' && !telegramDirty.value && !props.saving && !busy.value)
let alive = true
let poll, tick

async function unbindOwn(){ for(const binding of ownBindings.value) await action('unbind',{telegramId:binding.telegramId}) }
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
  <BotBindingPanel :model-value="settings.telegram_bot_token" @update:model-value="settings.telegram_bot_token=$event" :configured="status?.configured" :enabled="saved.telegram_enabled==='1'" :bound="!!ownBindings.length" :dirty="telegramDirty" :busy="busy || saving" :bot="status?.bot" :command="remaining ? command : ''" :error="error || status?.error" @save="settings.telegram_enabled='1';emit('save')" @generate="action('pair')" @unbind="unbindOwn()" @toggle="settings.telegram_enabled=saved.telegram_enabled==='1'?'0':'1';emit('save')">
   <label class="check-line"><input type="checkbox" :checked="settings.telegram_include_private==='1'" @change="settings.telegram_include_private=$event.target.checked?'1':'0'" />{{ t('允许通过 Telegram 获取私密标签图片') }}</label>
   <p class="hint">{{ t('仅绑定且启用的管理员可取图。绑定后才会授予取图权限。一个机器人只供一个实例使用。') }}</p>
  </BotBindingPanel>
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
