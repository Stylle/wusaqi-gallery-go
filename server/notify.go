package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"time"
)

type notification struct {
	event, message string
	fields         M
}

var eventTitles = map[string]string{"test": "🔔 测试通知", "admin_login": "🔐 管理员登录", "rate_limit": "⚠️ 随机图接口触发限流", "auth_brute_force": "🛡️ 疑似暴力破解，已封禁", "manual_ban": "🚫 手动封禁 IP", "manual_unban": "✅ 解除封禁", "restore": "💾 从备份恢复了站点数据", "daily_report": "📊 每日汇报", "weekly_report": "📊 每周报告", "monthly_report": "📊 每月报告"}
var eventSwitch = map[string]string{"admin_login": "notify_admin_login", "rate_limit": "notify_security", "auth_brute_force": "notify_security", "manual_ban": "notify_ban", "manual_unban": "notify_ban", "restore": "notify_restore"}

func (a *App) fire(event, message string, fields M) {
	s := a.settings()
	if s["webhook_url"] == "" {
		return
	}
	if k := eventSwitch[event]; k != "" && s[k] != "1" {
		return
	}
	select {
	case a.notifications <- notification{event, message, fields}:
	default:
		log.Print("notification queue full; event dropped: " + event)
	}
}

var templateVar = regexp.MustCompile(`\{\{\w+\}\}`)

// Substitute JSON templates without turning quotes or multiline notification
// text into invalid JSON. {{fields}} also works as an unquoted JSON object.
func renderNotifyJSON(tpl string, ctx M) ([]byte, error) {
	var out strings.Builder
	quoted, escaped := false, false
	for i := 0; i < len(tpl); {
		if strings.HasPrefix(tpl[i:], "{{") {
			if match := templateVar.FindStringIndex(tpl[i:]); match != nil && match[0] == 0 {
				key := tpl[i+2 : i+match[1]-2]
				value, found := ctx[key]
				if quoted {
					b, _ := json.Marshal(str(value))
					out.Write(b[1 : len(b)-1])
				} else if !found {
					out.WriteString("null")
				} else if key == "fields" && json.Valid([]byte(str(value))) {
					out.WriteString(str(value))
				} else {
					b, e := json.Marshal(value)
					if e != nil {
						return nil, e
					}
					out.Write(b)
				}
				i += match[1]
				continue
			}
		}
		c := tpl[i]
		out.WriteByte(c)
		if escaped {
			escaped = false
		} else if quoted && c == '\\' {
			escaped = true
		} else if c == '"' {
			quoted = !quoted
		}
		i++
	}
	result := []byte(out.String())
	if !json.Valid(result) {
		return nil, fmt.Errorf("请求体模板不是合法 JSON，请检查模板或选择 Text 格式")
	}
	return result, nil
}

func (a *App) sendNotify(n notification) (bool, string) {
	s := a.settings()
	if k := eventSwitch[n.event]; k != "" && s[k] != "1" {
		return true, ""
	}
	url := strings.TrimSpace(s["webhook_url"])
	if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
		return false, "未配置 Webhook URL"
	}
	ctx := M{"site": s["site_title"], "event": n.event, "message": n.message, "time": time.Now().Format("2006-01-02 15:04:05"), "title": eventTitles[n.event]}
	for k, v := range n.fields {
		ctx[k] = v
	}
	if ip := str(ctx["ip"]); ip != "" && str(ctx["geo"]) == "" {
		ctx["geo"] = a.geo(ip)
	}
	lines := []string{str(ctx["title"]), "", "· 站点：" + s["site_title"], "· 时间：" + str(ctx["time"])}
	if n.message != "" {
		lines = append(lines, "· 说明："+n.message)
	}
	labels := map[string]string{"ip": "IP", "geo": "归属地", "reason": "原因", "minutes": "封禁时长", "ban_minutes": "封禁时长", "until": "解封时间", "operator": "操作人", "username": "账号", "fails": "失败次数", "path": "接口", "limit_per_minute": "限流阈值", "images": "图片数", "files": "文件数", "ua": "User-Agent", "role": "角色"}
	keys := []string{}
	for k := range n.fields {
		keys = append(keys, k)
	}
	if ctx["geo"] != nil && n.fields["geo"] == nil {
		keys = append(keys, "geo")
	}
	sort.Strings(keys)
	for _, k := range keys {
		label := labels[k]
		if label == "" {
			label = k
		}
		v := str(ctx[k])
		if k == "minutes" || k == "ban_minutes" {
			v += " 分钟"
		}
		if v != "" {
			lines = append(lines, "· "+label+"："+v)
		}
	}
	ctx["text"] = strings.Join(lines, "\n")
	fields, _ := json.Marshal(n.fields)
	ctx["fields"] = string(fields)
	payload, e := json.Marshal(ctx)
	if e != nil {
		return false, e.Error()
	}
	content := "application/json"
	if s["notify_body_type"] == "text" {
		payload = []byte(str(ctx["text"]))
		content = "text/plain; charset=utf-8"
	}
	if tpl := s["notify_body_tpl"]; tpl != "" {
		if s["notify_body_type"] == "json" {
			payload, e = renderNotifyJSON(tpl, ctx)
			if e != nil {
				return false, e.Error()
			}
		} else {
			for k, v := range ctx {
				tpl = strings.ReplaceAll(tpl, "{{"+k+"}}", str(v))
			}
			payload = []byte(templateVar.ReplaceAllString(tpl, ""))
		}
	}
	method := s["notify_method"]
	var b io.Reader = bytes.NewReader(payload)
	if method == "GET" {
		b = nil
	}
	req, e := http.NewRequest(method, url, b)
	if e != nil {
		return false, e.Error()
	}
	req.Header.Set("Content-Type", content)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 wusaqi-gallery/1.0")
	req.Header.Set("Accept", "*/*")
	req.Header.Set("Accept-Language", "zh-CN,zh;q=0.9")
	headers := map[string]string{}
	if raw := s["notify_headers"]; raw != "" {
		if e = json.Unmarshal([]byte(raw), &headers); e != nil {
			return false, "自定义请求头不是合法的 JSON 对象"
		}
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, e := a.httpClient.Do(req)
	if e != nil {
		return false, e.Error()
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
	if resp.StatusCode >= 400 {
		return false, fmt.Sprintf("HTTP %d · %s", resp.StatusCode, truncate(string(data), 300))
	}
	return true, ""
}
func (a *App) geo(ip string) string {
	if localIP(ip) {
		return "局域网 / 本机"
	}
	if r := a.one("SELECT location FROM ip_geo WHERE ip=? AND checked_at>?", ip, since(7)); r != nil {
		return str(r["location"])
	}
	req, e := http.NewRequest("GET", "http://ip-api.com/json/"+ip+"?fields=status,country,regionName,city&lang=zh-CN", nil)
	if e != nil {
		return "未知"
	}
	resp, e := a.httpClient.Do(req)
	if e != nil {
		return "未知"
	}
	defer resp.Body.Close()
	out := map[string]string{}
	if json.NewDecoder(io.LimitReader(resp.Body, 65536)).Decode(&out) != nil || out["status"] != "success" {
		return "未知"
	}
	loc := strings.TrimSpace(out["country"] + " " + out["regionName"] + " " + out["city"])
	a.exec("INSERT INTO ip_geo(ip,location,checked_at) VALUES(?,?,?) ON CONFLICT(ip) DO UPDATE SET location=excluded.location,checked_at=excluded.checked_at", ip, loc, nowISO())
	return loc
}
func (a *App) background() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-a.stop:
			return
		case n := <-a.notifications:
			a.withBackground(func() {
				if ok, e := a.sendNotify(n); !ok {
					log.Print("notification: " + e)
				}
			})
		case <-ticker.C:
			a.withBackground(func() { a.purgeVisits(); a.exec("DELETE FROM sessions WHERE expires_at<=?", nowISO()); a.reports() })
		}
	}
}
func (a *App) withBackground(fn func()) {
	defer func() {
		if p := recover(); p != nil {
			log.Printf("background: %v", p)
		}
	}()
	a.dataMu.RLock()
	defer a.dataMu.RUnlock()
	fn()
}
func (a *App) reports() {
	s := a.settings()
	if s["webhook_url"] == "" {
		return
	}
	now := time.Now()
	today := now.Format("2006-01-02")
	for _, kind := range []string{"daily", "weekly", "monthly"} {
		last := map[string]string{"daily": "notify_last_daily", "weekly": "notify_last_week", "monthly": "notify_last_month"}[kind]
		if s["notify_"+kind] != "1" || s[last] == today {
			continue
		}
		if kind == "daily" && now.Format("15:04") < s["notify_daily_time"] {
			continue
		}
		if kind == "weekly" && now.Weekday() != time.Monday {
			continue
		}
		if kind == "monthly" && now.Day() != 1 {
			continue
		}
		days := map[string]int{"daily": 1, "weekly": 7, "monthly": 30}[kind]
		cut := now.AddDate(0, 0, -days+1).Format("2006-01-02")
		visits := a.one("SELECT COUNT(*) AS pv,COUNT(DISTINCT ip) AS uv FROM visits WHERE day>=?", cut)
		uploads := a.one("SELECT COUNT(*) AS n,COALESCE(SUM(size),0) AS bytes FROM images WHERE created_at>=?", localMidnight(days-1))
		total := a.one("SELECT COUNT(*) AS n,COALESCE(SUM(size),0) AS bytes FROM images")
		message := fmt.Sprintf("访问：PV %v · UV %v\n上传：%v 张（%.1f MB）\n图库总量：%v 张（%.1f MB）", visits["pv"], visits["uv"], uploads["n"], float64(num(uploads["bytes"]))/1048576, total["n"], float64(num(total["bytes"]))/1048576)
		if ok, e := a.sendNotify(notification{kind + "_report", message, M{}}); ok {
			a.updateSettings(map[string]string{last: today})
		} else {
			log.Print(e)
		}
	}
}
func localMidnight(daysAgo int) string {
	now := time.Now()
	return time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location()).AddDate(0, 0, -daysAgo).UTC().Format("2006-01-02T15:04:05+00:00")
}
func (a *App) stats() M {
	cut := time.Now().AddDate(0, 0, -2).Format("2006-01-02")
	days := []M{}
	for n := 2; n >= 0; n-- {
		day := time.Now().AddDate(0, 0, -n).Format("2006-01-02")
		v := a.one("SELECT COUNT(*) AS pv,COUNT(DISTINCT ip) AS uv FROM visits WHERE day=?", day)
		v["day"] = day
		days = append(days, v)
	}
	ips := a.rows("SELECT ip,COUNT(*) AS count,MIN(ts) AS first_at,MAX(ts) AS last_at FROM visits WHERE day>=? GROUP BY ip ORDER BY count DESC LIMIT 20", cut)
	for _, ip := range ips {
		ip["geo"] = a.geo(str(ip["ip"]))
	}
	today := a.one("SELECT COUNT(*) AS uploads,COALESCE(SUM(size),0) AS uploadBytes FROM images WHERE created_at>=?", localMidnight(0))
	yesterday := a.count("SELECT COUNT(*) FROM images WHERE created_at>=? AND created_at<?", localMidnight(1), localMidnight(0))
	return M{"days": days, "summary": a.one("SELECT COUNT(*) AS pv,COUNT(DISTINCT ip) AS uv FROM visits WHERE day>=?", cut), "today": today, "yesterday": M{"uploads": yesterday}, "topIps": ips, "topPaths": a.rows("SELECT path,COUNT(*) AS count FROM visits WHERE day>=? GROUP BY path ORDER BY count DESC LIMIT 10", cut), "library": M{"count": a.count("SELECT COUNT(*) FROM images")}}
}
