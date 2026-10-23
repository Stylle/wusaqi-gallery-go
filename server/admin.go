package main

import (
	"encoding/json"
	"math"
	"net/http"
	"os"
	"runtime"
	"strconv"
	"strings"
	"time"
)

func (a *App) effective() M {
	s := a.settings()
	profiles := map[string]M{}
	must(json.Unmarshal(profilesJSON, &profiles))
	cores := int64(runtime.NumCPU())
	mem := physicalMemoryMB()
	if b, e := os.ReadFile("/proc/meminfo"); e == nil {
		for _, line := range strings.Split(string(b), "\n") {
			f := strings.Fields(line)
			if len(f) > 1 && f[0] == "MemTotal:" {
				mem = num(f[1]) / 1024
			}
		}
	}
	for _, p := range []string{"/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"} {
		if b, e := os.ReadFile(p); e == nil {
			n := num(strings.TrimSpace(string(b))) / 1048576
			if n > 0 && (mem == 0 || n < mem) {
				mem = n
			}
		}
	}
	if b, e := os.ReadFile("/sys/fs/cgroup/cpu.max"); e == nil {
		f := strings.Fields(string(b))
		if len(f) == 2 && f[0] != "max" && num(f[1]) > 0 {
			cores = min(cores, max(1, (num(f[0])+num(f[1])-1)/num(f[1])))
		}
	}
	if b, e := os.ReadFile("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"); e == nil {
		if p, e := os.ReadFile("/sys/fs/cgroup/cpu/cpu.cfs_period_us"); e == nil && num(strings.TrimSpace(string(b))) > 0 && num(strings.TrimSpace(string(p))) > 0 {
			quota, period := num(strings.TrimSpace(string(b))), num(strings.TrimSpace(string(p)))
			cores = min(cores, max(1, (quota+period-1)/period))
		}
	}
	auto := "normal"
	if cores <= 1 || (mem > 0 && mem <= 1536) {
		auto = "tiny"
	} else if cores <= 2 || (mem > 0 && mem <= 3072) {
		auto = "small"
	}
	mode := s["comp_profile"]
	name := mode
	if mode == "auto" {
		name = auto
	}
	base := profiles[name]
	if base == nil {
		base = profiles[auto]
	}
	out := M{"mode": mode, "profile": name, "autoProfile": auto, "label": base["label"], "detected": M{"cores": cores, "memMb": mem}, "format": s["comp_format"], "quality": num(base["quality"]), "maxWidth": num(base["max_width"]), "method": num(base["method"]), "maxPixels": num(base["max_pixels"]), "concurrency": num(base["concurrency"]), "thumbQuality": num(base["thumb_quality"]), "thumbMethod": num(base["thumb_method"])}
	if mode == "custom" {
		out["label"] = "自定义方案"
		for k, rule := range map[string][3]int64{"quality": {1, 100, 80}, "maxWidth": {0, 12000, 2560}, "method": {0, 6, 0}, "maxPixels": {0, 500, 0}, "concurrency": {1, 8, 1}} {
			key := map[string]string{"quality": "comp_quality", "maxWidth": "comp_max_width", "method": "comp_method", "maxPixels": "comp_max_pixels", "concurrency": "comp_concurrency"}[k]
			v, e := strconv.ParseInt(s[key], 10, 64)
			if e != nil {
				v = rule[2]
			}
			out[k] = clamp(v, rule[0], rule[1])
		}
	}
	return out
}

var inputFormats = []M{
	{"ext": "jpg / jpeg", "label": "JPG / JPEG", "recommend": true, "note": "照片首选：体积小、兼容性最好，压缩后几乎无感"},
	{"ext": "png", "label": "PNG", "recommend": true, "note": "截图 / 需要透明背景时用；无损但原图体积偏大"},
	{"ext": "webp", "label": "WebP", "recommend": true, "note": "已有素材推荐：同画质体积最小，所有现代浏览器都支持"},
	{"ext": "avif", "label": "AVIF", "recommend": false, "note": "支持（取决于 Pillow 构建）；部分老浏览器打不开"},
	{"ext": "gif", "label": "GIF", "recommend": false, "note": "支持，但动图不生成压缩版（保留原图），流量偏大"},
	{"ext": "bmp", "label": "BMP", "recommend": false, "note": "不推荐：未压缩位图，体积可能是 JPG 的 10 倍以上"},
}

func (a *App) system() M {
	p := map[string]M{}
	must(json.Unmarshal(profilesJSON, &p))
	profiles := []M{}
	for _, k := range []string{"tiny", "small", "normal"} {
		v := p[k]
		v["name"] = k
		profiles = append(profiles, v)
	}
	eff := a.effective()
	a.poolMu.Lock()
	active := a.active
	a.poolMu.Unlock()
	return M{"perf": eff, "profiles": profiles, "formats": inputFormats, "pool": M{"limit": eff["concurrency"], "active": active}, "runtime": M{"engine": "go", "imageWorker": "on-demand", "sqliteConnections": 1}}
}
func (a *App) saveSettings(v M) {
	clean := map[string]string{}
	switches := ",random_public,notify_admin_login,notify_security,notify_ban,notify_restore,notify_daily,notify_weekly,notify_monthly,"
	ranges := map[string][2]int64{"comp_quality": {1, 100}, "comp_method": {0, 6}, "comp_max_width": {0, 12000}, "comp_max_pixels": {0, 500}, "comp_concurrency": {0, 8}, "upload_max_mb": {0, 200}, "new_user_quota_mb": {0, 1e9}, "new_user_max_upload_mb": {0, 200}, "new_user_daily": {0, 1e9}, "new_user_weekly": {0, 1e9}, "new_user_monthly": {0, 1e9}, "rate_limit": {0, 100000}, "rate_ban_minutes": {1, 5256000}, "auth_max_fails": {1, 100000}, "auth_ban_minutes": {1, 5256000}, "session_hours": {1, 87600}, "remember_days": {1, 3650}}
	choices := map[string]string{"comp_profile": ",auto,tiny,small,normal,custom,", "comp_format": ",webp,jpeg,png,", "theme_style": ",gradient,solid,", "notify_method": ",POST,PUT,GET,", "notify_body_type": ",json,text,"}
	for k, x := range v {
		if _, ok := a.defaults[k]; !ok {
			continue
		}
		s := strings.TrimSpace(str(x))
		if strings.Contains(switches, ","+k+",") {
			if truth(x) {
				s = "1"
			} else {
				s = "0"
			}
		} else if rule, ok := ranges[k]; ok {
			n, e := strconv.ParseFloat(s, 64)
			if e != nil || math.IsNaN(n) || math.IsInf(n, 0) {
				fail(400, k+" 必须是数字")
			}
			s = strconv.FormatInt(clamp(int64(n), rule[0], rule[1]), 10)
		} else if choice, ok := choices[k]; ok {
			valid := false
			for _, option := range strings.Split(choice, ",") {
				if s != "" && s == option {
					valid = true
				}
			}
			if !valid {
				fail(400, "invalid "+k)
			}
		} else if k == "notify_daily_time" {
			if _, e := time.Parse("15:04", s); e != nil {
				fail(400, "invalid notify_daily_time")
			}
		} else {
			n := 500
			if k == "notify_headers" || k == "notify_body_tpl" {
				n = 2000
			}
			s = truncate(s, n)
		}
		if k == "notify_headers" && s != "" {
			var h map[string]string
			if json.Unmarshal([]byte(s), &h) != nil {
				fail(400, "自定义请求头不是合法的 JSON 对象")
			}
		}
		clean[k] = s
	}
	if len(clean) == 0 {
		fail(400, "no valid fields")
	}
	a.updateSettings(clean)
}
func (a *App) adminSettings() map[string]string {
	stored := a.settings()
	out := map[string]string{}
	for k := range a.defaults {
		out[k] = stored[k]
	}
	return out
}
func (a *App) adminRoute(w http.ResponseWriter, r *http.Request) {
	// Removed aliases return 404, including for anonymous callers.
	if r.URL.Path == "/api/admin/upload" || r.URL.Path == "/api/admin/reindex" || r.URL.Path == "/api/admin/verify" {
		notFound()
	}
	u := a.require(r, true)
	p, m := r.URL.Path, r.Method
	switch {
	case p == "/api/admin/settings" && m == "GET":
		respond(w, a.adminSettings())
	case p == "/api/admin/settings" && m == "PUT":
		a.saveSettings(body(r))
		respond(w, a.adminSettings())
	case p == "/api/admin/system" && m == "GET":
		respond(w, a.system())
	case strings.HasPrefix(p, "/api/admin/local/"):
		a.localRoute(w, r, u)
	case strings.HasPrefix(p, "/api/admin/bans") || strings.HasPrefix(p, "/api/admin/whitelist") || strings.HasPrefix(p, "/api/admin/blacklist"):
		a.bansRoute(w, r, u)
	case p == "/api/admin/backup/stats" && m == "GET":
		respond(w, a.backupStats())
	case p == "/api/admin/backup" && m == "GET":
		a.downloadBackup(w, r)
	case p == "/api/admin/restore" && m == "POST":
		a.restoreBackup(w, r, u)
	case p == "/api/admin/stats" && m == "GET":
		respond(w, a.stats())
	case p == "/api/admin/notify/test" && m == "POST":
		ok, err := a.sendNotify(notification{"test", "这是一条来自 wusaqi-gallery 的测试通知 ✅", M{}})
		respond(w, M{"ok": ok, "error": err})
	default:
		notFound()
	}
}
