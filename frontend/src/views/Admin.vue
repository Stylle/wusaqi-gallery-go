<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import {
  getSettings, saveSettings, getBans, getPublicSettings, getSystem,
  listUsers, createUser, updateUser, deleteUser, fmtSize,
  scanLocal, compressLocal, getStats, testNotify,
} from '../api.js'
import { store, isAdmin, refreshMe, ensureAuth } from '../auth.js'
import { setSite } from '../site.js'
import { t } from '../i18n.js'

// 统一的错误文案：401 不再裸露 "login required"
function errText(e) {
  if (e && e.status === 401) return t('登录已失效，请重新登录')
  return e?.message || String(e)
}

const groups = [
  { title: '站点信息', items: [
    { id: 'site', label: '🏷️ 站点与外观', fields: [
      { k: 'site_title', label: '站点标题', hint: '浏览器标签页与顶栏显示' },
      { k: 'site_icon', label: '站点图标', hint: '填图片 URL 或单个 emoji（如 🌶️）；留空使用默认 logo' },
      { k: 'site_tags', label: '标签池', hint: '逗号分隔，作为顶部筛选项与上传可选项' },
      { k: 'site_footer', label: '底部文字', hint: '页脚展示，可留空隐藏' },
    ] },
    { id: 'share', label: '🔗 分享与上传', fields: [
      { k: 'share_base_url', label: '分享基址', hint: '复制链接用的域名，如 https://img.example.com；留空 = 用当前访问地址' },
      { k: 'upload_default_tags', label: '上传默认标签', hint: '逗号分隔，上传页默认选中第一个' },
    ] },
  ]},
  { title: '图片处理', items: [
    { id: 'compress', label: '🗜️ 压缩方案', custom: 'compress' },
    { id: 'limits', label: '📤 上传限制', fields: [
      { k: 'upload_max_mb', label: '全局单图上限 (MB，0=不限)', type: 'number',
        hint: '默认 5MB；用户级「单图上限」优先于此项，管理员不受限' },
      { k: 'new_user_quota_mb', label: '新用户默认容量配额 (MB，0=不限)', type: 'number' },
      { k: 'new_user_max_upload_mb', label: '新用户默认单图上限 (MB，0=跟随全局)', type: 'number' },
      { k: 'new_user_daily', label: '新用户每日上传张数 (0=不限)', type: 'number' },
      { k: 'new_user_weekly', label: '新用户每周上传张数 (0=不限)', type: 'number' },
      { k: 'new_user_monthly', label: '新用户每月上传张数 (0=不限)', type: 'number' },
    ], hint: '上面 5 项只是「新建用户」时表单的默认值，建好后可在用户管理里单独改；管理员始终不受上传张数、单图与容量限制。' },
  ]},
  { title: '账号与权限', items: [
    { id: 'login', label: '🔐 登录规则', fields: [
      { k: 'session_hours', label: '未勾「记住我」有效期 (小时)', type: 'number' },
      { k: 'remember_days', label: '勾选「记住我」有效期 (天)', type: 'number' },
      { k: 'random_public', label: '随机图 API 对游客开放', type: 'switch', hint: '开启后未登录也能用外链（会被限流）' },
    ] },
    { id: 'users', label: '👥 用户管理', custom: 'users' },
  ]},
  { title: '流量与安全', items: [
    { id: 'traffic', label: '🚦 流量防御', fields: [
      { k: 'rate_limit', label: '随机图限流 (次/分钟/IP，0=关闭)', type: 'number' },
      { k: 'rate_ban_minutes', label: '超限封禁时长 (分钟)', type: 'number' },
    ] },
    { id: 'stats', label: '📊 访问统计', custom: 'stats' },
    { id: 'security', label: '🛡️ 防爆破', fields: [
      { k: 'auth_max_fails', label: '鉴权失败次数阈值 (10分钟内)', type: 'number' },
      { k: 'auth_ban_minutes', label: '触发后封禁时长 (分钟)', type: 'number' },
    ] },
    { id: 'notify', label: '📣 通知', custom: 'notify' },
  ]},
  { title: '媒体维护', items: [
    { id: 'local', label: '📥 本地图库导入', custom: 'local' },
  ]},
  { title: '开发者', items: [
    { id: 'apidoc', label: '📡 API 文档', custom: 'apidoc' },
  ]},
]

const active = ref('site')
const s = ref(null)
const msg = ref('')
const msgBad = ref(false)
const saveBusy = ref(false)
const toast = ref(null)
let toastTimer = null
function showToast(text, ok = true) {
  toast.value = { text, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 3200)
}
const toastText = computed(() => toast.value?.text || '')
const toastOk = computed(() => toast.value?.ok !== false)
const bans = ref([])
const users = ref([])
const uMsg = ref('')
const form = ref(blankForm())
const editing = ref('')     // 空 = 新建

// ---- 本地图库（扫描导入 / 补压缩）----
const localInfo = ref(null)
const localMsg = ref('')
const localBusy = ref(false)
const importLimit = ref(20)
const compLimit = ref(5)
const compInfo = ref(null)
const compMsg = ref('')
const compBusy = ref(false)

// ---- 访问统计 ----
const stats = ref(null)
const statsMsg = ref('')
const statsBusy = ref(false)

// ---- 通知 ----
const notifyMsg = ref('')
const notifyOk = ref(null)   // null = 还没测过
const notifyBusy = ref(false)

// ---- 压缩方案（自动探测 / 手动档位 / 自定义）----
const sys = ref(null)
const fmtMem = (mb) => (mb ? (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`) : t('未知'))
const profileLabel = (name) =>
  t((sys.value?.profiles || []).find(p => p.name === name)?.label || name)
const profileOptions = computed(() => {
  const det = sys.value?.perf?.detected
  const autoDesc = det
    ? `${t('探测到')} ${det.cores} ${t('核 /')} ${fmtMem(det.memMb)}${t('，自动选「')}${profileLabel(sys.value.perf.autoProfile)}${t('」')}`
    : t('按机器的 CPU 核数与内存自动选档')
  return [
    { v: 'auto', label: t('自动探测（推荐）'), desc: autoDesc },
    ...(sys.value?.profiles || []).map(p => ({
      v: p.name, label: t(p.label),
      desc: `${t(p.desc)} · ${t('质量')} ${p.quality} / ${p.max_width}px / ${t('并发')} ${p.concurrency}`,
    })),
    { v: 'custom', label: t('自定义'), desc: t('手动指定质量、最大宽度、编码强度与并发数') },
  ]
})

async function loadSystem() {
  try { sys.value = await getSystem(store.token) } catch { /* 后端未更新时忽略 */ }
}

async function loadStats() {
  statsBusy.value = true
  statsMsg.value = ''
  try { stats.value = await getStats(store.token) }
  catch (e) { statsMsg.value = t('失败：') + errText(e) }
  finally { statsBusy.value = false }
}

async function sendTestNotify() {
  notifyBusy.value = true
  notifyMsg.value = t('发送中…')
  try {
    const d = await testNotify(store.token)
    notifyOk.value = !!d.ok
    notifyMsg.value = d.ok ? t('测试通知已发送，请查收 ✓') : `${t('失败：')}${t(d.error) || t('未知错误')}`
    showToast(notifyMsg.value, d.ok)
  } catch (e) {
    notifyOk.value = false
    notifyMsg.value = t('失败：') + errText(e)
    showToast(t('发送失败 ✗'), false)
  } finally { notifyBusy.value = false }
}

async function previewLocal() {
  localBusy.value = true
  localMsg.value = t('扫描中…')
  try {
    localInfo.value = await scanLocal(store.token, true, 50)
    localMsg.value = `${t('扫描')} ${localInfo.value.scanned} · ${t('已在库')} ${localInfo.value.indexed} · `
      + `${t('待导入')} ${localInfo.value.pendingCount} · ${t('无法识别')} ${localInfo.value.invalidCount}`
  } catch (e) {
    localMsg.value = t('失败：') + e.message
  } finally {
    localBusy.value = false
  }
}

async function doImport() {
  localBusy.value = true
  localMsg.value = t('导入中（会生成缩略图与压缩版，请稍候）…')
  try {
    const d = await scanLocal(store.token, false, importLimit.value)
    await previewLocal()
    const extra = d.failed.length ? `，${t('失败')} ${d.failed.length} ` + t('张') : ''
    localMsg.value = `${t('本次导入')} ${d.imported} ${t('张')}${extra}，${t('剩余')} ${d.remaining} ${t('张')}`
    await refreshMe()
  } catch (e) {
    localMsg.value = t('失败：') + e.message
  } finally {
    localBusy.value = false
  }
}

async function previewCompress() {
  compBusy.value = true
  compMsg.value = t('检查中…')
  try {
    compInfo.value = await compressLocal(store.token, true, compLimit.value)
    compMsg.value = compInfo.value.todoCount
      ? `${t('有')} ${compInfo.value.todoCount} ${t('张缺压缩版/缩略图')}`
      : t('全部图片都有压缩版与缩略图 ✓')
  } catch (e) {
    compMsg.value = t('失败：') + e.message
  } finally {
    compBusy.value = false
  }
}

async function runCompress() {
  compBusy.value = true
  compMsg.value = t('压缩中…')
  try {
    const d = await compressLocal(store.token, false, compLimit.value)
    await previewCompress()
    const extra = d.failed.length ? `，${t('失败')} ${d.failed.length} ` + t('张') : ''
    compMsg.value = `${t('本次处理')} ${d.done} ${t('张')}${extra}，${t('剩余')} ${d.remaining} ${t('张')}`
    await refreshMe()
  } catch (e) {
    compMsg.value = t('失败：') + e.message
  } finally {
    compBusy.value = false
  }
}

function blankForm() {
  const d = s.value || {}
  const num = (v, fb) => (v === undefined || v === '' ? fb : Number(v))
  return {
    username: '', password: '', role: 'user',
    quota_mb: num(d.new_user_quota_mb, 500),
    max_upload_mb: num(d.new_user_max_upload_mb, 5),
    daily_limit: num(d.new_user_daily, 30),
    weekly_limit: num(d.new_user_weekly, 100),
    monthly_limit: num(d.new_user_monthly, 250),
    comp_format: '', comp_quality: '', enabled: 1,
  }
}

const currentGroup = () => groups.flatMap(g => g.items).find(i => i.id === active.value)
const myQuota = computed(() => {
  const u = store.user
  if (!u) return null
  const total = u.quotaMb * 1024 * 1024
  return {
    total, used: u.usedBytes, count: u.imageCount,
    left: total ? Math.max(0, total - u.usedBytes) : -1,
    pct: total ? Math.min(100, u.usedBytes / total * 100) : 0,
  }
})

onMounted(async () => {
  // 等登录校验完成再发请求：子组件的 onMounted 早于 App 的，直接发会带空 token → 401
  await ensureAuth()
  if (!store.token) { msg.value = t('登录已失效，请重新登录'); return }
  await refreshMe()
  if (!isAdmin.value) return
  try {
    s.value = await getSettings(store.token)
  } catch (e) {
    msg.value = t('失败：') + errText(e)
    return
  }
  loadSystem()
  loadBans()
  loadUsers()
  loadStats()
  previewLocal()
  previewCompress()
})

// 切换左侧菜单时清掉上一页残留的提示，否则旧的「失败：…」会一直挂在新面板上
watch(active, () => {
  msg.value = ''
  notifyMsg.value = ''
  localMsg.value = ''
  compMsg.value = ''
  statsMsg.value = ''
})

async function loadBans() {
  try { bans.value = (await getBans(store.token)).bans } catch { }
}

async function loadUsers() {
  try { users.value = (await listUsers(store.token)).users } catch (e) { uMsg.value = errText(e) }
}

async function save() {
  if (saveBusy.value) return
  if (!store.token) { msg.value = t('登录已失效，请重新登录'); showToast(msg.value, false); return }
  saveBusy.value = true
  msgBad.value = false
  msg.value = t('保存中…')
  try {
    s.value = await saveSettings(store.token, s.value)
    setSite(await getPublicSettings())
    await loadSystem()
    msg.value = t('已保存 ✓（压缩方案对新上传生效）')
    showToast(t('设置已保存 ✓'))
  } catch (e) {
    msgBad.value = true
    msg.value = t('失败：') + errText(e)
    showToast(msg.value, false)
  } finally {
    saveBusy.value = false
  }
}

function editUser(u) {
  editing.value = u.id
  form.value = {
    username: u.username, password: '', role: u.role, quota_mb: u.quota_mb,
    max_upload_mb: u.max_upload_mb,
    daily_limit: u.daily_limit || 0,
    weekly_limit: u.weekly_limit || 0,
    monthly_limit: u.monthly_limit || 0,
    comp_format: u.comp_format || '',
    comp_quality: u.comp_quality ?? '',
    enabled: u.enabled,
  }
  uMsg.value = ''
}

function resetForm() { editing.value = ''; form.value = blankForm(); uMsg.value = '' }

function goUpload() { location.hash = '#/upload' }

async function submitUser() {
  uMsg.value = t('提交中…')
  const f = { ...form.value }
  f.comp_quality = f.comp_quality === '' || f.comp_quality === null ? null : Number(f.comp_quality)
  for (const k of ['quota_mb', 'max_upload_mb', 'daily_limit', 'weekly_limit', 'monthly_limit']) {
    f[k] = f[k] === '' || f[k] === null || Number.isNaN(Number(f[k])) ? 0 : Number(f[k])
  }
  f.comp_format = f.comp_format || null
  try {
    if (editing.value) {
      const patch = { ...f }
      delete patch.password
      if (form.value.password) patch.password = form.value.password
      await updateUser(store.token, editing.value, patch)
      uMsg.value = t('已更新 ✓')
    } else {
      await createUser(store.token, f)
      uMsg.value = `${t('用户')} ${f.username} ${t('已创建 ✓')}`
    }
    resetForm()
    await loadUsers()
  } catch (e) { uMsg.value = t('失败：') + e.message }
}

async function removeUser(u) {
  const purge = confirm(`${t('删除用户')} ${u.username}?\n\n${t('确定 = 其图片转交给管理员')}\n${t('取消')} = 不删除`)
  if (!purge) return
  try {
    await deleteUser(store.token, u.id, false)
    uMsg.value = `${t('已删除')} ${u.username}，${t('图片已转交给管理员')}`
    await loadUsers()
  } catch (e) { uMsg.value = t('失败：') + e.message }
}

async function toggleEnabled(u) {
  try {
    await updateUser(store.token, u.id, { enabled: u.enabled ? 0 : 1 })
    await loadUsers()
  } catch (e) { uMsg.value = t('失败：') + e.message }
}

function switchField(k, checked) { s.value[k] = checked ? '1' : '0' }

// 模板变量提示（含字面 {{}}，必须放 JS 里，不能直接写进模板插值）
const tplHint = computed(() =>
  t('可用变量：{{event}} 事件、{{message}} 内容、{{time}} 时间、{{site}} 站点名，以及事件附加字段（如 {{ip}}）'))
</script>

<template>
  <!-- 普通用户：只看自己的空间 -->
  <template v-if="!isAdmin">
    <h2 class="page-title">{{ t('我的空间') }}</h2>
    <div class="panel" v-if="myQuota">
      <div class="row" style="margin-top:0">
        <span>{{ t('账号') }}：<b>{{ store.user.username }}</b></span>
        <span class="muted">{{ myQuota.count }} {{ t('张') }} · {{ t('已用') }} {{ fmtSize(myQuota.used) }}</span>
      </div>
      <template v-if="myQuota.total">
        <div class="bar quota-bar" style="height:10px">
          <div :style="{ width: myQuota.pct + '%' }" :class="{ full: myQuota.pct >= 90 }"></div>
        </div>
        <p class="muted">
          {{ t('配额') }} {{ store.user.quotaMb }} MB · {{ t('剩余') }} <b>{{ fmtSize(myQuota.left) }}</b>
        </p>
      </template>
      <p class="muted" v-else>{{ t('不限容量') }}</p>
      <p class="muted" v-if="store.user.maxUploadMb">
        {{ t('单图上限') }} <b>{{ store.user.maxUploadMb }} MB</b> ·
        {{ t('今日已传') }} {{ store.user.uploadCounts?.day || 0 }}/{{ store.user.uploadLimits?.daily || '∞' }} {{ t('张') }}
      </p>
      <p class="hint muted" v-if="store.user.compQuality">
        {{ t('你的图片会按质量') }} {{ store.user.compQuality }} {{ t('压缩') }}
      </p>
      <div class="row">
        <button @click="goUpload">{{ t('去上传') }}</button>
      </div>
    </div>
    <p class="hint muted">{{ t('站点配置与用户管理仅管理员可见；需要扩容或改压缩参数请联系管理员。') }}</p>
  </template>

  <!-- 管理员 -->
  <template v-else>
    <h2 class="page-title">{{ t('后台配置') }}</h2>
    <div class="admin-layout" v-if="s">
      <aside class="admin-tree">
        <div class="group" v-for="g in groups" :key="g.title">
          <div class="group-title">{{ t(g.title) }}</div>
          <button v-for="it in g.items" :key="it.id" class="item" :class="{ on: active === it.id }"
            @click="active = it.id">{{ t(it.label) }}</button>
        </div>
      </aside>

      <section class="admin-content">
        <h3>{{ t(currentGroup()?.label) }}</h3>

        <!-- 压缩方案 -->
        <template v-if="currentGroup()?.custom === 'compress'">
          <div class="panel" v-if="sys" style="margin-top:0">
            <h3 style="font-size:14px">{{ t('当前生效') }}</h3>
            <p class="muted" style="margin-top:0">
              {{ t('程序自动探测') }}：<b>{{ sys.perf.detected.cores }} {{ t('核 /') }} {{ fmtMem(sys.perf.detected.memMb) }}</b>
              → {{ t('建议') }}「{{ profileLabel(sys.perf.autoProfile) }}」<br />
              {{ t('实际生效') }}：<b>{{ t(sys.perf.label) }}</b> · {{ sys.perf.format }} · {{ t('质量') }} {{ sys.perf.quality }} ·
              {{ t('最大宽') }} {{ sys.perf.maxWidth || t('不缩放') }}px · {{ t('并发') }} {{ sys.perf.concurrency }} ·
              {{ t('单图分辨率上限') }} {{ sys.perf.maxPixels }} MP
              <span class="muted" v-if="sys.perf.mode === 'auto'">（{{ t('跟随自动探测') }}）</span>
            </p>
            <div class="profile-grid">
              <button v-for="p in profileOptions" :key="p.v" class="profile-card"
                :class="{ on: s.comp_profile === p.v }" @click="s.comp_profile = p.v">
                <b>{{ p.label }}</b>
                <small>{{ p.desc }}</small>
              </button>
            </div>
            <p class="hint muted">
              {{ t('选「自动探测」后，机器换成 1 核 1G 会自动降档，不用改配置；手动指定某档或「自定义」则固定使用该参数。') }}
            </p>
          </div>

          <h3>{{ t('方案对照') }}</h3>
          <div class="table-scroll">
            <table class="user-table" style="margin-top:0">
              <thead>
                <tr><th>{{ t('方案') }}</th><th>{{ t('适用机器') }}</th><th>{{ t('质量') }}</th><th>{{ t('最大宽度') }}</th><th>{{ t('分辨率上限') }}</th><th>{{ t('并发') }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in sys?.profiles || []" :key="p.name">
                  <td><b>{{ t(p.label) }}</b> <span class="mono muted" style="font-size:11px">{{ p.name }}</span></td>
                  <td class="muted" style="font-size:12px">{{ t(p.desc) }}</td>
                  <td>{{ p.quality }}</td>
                  <td>{{ p.max_width }}px</td>
                  <td>{{ p.max_pixels }} MP</td>
                  <td>{{ p.concurrency }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="hint muted">
            {{ t('质量与宽度决定成图体积；「并发」是同时压缩的张数 —— 1 核机器必须是 1，否则两张 5000px 大图同时解码就可能把内存吃光。') }}
          </p>

          <div class="field">
            <label>{{ t('压缩格式（所有方案共用）') }}</label>
            <select v-model="s.comp_format" style="max-width:320px">
              <option value="webp">webp（{{ t('推荐：同画质体积最小') }}）</option>
              <option value="jpeg">jpeg（{{ t('兼容性最好') }}）</option>
              <option value="png">png（{{ t('无损，体积大') }}）</option>
            </select>
            <span class="hint">{{ t('只影响对外分享的压缩版；原图始终保留上传时的原始格式') }}</span>
          </div>

          <template v-if="s.comp_profile === 'custom'">
            <h3>{{ t('自定义参数') }}</h3>
            <div class="user-form">
              <div class="field">
                <label>{{ t('质量 (1-100)') }}</label>
                <input v-model.number="s.comp_quality" type="number" min="1" max="100" />
                <span class="hint">{{ t('72 省 CPU / 80 均衡 / 88+ 高画质') }}</span>
              </div>
              <div class="field">
                <label>{{ t('最大宽度 px (0=不缩放)') }}</label>
                <input v-model.number="s.comp_max_width" type="number" min="0" />
              </div>
              <div class="field">
                <label>{{ t('webp 编码强度 (0-6)') }}</label>
                <input v-model.number="s.comp_method" type="number" min="0" max="6" />
                <span class="hint">{{ t('越高越慢越小；1 核机器建议 2') }}</span>
              </div>
              <div class="field">
                <label>{{ t('单图分辨率上限 (MP，0=不限)') }}</label>
                <input v-model.number="s.comp_max_pixels" type="number" min="0" />
                <span class="hint">{{ t('超过就拒绝上传，防止解码把内存打爆') }}</span>
              </div>
              <div class="field">
                <label>{{ t('压缩并发数 (1-8)') }}</label>
                <input v-model.number="s.comp_concurrency" type="number" min="1" max="8" />
                <span class="hint">{{ t('1 核机器填 1，别贪') }}</span>
              </div>
            </div>
          </template>

          <div class="row" style="margin-top:16px">
            <button :disabled="saveBusy" @click="save">{{ saveBusy ? t('保存中…') : t('保存并应用') }}</button>
            <span class="muted">{{ msg }}</span>
          </div>

          <h3>{{ t('支持的图片格式') }}</h3>
          <div class="table-scroll">
            <table class="user-table" style="margin-top:0">
              <thead><tr><th>{{ t('格式') }}</th><th>{{ t('建议') }}</th><th>{{ t('说明') }}</th></tr></thead>
              <tbody>
                <tr v-for="f in sys?.formats || []" :key="f.ext">
                  <td class="mono">{{ f.label }}</td>
                  <td><span class="rec" :class="{ no: !f.recommend }">{{ f.recommend ? t('推荐') : t('可用') }}</span></td>
                  <td class="muted" style="font-size:12px">{{ t(f.note) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="hint muted">
            {{ t('原图按上传格式保存；压缩版统一按上面的「压缩格式」输出（GIF 动图除外，只保留原图）。大批量导入时，超大图会按「分辨率上限」被挡下。') }}
          </p>
        </template>

        <!-- 访问统计 -->
        <template v-else-if="currentGroup()?.custom === 'stats'">
          <p class="muted">
            {{ t('记录所有 API 请求的 IP 与次数（静态图片不统计），数据只保留 3 天；IP 归属地查询结果缓存 7 天。') }}
          </p>
          <div class="row" style="margin:10px 0">
            <button class="ghost" :disabled="statsBusy" @click="loadStats">{{ t('刷新') }}</button>
            <span class="muted">{{ statsMsg }}</span>
          </div>
          <template v-if="stats">
            <div class="stats-cards">
              <div class="stat-card" v-for="d in stats.days" :key="d.day">
                <div class="stat-day">{{ d.day }}</div>
                <div class="stat-num">{{ d.pv }}</div>
                <div class="muted" style="font-size:12px">PV</div>
                <div class="stat-num">{{ d.uv }}</div>
                <div class="muted" style="font-size:12px">UV</div>
              </div>
              <div class="stat-card">
                <div class="stat-day">{{ t('今日上传') }}</div>
                <div class="stat-num">{{ stats.today.uploads }}</div>
                <div class="muted" style="font-size:12px">{{ fmtSize(stats.today.uploadBytes) }}</div>
                <div class="stat-num">{{ stats.yesterday.uploads }}</div>
                <div class="muted" style="font-size:12px">{{ t('昨日上传') }}</div>
              </div>
              <div class="stat-card">
                <div class="stat-day">{{ t('图库总量') }}</div>
                <div class="stat-num">{{ stats.library.count }}</div>
                <div class="muted" style="font-size:12px">{{ t('张') }}</div>
              </div>
            </div>

            <h3>{{ t('Top IP（请求数）') }}</h3>
            <div class="table-scroll">
              <table class="user-table" style="margin-top:0">
                <thead>
                  <tr><th>IP</th><th>{{ t('归属地') }}</th><th>{{ t('请求数') }}</th><th>{{ t('最近请求') }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="ip in stats.topIps" :key="ip.ip">
                    <td class="mono">{{ ip.ip }}</td>
                    <td>{{ t(ip.geo) || '…' }}</td>
                    <td>{{ ip.count }}</td>
                    <td class="mono muted" style="font-size:11.5px">{{ ip.last_at }}</td>
                  </tr>
                  <tr v-if="!stats.topIps.length"><td colspan="4" class="muted">{{ t('暂无数据') }}</td></tr>
                </tbody>
              </table>
            </div>

            <h3>{{ t('热门接口') }}</h3>
            <div class="table-scroll">
              <table class="user-table" style="margin-top:0">
                <thead><tr><th>{{ t('接口') }}</th><th>{{ t('请求数') }}</th></tr></thead>
                <tbody>
                  <tr v-for="p in stats.topPaths" :key="p.path">
                    <td class="mono" style="font-size:12px">{{ p.path }}</td>
                    <td>{{ p.count }}</td>
                  </tr>
                  <tr v-if="!stats.topPaths.length"><td colspan="2" class="muted">{{ t('暂无数据') }}</td></tr>
                </tbody>
              </table>
            </div>
          </template>
          <div v-else class="spinner"></div>
        </template>

        <!-- 通知 -->
        <template v-else-if="currentGroup()?.custom === 'notify'">
          <p class="muted" style="margin-top:0">
            {{ t('通过 Webhook 推送事件：限流告警、防爆破告警、管理员登录提醒，以及每日 / 每周 / 每月机器体检报告（PV、UV、上传数、图库总量）。兼容企业微信、钉钉、飞书、Telegram Bot 等自定义 Webhook。') }}
          </p>

          <div class="panel" style="margin-top:14px">
            <h3 class="panel-title">{{ t('连接') }}</h3>
            <div class="field-grid">
              <div class="field span-2">
                <label>Webhook URL</label>
                <input v-model="s.webhook_url" placeholder="https://..." />
              </div>
              <div class="field">
                <label>{{ t('请求方法') }}</label>
                <select v-model="s.notify_method">
                  <option value="POST">POST</option>
                  <option value="PUT">PUT</option>
                  <option value="GET">GET</option>
                </select>
              </div>
              <div class="field">
                <label>Body {{ t('格式') }}</label>
                <select v-model="s.notify_body_type">
                  <option value="json">JSON</option>
                  <option value="text">Text</option>
                </select>
              </div>
              <div class="field span-2">
                <label>{{ t('自定义请求头（JSON，可选）') }}</label>
                <textarea v-model="s.notify_headers" rows="2" class="mono" spellcheck="false"
                  placeholder='{"Authorization": "Bearer xxx"}'></textarea>
              </div>
              <div class="field span-2">
                <label>{{ t('请求体模板（可选；留空 = 默认 JSON）') }}</label>
                <textarea v-model="s.notify_body_tpl" rows="3" class="mono" spellcheck="false"
                  placeholder='{"title": "{{event}}", "content": "{{message}}"}'
                  style="font-size:12px"></textarea>
                <span class="hint">{{ tplHint }}</span>
              </div>
            </div>
            <div class="row" style="margin:12px 0 0">
              <button class="ghost" :disabled="notifyBusy" @click="sendTestNotify">
                {{ notifyBusy ? t('发送中…') : t('发送测试') }}
              </button>
              <span class="msg-line" :class="{ bad: notifyOk === false }">{{ notifyMsg }}</span>
            </div>
          </div>

          <div class="panel">
            <h3 class="panel-title">{{ t('事件订阅') }}</h3>
            <div class="notify-grid">
              <div class="switch-card" :class="{ on: s.notify_admin_login === '1' }">
                <label class="sc-main">
                  <input type="checkbox" :checked="s.notify_admin_login === '1'"
                    @change="switchField('notify_admin_login', $event.target.checked)" />
                  <span class="sc-body">
                    <span class="sc-title">{{ t('管理员登录通知') }}</span>
                    <span class="sc-desc">{{ t('有人用管理员账号登录时推送一条消息') }}</span>
                  </span>
                </label>
              </div>

              <div class="switch-card" :class="{ on: s.notify_daily === '1' }">
                <label class="sc-main">
                  <input type="checkbox" :checked="s.notify_daily === '1'"
                    @change="switchField('notify_daily', $event.target.checked)" />
                  <span class="sc-body">
                    <span class="sc-title">{{ t('每日汇报') }}</span>
                    <span class="sc-desc">{{ t('今日 PV / UV / 上传数 / 图库总量') }}</span>
                  </span>
                </label>
                <div class="sc-extra" v-if="s.notify_daily === '1'">
                  <span>{{ t('汇报时间') }}</span>
                  <input v-model="s.notify_daily_time" type="time" />
                </div>
              </div>

              <div class="switch-card" :class="{ on: s.notify_weekly === '1' }">
                <label class="sc-main">
                  <input type="checkbox" :checked="s.notify_weekly === '1'"
                    @change="switchField('notify_weekly', $event.target.checked)" />
                  <span class="sc-body">
                    <span class="sc-title">{{ t('每周周报') }}</span>
                    <span class="sc-desc">{{ t('每周一发送，近 7 天汇总') }}</span>
                  </span>
                </label>
              </div>

              <div class="switch-card" :class="{ on: s.notify_monthly === '1' }">
                <label class="sc-main">
                  <input type="checkbox" :checked="s.notify_monthly === '1'"
                    @change="switchField('notify_monthly', $event.target.checked)" />
                  <span class="sc-body">
                    <span class="sc-title">{{ t('每月月报') }}</span>
                    <span class="sc-desc">{{ t('每月 1 号发送，近 30 天汇总') }}</span>
                  </span>
                </label>
              </div>
            </div>
            <p class="hint muted" style="margin-bottom:0">{{ t('汇报时间使用服务器时区，格式 HH:MM。') }}</p>
          </div>

          <div class="row sticky-actions">
            <button :disabled="saveBusy" @click="save">{{ saveBusy ? t('保存中…') : t('保存全部设置') }}</button>
            <span class="msg-line" :class="{ bad: msgBad }">{{ msg }}</span>
          </div>
        </template>

        <!-- 本地图库导入 / 补压缩 -->
        <template v-else-if="currentGroup()?.custom === 'local'">
          <p class="muted">
            {{ t('把图片直接放进数据目录的') }} <code>uploads/</code>（{{ t('Docker 部署为') }} <code>/data/uploads</code>），
            {{ t('这里可以扫描入库 —— 原文件路径不变，归属') }}<strong>{{ t('管理员') }}</strong>；
            {{ t('入库时自动按当前「压缩方案」生成缩略图与压缩版。') }}
          </p>

          <div class="panel">
            <h3 style="font-size:14px">{{ t('扫描本地原图') }}</h3>
            <p class="muted" style="margin-top:0">{{ localMsg || t('尚未扫描') }}</p>
            <div class="row" style="margin:0">
              <button class="ghost" :disabled="localBusy" @click="previewLocal">{{ t('重新扫描') }}</button>
              <label class="muted" style="display:flex;align-items:center;gap:6px">
                {{ t('每次导入') }}
                <input v-model.number="importLimit" type="number" min="1" max="200"
                  style="width:76px" /> {{ t('张') }}
              </label>
              <button :disabled="localBusy || !localInfo?.pendingCount" @click="doImport">
                {{ t('导入') }} {{ Math.min(importLimit, localInfo?.pendingCount || 0) }} {{ t('张') }}
              </button>
            </div>

            <div v-if="localInfo?.pending?.length" class="table-scroll" style="margin-top:12px">
              <table class="user-table">
                <thead>
                  <tr><th>{{ t('待导入文件') }}</th><th>{{ t('尺寸') }}</th><th>{{ t('大小') }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="p in localInfo.pending" :key="p.key">
                    <td class="mono" style="font-size:12px">{{ p.key }}</td>
                    <td>{{ p.width }}×{{ p.height }}</td>
                    <td>{{ fmtSize(p.size) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="hint muted" v-if="localInfo?.pendingCount > localInfo?.pending?.length">
              {{ t('仅显示前') }} {{ localInfo.pending.length }} {{ t('条，共') }} {{ localInfo.pendingCount }} {{ t('张待导入。') }}
            </p>

            <details v-if="localInfo?.invalid?.length" style="margin-top:10px">
              <summary class="muted" style="cursor:pointer;font-size:12.5px">
                {{ t('忽略的') }} {{ localInfo.invalidCount }} {{ t('个文件（非图片 / 无法解析）') }}
              </summary>
              <div v-for="p in localInfo.invalid" :key="p.key" class="mono muted" style="font-size:11.5px">
                {{ p.key }} — {{ t(p.error) }}
              </div>
            </details>
          </div>

          <div class="panel">
            <h3 style="font-size:14px">{{ t('补齐压缩版') }}</h3>
            <p class="muted" style="margin-top:0">
              {{ compMsg || t('尚未检查') }}
              <template v-if="compInfo?.settings">
                · {{ t(compInfo.settings.label) || compInfo.settings.profile }} ·
                {{ compInfo.settings.format }} / {{ t('质量') }} {{ compInfo.settings.quality }}
                / {{ t('最大宽') }} {{ compInfo.settings.maxWidth || t('不限') }}px
              </template>
            </p>
            <div class="row" style="margin:0">
              <button class="ghost" :disabled="compBusy" @click="previewCompress">{{ t('检查') }}</button>
              <label class="muted" style="display:flex;align-items:center;gap:6px">
                {{ t('每次处理') }}
                <input v-model.number="compLimit" type="number" min="1" max="50"
                  style="width:76px" /> {{ t('张') }}
              </label>
              <button :disabled="compBusy || !compInfo?.todoCount" @click="runCompress">
                {{ t('开始补') }} {{ Math.min(compLimit, compInfo?.todoCount || 0) }} {{ t('张') }}
              </button>
            </div>
            <p class="hint muted">
              {{ t('压缩吃 CPU。低配 VPS（1 核 1G）建议每次 3~5 张，点几次把积压清完；单张通常 0.3~2 秒，具体取决于原图分辨率。') }}
            </p>
            <div v-if="compInfo?.items?.length" style="margin-top:8px">
              <div v-for="i in compInfo.items" :key="i.key" class="mono muted" style="font-size:11.5px">
                {{ i.filename }} · {{ fmtSize(i.size) }}
                <span v-if="i.compressed">· {{ t('缺压缩版') }}</span>
                <span v-if="i.thumb">· {{ t('缺缩略图') }}</span>
              </div>
            </div>
          </div>
        </template>

        <!-- API 文档 -->
        <template v-else-if="currentGroup()?.custom === 'apidoc'">
          <p class="muted">
            {{ t('鉴权统一用') }} <code>Authorization: Bearer &lt;token&gt;</code>。token {{ t('来自登录接口') }}。
          </p>

          <h3>{{ t('公开接口（游客）') }}</h3>
          <pre>GET /api/public/settings
  → { site_title, site_icon, site_tags, site_footer, random_public,
      share_base_url, upload_default_tags, token_login }

GET /api/tags
  → { tags: [{ name, count }] }

GET /api/images?page=1&amp;limit=24&amp;sort=latest|random[&amp;tag=xxx][&amp;mine=1]
  → { items: [...], page, limit, total, hasMore }
  item: { id, key, url, thumb, compressed, width, height, mimeType, size,
          compressedSize, createdAt, tag, filename, origName,
          ownerId, owner, mine, canEdit }
  mine=1 {{ t('需登录，只返回自己上传的图') }}</pre>

          <h3>{{ t('账号') }}</h3>
          <pre>POST /api/auth/login     {"username":"admin","password":"***","remember":true}
  → { token, remember, expiresAt, user: { id, username, role, quotaMb,
      usedBytes, remainingBytes, imageCount, maxUploadMb, ... } }
POST /api/auth/logout    {{ t('注销当前 token') }}
GET  /api/auth/me        {{ t('当前用户 + 用量') }}
POST /api/auth/password  {"old":"***","new":"***"}</pre>

          <h3>{{ t('随机图（默认需登录；后台可开放为公开）') }}</h3>
          <pre>GET /api/random?variant=compressed|original[&amp;redirect=true]
GET /api/random/image?variant=compressed|original   # 302 {{ t('直链') }}</pre>

          <h3>{{ t('图片（登录）') }}</h3>
          <pre>POST   /api/upload        multipart: files=@a.png&amp;tag=xxx
PATCH  /api/images/{id}   {"filename":"newname"}  {{ t('重命名（原图/压缩/缩略图同步）') }}
                          {"tag":"landscape"}          {{ t('改标签') }}
DELETE /api/images/{id}   {{ t('删原图 + 压缩图 + 缩略图') }}
  {{ t('权限：管理员可操作全部；普通用户仅限自己上传的图') }}</pre>

          <h3>{{ t('用户管理（管理员）') }}</h3>
          <pre>GET    /api/users                {{ t('用户列表（含 used / count / day_count / remainingBytes）') }}
POST   /api/users                {"username","password","role","quota_mb",
                                  "max_upload_mb","daily_limit","weekly_limit",
                                  "monthly_limit","comp_format","comp_quality"}
                                  {{ t('缺省额度取后台「上传限制 → 新用户默认值」') }}
PATCH  /api/users/{id}           {{ t('改配额 / 上传张数 / 压缩覆盖 / 角色 / 密码 / 启用') }}
DELETE /api/users/{id}?purge=false   {{ t('删用户（默认图片转交管理员）') }}

{{ t('上传校验顺序：单图大小 → 日/周/月张数 → 容量配额 → 分辨率上限（压缩方案）') }}
{{ t('管理员（role=admin）不受单图/张数/配额限制') }}</pre>

          <h3>{{ t('压缩方案 / 设置（管理员）') }}</h3>
          <pre>GET  /api/admin/system
  → { perf: { mode, profile, autoProfile, label, detected:{cores,memMb},
              format, quality, maxWidth, method, maxPixels, concurrency },
      profiles: [...], formats: [...], pool: { limit, active } }

PUT  /api/admin/settings   {"comp_profile":"auto|tiny|small|normal|custom",
                            "comp_format":"webp|jpeg|png","comp_quality":80,
                            "upload_max_mb":5,
                            "new_user_quota_mb":500,"new_user_max_upload_mb":5,
                            "new_user_daily":30,"new_user_weekly":100,
                            "new_user_monthly":250,
                            "rate_limit":120,"session_hours":12}

GET  /api/admin/stats         {{ t('访问统计（3 天 PV/UV、Top IP+归属地、热门接口）') }}
GET  /api/admin/bans          {{ t('当前封禁列表') }}
POST /api/admin/notify/test   {{ t('按「通知」配置发一条测试消息') }}
{{ t('通知配置字段：') }}
  webhook_url, notify_method(POST/PUT/GET), notify_body_type(json/text),
  notify_headers(JSON), notify_body_tpl({{ t('模板') }}),
  notify_admin_login, notify_daily, notify_daily_time,
  notify_weekly, notify_monthly</pre>

          <h3>{{ t('本地图库（管理员）') }}</h3>
          <pre>GET  /api/admin/local/scan?dry_run=true&amp;limit=50
POST /api/admin/local/compress?dry_run=true&amp;limit=5
POST /api/admin/reindex    v4 {{ t('兼容别名，等价于全量扫描导入') }}</pre>

          <h3>{{ t('用法示例') }}</h3>
          <pre># {{ t('登录拿 token') }}
curl -X POST -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"***","remember":true}' \
     http://your-host/api/auth/login

# {{ t('上传（带标签）') }}
curl -H "Authorization: Bearer $TOKEN" \
     -F "files=@pic.jpg" -F "tag=wallpaper" http://your-host/api/upload

# {{ t('随机压缩图直链（开放公开后可直接用于 Markdown）') }}
![random](https://your-host/api/random/image?variant=compressed)</pre>

          <h3>{{ t('防御机制') }}</h3>
          <p>
            {{ t('随机图接口每 IP 每分钟限流（后台可调），超限 → webhook 通知 + 封禁；登录失败 10 分钟内累计超阈值 → 封禁（防爆破）；所有静态文件路径由框架白名单伺服，无目录遍历面；图片 URL 一年期 immutable 缓存，重复访问不耗流量。') }}
          </p>
        </template>

        <!-- 用户管理 -->
        <template v-else-if="currentGroup()?.custom === 'users'">
          <div class="panel" style="margin-top:0">
            <h3 style="font-size:14px">{{ editing ? t('编辑用户') : t('新建用户') }}</h3>
            <div class="user-form">
              <div class="field">
                <label>{{ t('用户名') }}</label>
                <input v-model="form.username" placeholder="3-32 _ - ." />
              </div>
              <div class="field">
                <label>{{ editing ? t('重置密码（留空不改）') : t('密码') }}</label>
                <input v-model="form.password" type="password" :placeholder="t('至少 6 位')" />
              </div>
              <div class="field">
                <label>{{ t('角色') }}</label>
                <select v-model="form.role">
                  <option value="user">{{ t('普通用户') }}</option>
                  <option value="admin">{{ t('管理员') }}</option>
                </select>
              </div>
              <div class="field">
                <label>{{ t('容量配额 (MB，0=不限)') }}</label>
                <input v-model.number="form.quota_mb" type="number" min="0" />
              </div>
              <div class="field">
                <label>{{ t('单图上限 (MB，0=跟随全局)') }}</label>
                <input v-model.number="form.max_upload_mb" type="number" min="0" />
              </div>
              <div class="field">
                <label>{{ t('每日上传张数 (0=不限)') }}</label>
                <input v-model.number="form.daily_limit" type="number" min="0" />
              </div>
              <div class="field">
                <label>{{ t('每周上传张数 (0=不限)') }}</label>
                <input v-model.number="form.weekly_limit" type="number" min="0" />
              </div>
              <div class="field">
                <label>{{ t('每月上传张数 (0=不限)') }}</label>
                <input v-model.number="form.monthly_limit" type="number" min="0" />
              </div>
              <div class="field">
                <label>{{ t('压缩格式覆盖') }}</label>
                <select v-model="form.comp_format">
                  <option value="">{{ t('跟随全局') }}</option>
                  <option value="webp">webp</option>
                  <option value="jpeg">jpeg</option>
                  <option value="png">png</option>
                </select>
              </div>
              <div class="field">
                <label>{{ t('压缩质量覆盖 (1-100，空=全局)') }}</label>
                <input v-model="form.comp_quality" type="number" min="1" max="100" :placeholder="t('跟随全局')" />
              </div>
            </div>
            <div class="row">
              <button @click="submitUser">{{ editing ? t('保存修改') : t('创建用户') }}</button>
              <button class="ghost" v-if="editing" @click="resetForm">{{ t('取消编辑') }}</button>
              <span class="muted">{{ uMsg }}</span>
            </div>
          </div>

          <div class="table-scroll">
          <table class="user-table">
            <thead>
              <tr>
                <th>{{ t('用户') }}</th><th>{{ t('角色') }}</th><th>{{ t('用量 / 配额') }}</th><th>{{ t('上传限制') }}</th><th>{{ t('压缩参数') }}</th><th>{{ t('状态') }}</th><th>{{ t('操作') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in users" :key="u.id" :class="{ off: !u.enabled }">
                <td>
                  <b>{{ u.username }}</b>
                  <div class="mono muted" style="font-size:11px">{{ u.id }}</div>
                </td>
                <td>
                  <span class="role-badge" :class="{ user: u.role !== 'admin' }">
                    {{ u.role === 'admin' ? t('管理员') : t('用户') }}
                  </span>
                </td>
                <td>
                  {{ fmtSize(u.used) }} / {{ u.quota_mb ? u.quota_mb + ' MB' : t('不限') }}
                  <div class="muted" style="font-size:11.5px">{{ u.count }} {{ t('张') }}</div>
                </td>
                <td style="font-size:12px">
                  <div>{{ t('单图') }} {{ u.max_upload_mb ? u.max_upload_mb + ' MB' : t('全局') }}</div>
                  <div class="muted" style="font-size:11.5px">
                    {{ t('日') }} {{ u.day_count }}/{{ u.daily_limit || '∞' }} ·
                    {{ t('周') }} {{ u.week_count }}/{{ u.weekly_limit || '∞' }} ·
                    {{ t('月') }} {{ u.month_count }}/{{ u.monthly_limit || '∞' }}
                  </div>
                </td>
                <td class="mono" style="font-size:11.5px">
                  {{ u.comp_format || t('全局') }} ·
                  {{ u.comp_quality ?? t('全局') }}
                </td>
                <td>{{ u.enabled ? t('正常') : t('已停用') }}</td>
                <td class="row" style="margin:0;gap:6px">
                  <button class="ghost sm" @click="editUser(u)">{{ t('编辑') }}</button>
                  <button class="ghost sm" @click="toggleEnabled(u)">{{ u.enabled ? t('停用') : t('启用') }}</button>
                  <button class="ghost sm danger" v-if="u.id !== store.user.id" @click="removeUser(u)">{{ t('删除') }}</button>
                </td>
              </tr>
            </tbody>
          </table>
          </div>
          <p class="hint muted">{{ t('删除用户时其图片会转交给管理员（不丢图）。') }}</p>
        </template>

        <!-- 普通配置组 -->
        <template v-else>
          <div class="field-grid">
            <template v-for="f in currentGroup()?.fields" :key="f.k">
              <div class="field" v-if="f.type !== 'switch'" :class="{ 'span-2': f.type !== 'number' }">
                <label>{{ t(f.label) }}</label>
                <select v-if="f.type === 'select'" v-model="s[f.k]">
                  <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                </select>
                <input v-else-if="f.type === 'number'" type="number" v-model.number="s[f.k]" />
                <input v-else v-model="s[f.k]" />
                <span class="hint" v-if="f.hint">{{ t(f.hint) }}</span>
              </div>
              <div class="field span-2" v-else>
                <label class="check-line">
                  <input type="checkbox" :checked="s[f.k] === '1'"
                    @change="s[f.k] = $event.target.checked ? '1' : '0'" /> {{ t(f.label) }}
                </label>
                <span class="hint" v-if="f.hint">{{ t(f.hint) }}</span>
              </div>
            </template>
          </div>
          <p class="hint muted" v-if="currentGroup()?.hint">{{ t(currentGroup().hint) }}</p>

          <div class="row sticky-actions">
            <button :disabled="saveBusy" @click="save">{{ saveBusy ? t('保存中…') : t('保存全部设置') }}</button>
            <button class="ghost" @click="loadBans">{{ t('刷新封禁列表') }}</button>
            <span class="msg-line" :class="{ bad: msgBad }">{{ msg }}</span>
          </div>

          <div v-if="bans.length" class="panel" style="margin-top:16px">
            <h3>{{ t('当前封禁') }}</h3>
            <div v-for="b in bans" :key="b.ip" class="mono muted">
              {{ b.ip }} · {{ b.reason }} · {{ b.until }}
            </div>
          </div>
        </template>
      </section>
    </div>
    <div v-else class="spinner"></div>
  </template>

  <!-- 全局操作提示：保存/测试等动作的即时反馈 -->
  <div v-if="toastText" class="admin-toast" :class="{ bad: !toastOk }">{{ toastText }}</div>
</template>
