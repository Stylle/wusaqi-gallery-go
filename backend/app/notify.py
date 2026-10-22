"""通知中心：Webhook 投递（方法/请求头/请求体模板可配）+ 定时日报/周报/月报。

形态参考主流监控面板的通知配置：
  - Webhook URL / 请求方法 / Body 格式（json|text）
  - 自定义请求头（JSON）
  - 请求体模板：支持 {{event}} {{message}} {{time}} {{site}} 及事件附加字段
  - 事件：限流告警 / 防爆破告警 / 管理员登录 / 每日汇报 / 周报 / 月报 / 测试
汇报由后台线程按服务器本地时间触发，settings 表记 last_sent 防重发。
"""
import json
import re
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import db

# 不少 Webhook 服务（含 Cloudflare/WAF 前置）会直接 403 掉 Python-urllib 的默认 UA，
# 这里默认伪装成普通浏览器；后台「自定义请求头」里可以覆盖。
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 lolis-gallery/1.0")


# 事件 → 开关键（None = 总是发送）
EVENT_SWITCH = {
    "admin_login": "notify_admin_login",
    "rate_limit": "notify_security",
    "auth_brute_force": "notify_security",
    "manual_ban": "notify_ban",
    "manual_unban": "notify_ban",
    "restore": "notify_restore",
    "test": None,
}

# 事件 → (emoji, 标题)
EVENT_META = {
    "test": ("🔔", "测试通知"),
    "admin_login": ("🔐", "管理员登录"),
    "rate_limit": ("⚠️", "随机图接口触发限流"),
    "auth_brute_force": ("🛡️", "疑似暴力破解，已封禁"),
    "manual_ban": ("🚫", "手动封禁 IP"),
    "manual_unban": ("✅", "解除封禁"),
    "restore": ("💾", "从备份恢复了站点数据"),
    "daily_report": ("📊", "每日汇报"),
    "weekly_report": ("📊", "每周报告"),
    "monthly_report": ("📊", "每月报告"),
}

FIELD_LABELS = {
    "ip": "IP", "geo": "归属地", "reason": "原因", "minutes": "封禁时长",
    "ban_minutes": "封禁时长", "until": "解封时间", "operator": "操作人",
    "username": "账号", "fails": "失败次数", "path": "接口",
    "limit_per_minute": "限流阈值", "images": "图片数", "files": "文件数",
    "ua": "User-Agent", "role": "角色",
}


_geo_resolver = None


def set_geo_resolver(fn) -> None:
    """注入 IP 归属地查询函数（main.geo_lookup），投递时在后台线程补全。"""
    global _geo_resolver
    _geo_resolver = fn


def _fill_geo(ctx: dict) -> None:
    if _geo_resolver and ctx.get("ip") and not ctx.get("geo"):
        try:
            ctx["geo"] = _geo_resolver(str(ctx["ip"]))
        except Exception:
            pass


def is_enabled(event: str, s: dict | None = None) -> bool:
    """该事件是否被后台开关允许投递（test 始终允许）。"""
    key = EVENT_SWITCH.get(event)
    if key is None:
        return True
    s = s or db.get_settings()
    return s.get(key) == "1"


def event_title(event: str) -> str:
    emoji, title = EVENT_META.get(event, ("🔔", event))
    return f"{emoji} {title}"


def _fmt_minutes(v) -> str:
    try:
        m = int(v)
    except (TypeError, ValueError):
        return str(v)
    if m >= 24 * 60 and m % (24 * 60) == 0:
        return f"{m // (24 * 60)} 天"
    if m >= 60 and m % 60 == 0:
        return f"{m // 60} 小时"
    return f"{m} 分钟"


def build_text(event: str, ctx: dict) -> str:
    """把事件字段拼成可读的多行消息（不止一句字符）。"""
    title = event_title(event)
    lines = [title, ""]
    if ctx.get("site"):
        lines.append(f"· 站点：{ctx['site']}")
    if ctx.get("time"):
        lines.append(f"· 时间：{ctx['time']}")
    msg = (ctx.get("message") or "").strip()
    # message 若以标题开头（如定时汇报自带标题），去掉重复的标题；
    # 若与事件名相同（历史调用遗留），说明为空，直接丢弃，避免把内部事件名暴露给用户。
    if msg.startswith(title):
        msg = msg[len(title):].strip()
    if msg == event:
        msg = ""
    if msg:
        for i, ln in enumerate(msg.splitlines()):
            lines.append(f"· 说明：{ln}" if i == 0 else f"  {ln}")
    for k, v in ctx.items():
        if k in ("site", "time", "message", "event", "title", "text", "fields"):
            continue
        if v is None or v == "":
            continue
        label = FIELD_LABELS.get(k, k)
        val = _fmt_minutes(v) if k in ("minutes", "ban_minutes") else str(v)
        lines.append(f"· {label}：{val}")
    return "\n".join(lines)


def render(tpl: str, ctx: dict) -> str:
    out = tpl
    for k, v in ctx.items():
        out = out.replace("{{" + k + "}}", str(v))
    # 事件没带的变量（如 {{ip}}）不留原始占位符
    return re.sub(r"\{\{\w+\}\}", "", out)


def send(event: str, message: str, extra: dict | None = None) -> tuple[bool, str]:
    """按后台「通知」配置投递一条 webhook。返回 (ok, 错误信息)。"""
    s = db.get_settings()
    if not is_enabled(event, s):
        return True, ""            # 开关关闭：静默跳过（不算失败）
    url = (s.get("webhook_url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return False, "未配置 Webhook URL"
    method = s.get("notify_method", "POST")
    method = method if method in ("POST", "PUT", "GET") else "POST"
    body_type = s.get("notify_body_type", "json")
    ctx = {
        "site": s.get("site_title", "lolis-gallery"),
        "event": event,
        "message": message,
        "time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "title": event_title(event),
        **(extra or {}),
    }
    _fill_geo(ctx)
    ctx["text"] = build_text(event, ctx)
    ctx["fields"] = json.dumps(extra or {}, ensure_ascii=False)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": DEFAULT_UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    custom = (s.get("notify_headers") or "").strip()
    if custom:
        try:
            for k, v in json.loads(custom).items():
                headers[str(k)] = str(v)
        except Exception:
            return False, "自定义请求头不是合法的 JSON 对象"
    tpl = (s.get("notify_body_tpl") or "").strip()
    if tpl:
        data = render(tpl, ctx).encode()
    elif body_type == "text":
        data = ctx["text"].encode()
        headers["Content-Type"] = "text/plain; charset=utf-8"
    else:
        data = json.dumps(ctx, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=None if method == "GET" else data,
                                 headers=headers, method=method)
    # 先直连：内网/本机目标不能被系统代理拦；外网目标直连失败再退回系统代理
    ok, err = _open(req, direct=True)
    if ok:
        return True, ""
    if urllib.request.getproxies():
        ok2, err2 = _open(req, direct=False)
        if ok2:
            return True, ""
        err = err if "HTTP" in err else f"{err} / 代理：{err2}"
    return False, err


def _open(req, direct: bool) -> tuple[bool, str]:
    """发一次请求；返回 (ok, 人类可读的错误)。"""
    try:
        if direct:
            resp = urllib.request.build_opener(
                urllib.request.ProxyHandler({})).open(req, timeout=8)
        else:
            resp = urllib.request.urlopen(req, timeout=8)
        with resp:
            resp.read(65536)
        return True, ""
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(2048).decode("utf-8", "replace")
            body = re.sub(r"\s+", " ", body).strip()[:300]
        except Exception:
            pass
        hint = ""
        if e.code in (401, 403):
            hint = "（目标拒绝：密钥/签名无效，或被对方 WAF 拦截）"
        msg = f"HTTP {e.code} {e.reason}{hint}"
        if body:
            msg += f" · 响应：{body}"
        return False, msg
    except urllib.error.URLError as e:
        return False, f"网络错误：{e.reason}"
    except Exception as e:  # 超时、证书等
        return False, f"{type(e).__name__}: {e}"


def fire(event: str, message: str, extra: dict | None = None) -> None:
    """异步尽力投递，失败不影响主流程。"""
    def _post():
        try:
            send(event, message, extra)
        except Exception:
            pass
    threading.Thread(target=_post, daemon=True).start()


# ---------- 定时汇报 ----------

def _since_iso(days: int) -> str:
    """本地 days 天前 0 点对应的 UTC ISO（images.created_at 存 UTC）。"""
    midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    return midnight.astimezone(timezone.utc).isoformat(timespec="seconds")


def _period_stats(days: int) -> str:
    v = db.stats_summary(days)
    up = db.uploads_since(_since_iso(days))
    total = db.get_conn().execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS b FROM images").fetchone()
    lines = [f"访问：PV {v['pv']} · UV {v['uv']}",
             f"上传：{up['count']} 张（{up['bytes'] / 1048576:.1f} MB）",
             f"图库总量：{total['n']} 张（{total['b'] / 1048576:.1f} MB）"]
    return "\n".join(lines)


def _send_report(kind: str) -> None:
    days = {"day": 1, "week": 7, "month": 30}[kind]
    title = {"day": "📊 每日汇报", "week": "📊 每周报告", "month": "📊 每月报告"}[kind]
    event = {"day": "daily_report", "week": "weekly_report", "month": "monthly_report"}[kind]
    send(event, f"{title}\n{_period_stats(days)}")


def report_worker():
    """后台线程：每 30 秒检查一次是否到汇报时间（用 settings 记 last_sent 防重发）。"""
    while True:
        try:
            s = db.get_settings()
            if (s.get("webhook_url") or "").strip():
                now = datetime.now().astimezone()
                today = now.strftime("%Y-%m-%d")
                target = (s.get("notify_daily_time") or "09:00").strip()
                if s.get("notify_daily") == "1" and now.strftime("%H:%M") >= target \
                        and s.get("notify_last_daily") != today:
                    _send_report("day")
                    db.update_settings({"notify_last_daily": today})
                if s.get("notify_weekly") == "1" and now.weekday() == 0 \
                        and s.get("notify_last_week") != today:
                    _send_report("week")
                    db.update_settings({"notify_last_week": today})
                if s.get("notify_monthly") == "1" and now.day == 1 \
                        and s.get("notify_last_month") != today:
                    _send_report("month")
                    db.update_settings({"notify_last_month": today})
        except Exception:
            traceback.print_exc()
        time.sleep(30)
