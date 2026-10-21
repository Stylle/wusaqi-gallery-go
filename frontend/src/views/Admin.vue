<script setup>
import { ref, onMounted } from 'vue'
import { getSettings, saveSettings, reindex, getBans } from '../api.js'
import { store, applySite } from '../auth.js'

const groups = [
  { title: '站点信息', items: [
    { id: 'site', label: '🏷️ 站点与外观', fields: [
      { k: 'site_title', label: '站点标题', hint: '浏览器标签页与顶栏显示' },
      { k: 'site_icon', label: '站点图标', hint: '填图片 URL 或单个 emoji（如 🌶️）' },
      { k: 'site_tags', label: '首页标签', hint: '逗号分隔，显示在画廊顶部' },
      { k: 'site_footer', label: '底部文字', hint: '页脚展示，可留空隐藏' },
    ] },
  ]},
  { title: '图片处理', items: [
    { id: 'compress', label: '🖼️ 压缩设置', fields: [
      { k: 'comp_format', label: '压缩格式', type: 'select', options: ['webp', 'jpeg', 'png'], hint: '对外分享用的压缩版格式' },
      { k: 'comp_quality', label: '压缩质量 (1-100)', type: 'number' },
      { k: 'comp_max_width', label: '最大宽度 px (0=不缩放)', type: 'number' },
    ], hint: '仅对新上传生效，历史压缩版不变' },
  ]},
  { title: '流量与权限', items: [
    { id: 'traffic', label: '🚦 流量防御', fields: [
      { k: 'rate_limit', label: '随机图限流 (次/分钟/IP，0=关闭)', type: 'number' },
      { k: 'rate_ban_minutes', label: '超限封禁时长 (分钟)', type: 'number' },
      { k: 'webhook_url', label: '告警 Webhook URL', hint: '超限/爆破时 POST JSON 通知（支持企微/钉钉/飞书自定义机器人中转）' },
    ] },
    { id: 'perm', label: '🔑 访问权限', fields: [
      { k: 'random_public', label: '随机图 API 对游客开放', type: 'switch', hint: '开启后未登录也能用外链（会被限流），关闭则仅登录可用' },
    ] },
  ]},
  { title: '安全', items: [
    { id: 'security', label: '🛡️ 防爆破', fields: [
      { k: 'auth_max_fails', label: '鉴权失败次数阈值 (10分钟内)', type: 'number' },
      { k: 'auth_ban_minutes', label: '触发后封禁时长 (分钟)', type: 'number' },
    ], hint: '路径由 FastAPI 静态挂载与 nginx 白名单路径保证，无目录遍历面' },
  ]},
]

const active = ref('site')
const s = ref(null)
const msg = ref('')
const bans = ref([])

onMounted(async () => {
  s.value = await getSettings(store.token)
  loadBans()
})

async function loadBans() {
  try { bans.value = (await getBans(store.token)).bans } catch { }
}

async function save() {
  msg.value = '保存中…'
  try {
    s.value = await saveSettings(store.token, s.value)
    msg.value = '已保存 ✓'
    applySite() // 站点标题/图标立即生效
  } catch (e) { msg.value = '失败：' + e.message }
}

async function doReindex() {
  msg.value = '扫描中…'
  try {
    const d = await reindex(store.token)
    msg.value = `扫描 ${d.scanned} 个文件，补录 ${d.added} 条`
  } catch (e) { msg.value = '失败：' + e.message }
}

const currentGroup = () => groups.flatMap(g => g.items).find(i => i.id === active.value)
</script>

<template>
  <h2 class="page-title">后台配置</h2>
  <div class="admin-layout" v-if="s">
    <aside class="admin-tree">
      <div class="group" v-for="g in groups" :key="g.title">
        <div class="group-title">{{ g.title }}</div>
        <button v-for="it in g.items" :key="it.id" class="item" :class="{ on: active === it.id }"
          @click="active = it.id">{{ it.label }}</button>
      </div>
    </aside>

    <section class="admin-content">
      <h3>{{ currentGroup()?.label }}</h3>
      <template v-for="f in currentGroup()?.fields" :key="f.k">
        <div class="field" v-if="f.type !== 'switch'">
          <label>{{ f.label }}</label>
          <select v-if="f.type === 'select'" v-model="s[f.k]" style="max-width:280px">
            <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
          </select>
          <input v-else-if="f.type === 'number'" type="number" v-model.number="s[f.k]" style="max-width:280px" />
          <input v-else v-model="s[f.k]" style="max-width:420px" />
          <span class="hint" v-if="f.hint">{{ f.hint }}</span>
        </div>
        <div class="field" v-else>
          <label style="display:flex;gap:8px;align-items:center;color:var(--text)">
            <input type="checkbox" style="width:16px;height:16px" :checked="s[f.k] === '1'"
              @change="s[f.k] = $event.target.checked ? '1' : '0'" /> {{ f.label }}
          </label>
          <span class="hint" v-if="f.hint">{{ f.hint }}</span>
        </div>
      </template>
      <p class="hint muted" v-if="currentGroup()?.hint">{{ currentGroup().hint }}</p>

      <div class="row" style="margin-top:18px">
        <button @click="save">保存全部设置</button>
        <button class="ghost" @click="doReindex">重建索引</button>
        <button class="ghost" @click="loadBans">刷新封禁列表</button>
        <span class="muted">{{ msg }}</span>
      </div>

      <div v-if="bans.length" class="panel" style="margin-top:16px">
        <h3>当前封禁</h3>
        <div v-for="b in bans" :key="b.ip" class="mono muted">
          {{ b.ip }} · {{ b.reason }} · 至 {{ b.until }}
        </div>
      </div>
    </section>
  </div>
  <div v-else class="spinner"></div>
</template>
