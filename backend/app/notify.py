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
import urllib.request
from datetime import datetime, timedelta, timezone

from . import db


def render(tpl: str, ctx: dict) -> str:
    out = tpl
    for k, v in ctx.items():
        out = out.replace("{{" + k + "}}", str(v))
    # 事件没带的变量（如 {{ip}}）不留原始占位符
    return re.sub(r"\{\{\w+\}\}", "", out)


def send(event: str, message: str, extra: dict | None = None) -> tuple[bool, str]:
    """按后台「通知」配置投递一条 webhook。返回 (ok, 错误信息)。"""
    s = db.get_settings()
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
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        **(extra or {}),
    }
    headers = {"Content-Type": "application/json"}
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
        data = message.encode()
        headers["Content-Type"] = "text/plain"
    else:
        data = json.dumps(ctx, ensure_ascii=False).encode()
    try:
        req = urllib.request.Request(url, data=None if method == "GET" else data,
                                     headers=headers, method=method)
        # 本机/局域网目标绕过系统代理（沙箱/公司代理常不放行内网地址）
        host = url.split("/")[2].split(":")[0]
        if host in ("127.0.0.1", "localhost", "::1") or host.startswith("192.168.") \
                or host.startswith("10."):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            resp = opener.open(req, timeout=8)
        else:
            resp = urllib.request.urlopen(req, timeout=8)
        with resp:
            resp.read(65536)
        return True, ""
    except Exception as e:
        return False, str(e)


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
