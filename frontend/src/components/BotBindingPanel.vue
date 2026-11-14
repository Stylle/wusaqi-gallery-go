<script setup>
import { t } from '../i18n.js'
defineProps({ modelValue:String, configured:Boolean, enabled:Boolean, bound:Boolean, bot:String, command:String, busy:Boolean, dirty:Boolean, error:String })
defineEmits(['update:modelValue','save','generate','unbind','toggle'])
</script>
<template>
 <section class="bot-binding-card">
  <h2>{{ t('Telegram 机器人') }}</h2>
  <p class="muted">{{ t('填写 Token 并保存，生成绑定码后，在机器人私聊中发送完整的 /bind 指令即可。') }}</p>
  <label>Bot Token<input type="password" autocomplete="new-password" spellcheck="false" :value="modelValue" :placeholder="t(configured ? 'Token 已保存，留空保留' : '填入 BotFather 提供的 Token')" @input="$emit('update:modelValue',$event.target.value)" /></label>
  <div class="binding-actions"><button type="button" class="primary" :disabled="busy" @click="$emit('save')">{{ t('保存设置') }}</button><button type="button" :disabled="busy || dirty || !configured || !enabled" @click="$emit('generate')">{{ t('生成绑定码') }}</button><button v-if="bound" type="button" class="ghost" :disabled="busy" @click="$emit('unbind')">{{ t('解除绑定') }}</button></div>
  <p class="binding-status" role="status">{{ t(!configured ? '尚未保存 Token' : !enabled ? '机器人已停用' : bound ? '已绑定' : '已保存，等待绑定') }}<a v-if="bot" :href="'https://t.me/'+bot" target="_blank" rel="noopener noreferrer"> @{{ bot }}</a></p>
  <p v-if="dirty" class="muted">{{ t('有未保存的修改，请先保存再生成绑定码。') }}</p>
  <div v-if="command" class="binding-command"><label>{{ t('在 Telegram 私聊发送以下完整指令') }}<input :value="command" readonly autocomplete="off" spellcheck="false" @focus="$event.target.select()" /></label><p class="muted">{{ t('绑定码五分钟有效、仅可使用一次。请勿分享，重新生成会使旧码失效。') }}</p></div>
  <p v-if="error" class="error" role="alert">{{ t(error) }}</p>
  <details><summary>{{ t('更多设置') }}</summary><button type="button" class="ghost" :disabled="busy" @click="$emit('toggle')">{{ t(enabled ? '停用机器人' : '启用机器人') }}</button><slot /></details>
 </section>
</template>
<style src="./binding-panel.css"></style>
