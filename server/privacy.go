package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const privateTag = "私密"
const mediaCookie = "wusaqi_media"
const viewerCookie = "wusaqi_viewer"

func canViewImage(im, u M) bool {
	return im != nil && (str(im["tag"]) != privateTag || (u != nil && u["role"] == "admin"))
}
func cleanTag(value any, u M) string {
	tag := truncate(strings.TrimSpace(str(value)), 40)
	if tag == privateTag && (u == nil || u["role"] != "admin") {
		fail(403, "私密标签仅管理员可使用")
	}
	return tag
}
func privateFilter(r *http.Request, u M) string {
	if u != nil && u["role"] == "admin" && truth(r.URL.Query().Get("include_private")) {
		return "1=1"
	}
	return "COALESCE(i.tag,'')!='私密'"
}
func disabledTags(s map[string]string) []string {
	var tags []string
	must(json.Unmarshal([]byte(s["external_disabled_tags"]), &tags))
	return tags
}
func externalAllowed(im M, s map[string]string) bool {
	if !canViewImage(im, nil) || s["site_public"] != "1" || s["external_links_enabled"] != "1" {
		return false
	}
	for _, tag := range disabledTags(s) {
		if str(im["tag"]) == tag {
			return false
		}
	}
	return true
}
func (a *App) tokenUser(token string) M {
	if token == "" {
		return nil
	}
	return a.one("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires_at>? AND COALESCE(u.enabled,1)=1", token, nowISO())
}
func (a *App) mediaUser(r *http.Request) M {
	if r.Header.Get("Authorization") != "" {
		return a.user(r)
	}
	if c, err := r.Cookie(mediaCookie); err == nil {
		return a.tokenUser(c.Value)
	}
	return nil
}
func (a *App) setMediaCookie(w http.ResponseWriter, r *http.Request) {
	token := strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
	if token == "" {
		return
	}
	s := a.one("SELECT expires_at,remember FROM sessions WHERE token=? AND expires_at>?", token, nowISO())
	if s == nil {
		return
	}
	c := &http.Cookie{Name: mediaCookie, Value: token, Path: "/media/", HttpOnly: true, SameSite: http.SameSiteStrictMode, Secure: requestHTTPS(r)}
	if num(s["remember"]) == 1 {
		c.Expires, _ = time.Parse(time.RFC3339, str(s["expires_at"]))
	}
	http.SetCookie(w, c)
}
func viewerSignature(value, secret string) string {
	h := hmac.New(sha256.New, []byte(secret))
	h.Write([]byte(value))
	return hex.EncodeToString(h.Sum(nil))
}
func (a *App) setViewerCookie(w http.ResponseWriter, r *http.Request, s map[string]string) {
	if s["site_public"] != "1" {
		return
	}
	exp := strconv.FormatInt(time.Now().Add(12*time.Hour).Unix(), 10)
	value := exp + "." + viewerSignature(exp, s["_viewer_secret"])
	http.SetCookie(w, &http.Cookie{Name: viewerCookie, Value: value, Path: "/media/", MaxAge: 43200, HttpOnly: true, SameSite: http.SameSiteStrictMode, Secure: requestHTTPS(r)})
}
func validViewer(r *http.Request, s map[string]string) bool {
	c, err := r.Cookie(viewerCookie)
	if err != nil || s["_viewer_secret"] == "" {
		return false
	}
	p := strings.Split(c.Value, ".")
	if len(p) != 2 {
		return false
	}
	exp, err := strconv.ParseInt(p[0], 10, 64)
	return err == nil && exp > time.Now().Unix() && hmac.Equal([]byte(p[1]), []byte(viewerSignature(p[0], s["_viewer_secret"])))
}

// Internal media requires a same-site viewing cookie or a live login. Public
// share paths always recheck the current policy, including legacy copied URLs.
// API mutations continue to require Bearer auth; cookies never authorize them.
func (a *App) serveMedia(w http.ResponseWriter, r *http.Request) bool {
	internal := strings.HasPrefix(r.URL.Path, "/media/")
	p := r.URL.Path
	if internal {
		p = strings.TrimPrefix(p, "/media")
	}
	for prefix, dir := range map[string]string{"/files/": "uploads", "/thumbs/": "thumbs", "/compressed/": "compressed"} {
		if !strings.HasPrefix(p, prefix) {
			continue
		}
		a.dataMu.RLock()
		defer a.dataMu.RUnlock()
		w.Header().Set("Cache-Control", "private, no-store")
		w.Header().Set("Vary", "Cookie, Authorization")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		if r.Method != "GET" && r.Method != "HEAD" {
			notFound()
		}
		a.guard(r)
		key := strings.TrimPrefix(p, prefix)
		file := pathIn(filepath.Join(a.data, dir), key)
		column, lookup := "key", key
		if dir == "thumbs" {
			lookup = strings.TrimSuffix(key, ".webp")
			if lookup == key {
				notFound()
			}
		}
		if dir == "compressed" {
			column = "c_key"
		}
		images := a.rows("SELECT * FROM images WHERE "+column+"=?", lookup)
		if len(images) == 0 {
			notFound()
		}
		s := a.settings()
		u := a.mediaUser(r)
		for _, im := range images {
			if internal {
				if !canViewImage(im, u) || (u == nil && (s["site_public"] != "1" || !validViewer(r, s))) {
					notFound()
				}
			} else if !externalAllowed(im, s) {
				notFound()
			}
		}
		fi, err := os.Stat(file)
		if err != nil || !fi.Mode().IsRegular() {
			notFound()
		}
		http.ServeFile(w, r, file)
		return true
	}
	if internal {
		notFound()
	}
	return false
}

func (a *App) adminTags(w http.ResponseWriter) {
	s := a.settings()
	rows := a.rows("SELECT COALESCE(tag,'') AS name,COUNT(*) AS count FROM images GROUP BY COALESCE(tag,'') ORDER BY name")
	seen := map[string]bool{}
	for _, row := range rows {
		seen[str(row["name"])] = true
	}
	for _, tag := range append(disabledTags(s), privateTag) {
		if !seen[tag] {
			rows = append(rows, M{"name": tag, "count": 0})
			seen[tag] = true
		}
	}
	respond(w, M{"tags": rows})
}
