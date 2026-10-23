package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"runtime/debug"
	"strings"
	"sync"
	"syscall"
	"time"
)

type App struct {
	db                        *sql.DB
	data, web, worker, python string
	defaults                  map[string]string
	dataMu                    sync.RWMutex
	writeMu                   sync.Mutex
	securityMu                sync.Mutex
	windows                   map[string]*rateWindow
	jobsMu                    sync.Mutex
	job                       M
	poolMu                    sync.Mutex
	poolCond                  *sync.Cond
	active                    int64
	notifications             chan notification
	httpClient                *http.Client
	stop                      chan struct{}
}

func newApp(data, web string) *App {
	must(os.MkdirAll(data, 0755))
	for _, d := range []string{"uploads", "thumbs", "compressed"} {
		must(os.MkdirAll(filepath.Join(data, d), 0755))
	}
	a := &App{data: data, web: web, worker: env("IMAGE_WORKER", "../backend/image_worker.py"), python: env("PYTHON", "python"), windows: map[string]*rateWindow{}, job: M{"running": false, "cancel": false, "total": 0, "done": 0, "imported": 0, "failed": 0, "retried": 0, "queueSize": 0, "current": "", "startedAt": "", "finishedAt": "", "errors": []any{}}, notifications: make(chan notification, 32), httpClient: &http.Client{Timeout: 8 * time.Second, Transport: &http.Transport{Proxy: http.ProxyFromEnvironment, MaxIdleConns: 4, MaxIdleConnsPerHost: 2, IdleConnTimeout: 30 * time.Second}}, stop: make(chan struct{})}
	a.poolCond = sync.NewCond(&a.poolMu)
	a.db = openDB(filepath.Join(data, "metadata.db"))
	a.initDB(true)
	return a
}
func respond(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	must(json.NewEncoder(w).Encode(v))
}
func body(r *http.Request) M {
	m := M{}
	if e := json.NewDecoder(io.LimitReader(r.Body, 65537)).Decode(&m); e != nil {
		fail(400, "invalid JSON body")
	}
	return m
}
func queryNum(r *http.Request, k string, fallback int64) int64 {
	v := r.URL.Query().Get(k)
	if v == "" {
		return fallback
	}
	return num(v)
}
func (a *App) user(r *http.Request) M {
	token := strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
	if token == "" {
		return nil
	}
	return a.one("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires_at>? AND COALESCE(u.enabled,1)=1", token, nowISO())
}
func (a *App) require(r *http.Request, admin bool) M {
	u := a.user(r)
	if u == nil {
		fail(401, "login required")
	}
	if admin && u["role"] != "admin" {
		fail(403, "admin only")
	}
	return u
}
func (a *App) recoverRequest(w http.ResponseWriter, r *http.Request) {
	if p := recover(); p != nil {
		// Consume small rejected bodies before closing the connection. On Windows
		// closing a socket with unread POST bytes can reset the response itself.
		if r.Body != nil {
			_, _ = io.Copy(io.Discard, io.LimitReader(r.Body, 64<<10))
		}
		status, msg := 500, "internal server error"
		if e, ok := p.(apiError); ok {
			status, msg = e.status, e.message
		} else {
			log.Printf("%s %s: %v\n%s", r.Method, r.URL.Path, p, debug.Stack())
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(M{"detail": msg})
	}
}
func (a *App) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	defer a.recoverRequest(w, r)
	if strings.HasPrefix(r.URL.Path, "/api/") {
		// Preserve the original API's cross-origin contract for external clients.
		if r.Header.Get("Origin") != "" {
			w.Header().Set("Access-Control-Allow-Origin", "*")
		}
		if r.Method == "OPTIONS" {
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", r.Header.Get("Access-Control-Request-Headers"))
			w.Header().Set("Access-Control-Max-Age", "600")
			w.WriteHeader(http.StatusNoContent)
			return
		}
		restore := r.Method == "POST" && r.URL.Path == "/api/admin/restore"
		if restore {
			a.jobsMu.Lock()
			busy := truth(a.job["running"])
			a.jobsMu.Unlock()
			if busy {
				fail(409, "导入任务进行中，请结束或取消导入后再恢复")
			}
			a.dataMu.Lock()
			defer a.dataMu.Unlock()
			a.jobsMu.Lock()
			busy = truth(a.job["running"])
			a.jobsMu.Unlock()
			if busy {
				fail(409, "导入任务进行中，请结束或取消导入后再恢复")
			}
		} else {
			a.dataMu.RLock()
			defer a.dataMu.RUnlock()
		}
		if r.Method != "GET" && r.Method != "HEAD" {
			a.writeMu.Lock()
			defer a.writeMu.Unlock()
		}
		sw := &statusWriter{ResponseWriter: w, status: 200}
		defer func() {
			if r.URL.Path != "/api/health" {
				a.exec("INSERT INTO visits(ts,day,ip,path,status) VALUES(?,?,?,?,?)", time.Now().Format(time.RFC3339), time.Now().Format("2006-01-02"), a.clientIP(r), r.URL.Path, sw.status)
			}
		}()
		defer a.recoverRequest(sw, r)
		a.guard(r)
		a.api(sw, r)
		return
	}
	for prefix, dir := range map[string]string{"/files/": "uploads", "/thumbs/": "thumbs", "/compressed/": "compressed"} {
		if strings.HasPrefix(r.URL.Path, prefix) {
			a.dataMu.RLock()
			defer a.dataMu.RUnlock()
			p := pathIn(filepath.Join(a.data, dir), strings.TrimPrefix(r.URL.Path, prefix))
			fi, e := os.Stat(p)
			if e != nil || fi.IsDir() {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
			http.ServeFile(w, r, p)
			return
		}
	}
	if r.Method != "GET" && r.Method != "HEAD" {
		http.NotFound(w, r)
		return
	}
	p := pathIn(a.web, r.URL.Path[1:])
	fi, e := os.Stat(p)
	if e != nil || fi.IsDir() {
		if filepath.Ext(r.URL.Path) != "" {
			http.NotFound(w, r)
			return
		}
		p = filepath.Join(a.web, "index.html")
	}
	if strings.Contains(r.URL.Path, "/assets/") {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	} else {
		w.Header().Set("Cache-Control", "no-cache")
	}
	http.ServeFile(w, r, p)
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(n int) { w.status = n; w.ResponseWriter.WriteHeader(n) }
func (a *App) api(w http.ResponseWriter, r *http.Request) {
	p, m := r.URL.Path, r.Method
	switch {
	case p == "/api/health" && m == "GET":
		a.count("SELECT 1")
		respond(w, M{"ok": true})
	case p == "/api/public/settings" && m == "GET":
		s := a.settings()
		out := M{}
		for _, k := range []string{"site_title", "site_icon", "site_tags", "site_footer", "random_public", "share_base_url", "upload_default_tags", "theme_style"} {
			out[k] = s[k]
		}
		out["upload_max_mb"] = s["upload_max_mb"]
		out["upload_formats"] = "jpg,jpeg,png,webp,avif,gif,bmp"
		respond(w, out)
	case p == "/api/images" && m == "GET":
		a.images(w, r)
	case p == "/api/tags" && m == "GET":
		out := []M{}
		rows := a.rows("SELECT tag AS name,COUNT(*) AS count FROM images WHERE tag IS NOT NULL AND trim(tag)!='' GROUP BY tag ORDER BY count DESC,tag")
		used := map[string]M{}
		seen := map[string]bool{}
		for _, row := range rows {
			used[str(row["name"])] = row
		}
		for _, name := range strings.Split(a.settings()["site_tags"], ",") {
			name = strings.TrimSpace(name)
			if row := used[name]; row != nil && !seen[name] {
				out = append(out, row)
				seen[name] = true
			}
		}
		for _, row := range rows {
			if !seen[str(row["name"])] {
				out = append(out, row)
			}
		}
		respond(w, M{"tags": out})
	case (p == "/api/random" || p == "/api/random/image") && m == "GET":
		a.random(w, r)
	case strings.HasPrefix(p, "/api/auth/"):
		a.authRoute(w, r)
	case (p == "/api/users" || strings.HasPrefix(p, "/api/users/")):
		a.usersRoute(w, r)
	case p == "/api/upload" && m == "POST":
		a.upload(w, r)
	case strings.HasPrefix(p, "/api/images/"):
		a.imageRoute(w, r)
	case strings.HasPrefix(p, "/api/admin/"):
		a.adminRoute(w, r)
	default:
		fail(404, "not found")
	}
}
func main() {
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		c := http.Client{Timeout: 3 * time.Second}
		addr := env("LISTEN_ADDR", ":80")
		_, port, e := net.SplitHostPort(addr)
		if e != nil {
			os.Exit(1)
		}
		r, e := c.Get("http://127.0.0.1:" + port + "/api/health")
		if e != nil {
			os.Exit(1)
		}
		r.Body.Close()
		if r.StatusCode != 200 {
			os.Exit(1)
		}
		return
	}
	if os.Getenv("GOMEMLIMIT") == "" {
		debug.SetMemoryLimit(40 << 20)
	}
	if os.Getenv("GOGC") == "" {
		debug.SetGCPercent(50)
	}
	a := newApp(env("DATA_DIR", "../data"), env("WEB_DIR", "../frontend/dist"))
	defer a.db.Close()
	go a.background()
	s := &http.Server{Addr: env("LISTEN_ADDR", "127.0.0.1:8000"), Handler: a, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32 << 10}
	stop, done := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer done()
	go func() {
		<-stop.Done()
		close(a.stop)
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = s.Shutdown(ctx)
	}()
	log.Printf("wusaqi-gallery · Go · data=%s · listen=%s", a.data, s.Addr)
	if env("ADMIN_PASSWORD", "changeme") == "changeme" {
		log.Print("WARNING: default initial password; configure ADMIN_PASSWORD")
	}
	if e := s.ListenAndServe(); e != nil && !errors.Is(e, http.ErrServerClosed) {
		log.Fatal(e)
	}
}
func remoteIP(r *http.Request) string {
	host, _, e := net.SplitHostPort(r.RemoteAddr)
	if e != nil {
		return r.RemoteAddr
	}
	return host
}
func (a *App) clientIP(r *http.Request) string {
	ip := remoteIP(r)
	for _, pat := range strings.Split(os.Getenv("TRUSTED_PROXIES"), ",") {
		if matchIP(ip, pat) {
			if h := r.Header.Get("X-Real-IP"); net.ParseIP(h) != nil {
				return h
			}
			parts := strings.Split(r.Header.Get("X-Forwarded-For"), ",")
			for i := len(parts) - 1; i >= 0; i-- {
				v := strings.TrimSpace(parts[i])
				if net.ParseIP(v) == nil {
					break
				}
				ip = v
				trusted := false
				for _, p := range strings.Split(os.Getenv("TRUSTED_PROXIES"), ",") {
					trusted = trusted || matchIP(ip, p)
				}
				if !trusted {
					return ip
				}
			}
			return ip
		}
	}
	return ip
}
func notFound() { fail(404, "not found") }
