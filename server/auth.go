package main

import (
	"math"
	"net/http"
	"strings"
	"time"
	"unicode"
)

func (a *App) usage(uid any) M {
	return a.one("SELECT COALESCE(SUM(size),0) AS used,COUNT(*) AS count FROM images WHERE owner_id=?", uid)
}
func (a *App) uploadCounts(uid any) M {
	out := M{}
	for k, days := range map[string]int{"day": 1, "week": 7, "month": 30} {
		out[k] = a.count("SELECT COUNT(*) FROM images WHERE owner_id=? AND created_at>=?", uid, since(days))
	}
	return out
}
func (a *App) publicUser(u M) M {
	use := a.usage(u["id"])
	s := a.settings()
	quota := num(u["quota_mb"])
	if u["role"] == "admin" {
		quota = 0
	}
	left := int64(-1)
	if quota > 0 {
		left = max(0, quota*1048576-num(use["used"]))
	}
	maxUp := num(u["max_upload_mb"])
	if maxUp == 0 {
		maxUp = num(s["upload_max_mb"])
	}
	lim := M{"daily": num(u["daily_limit"]), "weekly": num(u["weekly_limit"]), "monthly": num(u["monthly_limit"])}
	if u["role"] == "admin" {
		maxUp = 0
		lim = M{"daily": 0, "weekly": 0, "monthly": 0}
	}
	return M{"id": u["id"], "username": u["username"], "role": u["role"], "quotaMb": quota, "usedBytes": use["used"], "imageCount": use["count"], "remainingBytes": left, "maxUploadMb": maxUp, "uploadLimits": lim, "uploadCounts": a.uploadCounts(u["id"]), "compFormat": u["comp_format"], "compQuality": u["comp_quality"], "compMaxWidth": u["comp_max_width"], "enabled": u["enabled"], "createdAt": u["created_at"]}
}
func (a *App) authRoute(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Path
	switch {
	case p == "/api/auth/login" && r.Method == "POST":
		v := body(r)
		u := a.one("SELECT * FROM users WHERE username=? AND COALESCE(enabled,1)=1", strings.TrimSpace(str(v["username"])))
		ip := a.clientIP(r)
		if u == nil || !verify(str(v["password"]), str(u["pwd"])) {
			a.failedLogin(ip)
			fail(401, "用户名或密码错误")
		}
		a.securityMu.Lock()
		delete(a.windows, "auth:"+ip)
		a.securityMu.Unlock()
		a.exec("DELETE FROM sessions WHERE expires_at<=?", nowISO())
		s := a.settings()
		remember := truth(v["remember"])
		ttl := time.Duration(max(1, num(s["session_hours"]))) * time.Hour
		if remember {
			ttl = time.Duration(max(1, num(s["remember_days"]))) * 24 * time.Hour
		}
		token := id(32)
		exp := time.Now().UTC().Add(ttl).Format("2006-01-02T15:04:05+00:00")
		a.insert("sessions", M{"token": token, "user_id": u["id"], "expires_at": exp, "remember": map[bool]int{true: 1, false: 0}[remember], "created_at": nowISO()})
		if u["role"] == "admin" {
			a.fire("admin_login", "", M{"ip": ip, "username": u["username"], "role": u["role"], "ua": r.UserAgent()})
		}
		respond(w, M{"token": token, "remember": remember, "expiresAt": exp, "user": a.publicUser(u)})
	case p == "/api/auth/logout" && r.Method == "POST":
		a.exec("DELETE FROM sessions WHERE token=?", strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")))
		respond(w, M{"ok": true})
	case p == "/api/auth/me" && r.Method == "GET":
		respond(w, a.publicUser(a.require(r, false)))
	case p == "/api/auth/password" && r.Method == "POST":
		u := a.require(r, false)
		v := body(r)
		pw := strings.TrimSpace(str(v["new"]))
		if len([]rune(pw)) < 6 {
			fail(400, "新密码至少 6 位")
		}
		if !verify(str(v["old"]), str(u["pwd"])) {
			fail(401, "原密码错误")
		}
		a.update("users", "id", u["id"], M{"pwd": password(pw)})
		respond(w, M{"ok": true})
	default:
		notFound()
	}
}
func cleanUser(v M, partial bool) M {
	f := M{}
	if x, ok := v["username"]; ok || !partial {
		name := strings.TrimSpace(str(x))
		valid := len([]rune(name)) >= 3 && len([]rune(name)) <= 32
		for _, c := range name {
			if !unicode.IsLetter(c) && !unicode.IsDigit(c) && !strings.ContainsRune("_-.", c) {
				valid = false
			}
		}
		if !valid {
			fail(400, "用户名 3-32 位，仅字母数字 _ - .")
		}
		f["username"] = name
	}
	if x, ok := v["role"]; ok || !partial {
		if x == nil {
			x = "user"
		}
		if x != "admin" && x != "user" {
			fail(400, "role 必须是 admin 或 user")
		}
		f["role"] = x
	}
	for _, k := range []string{"quota_mb", "max_upload_mb", "daily_limit", "weekly_limit", "monthly_limit"} {
		if x, ok := v[k]; ok {
			n, ok := x.(float64)
			if !ok {
				if str(x) == "" {
					n = 0
				} else {
					fail(400, k+" 必须是数字")
				}
			}
			if math.IsNaN(n) || math.IsInf(n, 0) || n > 1e9 {
				fail(400, "invalid quota")
			}
			f[k] = max(0, int64(math.Ceil(n)))
		}
	}
	if x, ok := v["comp_quality"]; ok {
		if x == nil || x == "" {
			f["comp_quality"] = nil
		} else {
			f["comp_quality"] = clamp(num(x), 1, 100)
		}
	}
	if x, ok := v["comp_max_width"]; ok {
		if x == nil || x == "" {
			f["comp_max_width"] = nil
		} else {
			f["comp_max_width"] = clamp(num(x), 0, 12000)
		}
	}
	if x, ok := v["comp_format"]; ok {
		f["comp_format"] = nil
		if x == "webp" || x == "jpeg" || x == "png" {
			f["comp_format"] = x
		}
	}
	if x, ok := v["enabled"]; ok {
		f["enabled"] = map[bool]int{true: 1, false: 0}[truth(x)]
	}
	return f
}
func (a *App) usersRoute(w http.ResponseWriter, r *http.Request) {
	admin := a.require(r, true)
	uid := strings.TrimPrefix(r.URL.Path, "/api/users/")
	if r.URL.Path == "/api/users" {
		if r.Method == "GET" {
			out := []M{}
			for _, u := range a.rows("SELECT * FROM users ORDER BY role='admin' DESC,created_at") {
				delete(u, "pwd")
				use := a.usage(u["id"])
				u["used"], u["count"] = use["used"], use["count"]
				c := a.uploadCounts(u["id"])
				u["day_count"], u["week_count"], u["month_count"] = c["day"], c["week"], c["month"]
				u["remainingBytes"] = int64(-1)
				if num(u["quota_mb"]) > 0 {
					u["remainingBytes"] = max(0, num(u["quota_mb"])*1048576-num(use["used"]))
				}
				out = append(out, u)
			}
			respond(w, M{"users": out})
			return
		}
		if r.Method != "POST" {
			notFound()
		}
		v := body(r)
		f := cleanUser(v, false)
		pw := strings.TrimSpace(str(v["password"]))
		if len([]rune(pw)) < 6 {
			fail(400, "密码至少 6 位")
		}
		if a.one("SELECT id FROM users WHERE username=?", f["username"]) != nil {
			fail(409, "用户名已存在")
		}
		s := a.settings()
		for k, sk := range map[string]string{"quota_mb": "new_user_quota_mb", "max_upload_mb": "new_user_max_upload_mb", "daily_limit": "new_user_daily", "weekly_limit": "new_user_weekly", "monthly_limit": "new_user_monthly"} {
			if _, ok := f[k]; !ok {
				f[k] = max(0, num(s[sk]))
			}
		}
		uid = id(8)
		f["id"], f["pwd"], f["created_at"] = uid, password(pw), nowISO()
		if _, ok := f["enabled"]; !ok {
			f["enabled"] = 1
		}
		a.insert("users", f)
		respond(w, M{"ok": true, "user": a.publicUser(a.one("SELECT * FROM users WHERE id=?", uid))})
		return
	}
	target := a.one("SELECT * FROM users WHERE id=?", uid)
	if target == nil {
		fail(404, "用户不存在")
	}
	if r.Method == "PATCH" {
		v := body(r)
		f := cleanUser(v, true)
		if n, ok := f["username"]; ok && a.one("SELECT id FROM users WHERE username=? AND id!=?", n, uid) != nil {
			fail(409, "用户名已存在")
		}
		// An account must retain at least one enabled administrator.
		losing := f["role"] == "user" || f["enabled"] == 0
		if target["role"] == "admin" && num(target["enabled"]) != 0 && losing && a.count("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1") <= 1 {
			fail(400, "不能移除最后一个启用的管理员")
		}
		if uid == str(admin["id"]) && f["enabled"] == 0 {
			fail(400, "不能停用自己")
		}
		if pw := strings.TrimSpace(str(v["password"])); pw != "" {
			if len([]rune(pw)) < 6 {
				fail(400, "密码至少 6 位")
			}
			f["pwd"] = password(pw)
		}
		a.update("users", "id", uid, f)
		respond(w, M{"ok": true, "user": a.publicUser(a.one("SELECT * FROM users WHERE id=?", uid))})
		return
	}
	if r.Method == "DELETE" {
		if uid == str(admin["id"]) {
			fail(400, "不能删除自己")
		}
		if target["role"] == "admin" && num(target["enabled"]) != 0 && a.count("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1") <= 1 {
			fail(400, "不能删除最后一个管理员")
		}
		removed := 0
		if truth(r.URL.Query().Get("purge")) {
			for _, im := range a.rows("SELECT * FROM images WHERE owner_id=?", uid) {
				a.removeImage(im)
				removed++
			}
		} else {
			a.exec("UPDATE images SET owner_id=? WHERE owner_id=?", admin["id"], uid)
		}
		a.exec("DELETE FROM sessions WHERE user_id=?", uid)
		a.exec("DELETE FROM users WHERE id=?", uid)
		respond(w, M{"ok": true, "removedImages": removed})
		return
	}
	notFound()
}
