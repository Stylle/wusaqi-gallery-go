package main

import (
	"net"
	"net/http"
	"strings"
	"time"
)

func matchIP(ip, pattern string) bool {
	pattern = strings.TrimSpace(pattern)
	if pattern == "" {
		return false
	}
	if strings.HasSuffix(pattern, ".*") {
		pattern = strings.TrimSuffix(pattern, "*") + "0/24"
	}
	if strings.Contains(pattern, "/") {
		_, n, e := net.ParseCIDR(pattern)
		return e == nil && n.Contains(net.ParseIP(ip))
	}
	p, q := net.ParseIP(ip), net.ParseIP(pattern)
	return p != nil && q != nil && p.Equal(q)
}
func localIP(ip string) bool {
	p := net.ParseIP(ip)
	return p != nil && (p.IsLoopback() || p.IsPrivate() || p.IsLinkLocalUnicast() || p.IsUnspecified())
}
func (a *App) inList(ip, table string) bool {
	for _, r := range a.rows("SELECT pattern FROM " + table) {
		if matchIP(ip, str(r["pattern"])) {
			return true
		}
	}
	return false
}
func (a *App) bypass(ip string) bool { return localIP(ip) || a.inList(ip, "ip_whitelist") }

// Sixty fixed buckets bound memory independently of the request limit. Each
// bucket lives at most ttl; random API resolution is 1s, login failures 10s.
type rateWindow struct {
	counts [60]int64
	ticks  [60]int64
	last   int64
}

func (a *App) window(key string, ttl time.Duration, limit int64) bool {
	a.securityMu.Lock()
	defer a.securityMu.Unlock()
	now := time.Now().Unix()
	tick := now / max(1, int64(ttl.Seconds())/60)
	old := a.windows[key]
	if old == nil {
		old = &rateWindow{}
		a.windows[key] = old
	}
	index := tick % 60
	if old.ticks[index] != tick {
		old.ticks[index] = tick
		old.counts[index] = 0
	}
	old.last = now
	total := int64(0)
	for i, t := range old.ticks {
		if tick-t < 60 {
			total += old.counts[i]
		}
	}
	if total >= limit {
		return false
	}
	old.counts[index]++
	// New clients cannot grow resident state without bound; expired clients evict first.
	if len(a.windows) > 4096 {
		for k, v := range a.windows {
			if now-v.last > 600 {
				delete(a.windows, k)
			}
		}
		if len(a.windows) > 4096 {
			for k := range a.windows {
				if k != key {
					delete(a.windows, k)
					break
				}
			}
		}
	}
	return true
}
func (a *App) ban(ip string, minutes int64, reason string) {
	if a.bypass(ip) {
		return
	}
	a.exec("INSERT INTO bans(ip,until_ts,reason,hits,created_at) VALUES(?,?,?,1,?) ON CONFLICT(ip) DO UPDATE SET until_ts=MAX(until_ts,excluded.until_ts),reason=excluded.reason,hits=hits+1", ip, time.Now().Unix()+max(1, minutes)*60, reason, nowISO())
}
func (a *App) guard(r *http.Request) {
	ip := a.clientIP(r)
	if a.bypass(ip) {
		return
	}
	if a.inList(ip, "ip_blacklist") {
		fail(403, "blocked by administrator")
	}
	if b := a.one("SELECT * FROM bans WHERE ip=? AND until_ts>?", ip, time.Now().Unix()); b != nil {
		fail(429, "banned ("+str(b["reason"])+")")
	}
	if strings.HasPrefix(r.URL.Path, "/api/random") {
		s := a.settings()
		lim := num(s["rate_limit"])
		if lim > 0 && !a.window("rate:"+ip, time.Minute, lim) {
			minutes := max(1, num(s["rate_ban_minutes"]))
			a.ban(ip, minutes, "rate limit exceeded")
			a.fire("rate_limit", "", M{"ip": ip, "path": r.URL.Path, "limit_per_minute": lim, "ban_minutes": minutes, "ua": r.UserAgent()})
			fail(429, "rate limited")
		}
	}
}
func (a *App) failedLogin(ip string) {
	if a.bypass(ip) {
		return
	}
	s := a.settings()
	limit := max(1, num(s["auth_max_fails"]))
	if !a.window("auth:"+ip, 10*time.Minute, max(1, limit-1)) || limit == 1 {
		minutes := max(1, num(s["auth_ban_minutes"]))
		a.ban(ip, minutes, "auth brute force")
		a.fire("auth_brute_force", "", M{"ip": ip, "fails": limit, "ban_minutes": minutes})
		fail(429, "too many failures")
	}
}
func normPattern(s string) string {
	s = strings.TrimSpace(s)
	if strings.HasSuffix(s, ".*") {
		s = strings.TrimSuffix(s, "*") + "0/24"
	}
	if strings.Contains(s, "/") {
		_, n, e := net.ParseCIDR(s)
		if e != nil {
			fail(400, "invalid CIDR")
		}
		return n.String()
	}
	p := net.ParseIP(s)
	if p == nil {
		fail(400, "invalid IP address")
	}
	return p.String()
}
func banJSON(r M) M {
	r["remaining"] = max(0, num(r["until_ts"])-time.Now().Unix())
	r["until"] = time.Unix(num(r["until_ts"]), 0).UTC().Format(time.RFC3339)
	return r
}
func (a *App) bansRoute(w http.ResponseWriter, r *http.Request, u M) {
	p, m := r.URL.Path, r.Method
	if p == "/api/admin/bans" && m == "GET" {
		a.exec("DELETE FROM bans WHERE until_ts<=?", time.Now().Unix())
		b := []M{}
		for _, row := range a.rows("SELECT * FROM bans ORDER BY until_ts DESC") {
			b = append(b, banJSON(row))
		}
		respond(w, M{"bans": b, "whitelist": a.rows("SELECT * FROM ip_whitelist ORDER BY created_at DESC"), "blacklist": a.rows("SELECT * FROM ip_blacklist ORDER BY created_at DESC")})
		return
	}
	if p == "/api/admin/bans" && m == "POST" {
		v := body(r)
		ip := normPattern(str(v["ip"]))
		if strings.Contains(ip, "/") {
			fail(400, "only single IP can be banned")
		}
		if localIP(ip) {
			fail(400, "本机 / 局域网地址不可封禁")
		}
		if ip == a.clientIP(r) {
			fail(400, "不能封禁当前正在使用的 IP")
		}
		if a.bypass(ip) {
			fail(400, "IP is in the whitelist, remove it first")
		}
		minutes := num(v["minutes"])
		if minutes <= 0 {
			minutes = 10 * 365 * 24 * 60
		}
		reason := truncate(strings.TrimSpace(str(v["reason"])), 120)
		if reason == "" {
			reason = "manual ban"
		}
		a.ban(ip, minutes, reason)
		row := banJSON(a.one("SELECT * FROM bans WHERE ip=?", ip))
		a.fire("manual_ban", "", M{"ip": ip, "minutes": minutes, "reason": reason, "until": row["until"], "operator": u["username"]})
		respond(w, M{"ok": true, "ban": row})
		return
	}
	if strings.HasPrefix(p, "/api/admin/bans/") && m == "DELETE" {
		ip := strings.TrimPrefix(p, "/api/admin/bans/")
		res := a.exec("DELETE FROM bans WHERE ip=?", ip)
		n, _ := res.RowsAffected()
		if n == 0 {
			fail(404, "not banned")
		}
		a.fire("manual_unban", "", M{"ip": ip, "operator": u["username"]})
		respond(w, M{"ok": true, "ip": ip})
		return
	}
	for _, kind := range []string{"whitelist", "blacklist"} {
		prefix := "/api/admin/" + kind
		table := "ip_" + kind
		if p == prefix && m == "POST" {
			v := body(r)
			pat := normPattern(str(v["pattern"]))
			ip := strings.Split(pat, "/")[0]
			if kind == "blacklist" {
				if localIP(ip) {
					fail(400, "本机 / 局域网网段不可加入黑名单")
				}
				if a.inList(ip, "ip_whitelist") {
					fail(400, "this IP is whitelisted, remove it from the whitelist first")
				}
			}
			a.exec("INSERT INTO "+table+"(pattern,note,created_at) VALUES(?,?,?) ON CONFLICT(pattern) DO UPDATE SET note=excluded.note", pat, truncate(strings.TrimSpace(str(v["note"])), 120), nowISO())
			a.exec("DELETE FROM bans WHERE ip=?", pat)
			respond(w, M{"ok": true, kind: a.rows("SELECT * FROM " + table + " ORDER BY created_at DESC")})
			return
		}
		if strings.HasPrefix(p, prefix+"/") && m == "DELETE" {
			pat := strings.TrimPrefix(p, prefix+"/")
			res := a.exec("DELETE FROM "+table+" WHERE pattern=?", pat)
			n, _ := res.RowsAffected()
			if n == 0 {
				fail(404, "not found")
			}
			respond(w, M{"ok": true, "pattern": pat})
			return
		}
	}
	notFound()
}
