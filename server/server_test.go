package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func testApp(t *testing.T) *App {
	t.Helper()
	t.Setenv("ADMIN_PASSWORD", "test-password")
	t.Setenv("ADMIN_SYNC", "0")
	a := newApp(t.TempDir(), t.TempDir())
	t.Cleanup(func() { a.db.Close() })
	return a
}
func TestAdminEnvironmentAndSync(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", " owner ")
	a := testApp(t)
	u := a.one("SELECT * FROM users WHERE role='admin'")
	if u["username"] != "owner" || !verify("test-password", str(u["pwd"])) {
		t.Fatal("initial admin not seeded")
	}
	t.Setenv("ADMIN_PASSWORD", "changed-password")
	a.initDB(true)
	u = a.one("SELECT * FROM users WHERE role='admin'")
	if !verify("test-password", str(u["pwd"])) {
		t.Fatal("restart replaced password without sync")
	}
	t.Setenv("ADMIN_SYNC", "1")
	t.Setenv("ADMIN_USERNAME", "rescued")
	a.initDB(true)
	u = a.one("SELECT * FROM users WHERE role='admin'")
	if u["username"] != "rescued" || !verify("changed-password", str(u["pwd"])) {
		t.Fatal("rescue sync did not work")
	}
}
func TestProxyHeadersRequireTrustedPeer(t *testing.T) {
	a := testApp(t)
	r := httptest.NewRequest("GET", "/api/health", nil)
	r.RemoteAddr = "8.8.8.8:42"
	r.Header.Set("X-Real-IP", "127.0.0.1")
	if a.clientIP(r) != "8.8.8.8" {
		t.Fatal("untrusted peer spoofed client IP")
	}
	t.Setenv("TRUSTED_PROXIES", "8.8.8.8/32")
	if a.clientIP(r) != "127.0.0.1" {
		t.Fatal("trusted proxy ignored")
	}
	r.Header.Del("X-Real-IP")
	r.Header.Set("X-Forwarded-For", "1.1.1.1,9.9.9.9")
	if a.clientIP(r) != "9.9.9.9" {
		t.Fatal("trusted chain did not stop at untrusted hop")
	}
}
func TestFailureStatusRecordedAndSQLiteBounded(t *testing.T) {
	a := testApp(t)
	r := httptest.NewRequest("GET", "/api/admin/settings", nil)
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("status %d", w.Code)
	}
	if a.count("SELECT status FROM visits LIMIT 1") != 401 {
		t.Fatal("failure logged as success")
	}
	if a.db.Stats().MaxOpenConnections != 1 {
		t.Fatal("unbounded connection pool")
	}
}
func TestSettingsRejectUnknownKeys(t *testing.T) {
	a := testApp(t)
	a.saveSettings(M{"site_title": "hello", "unrecognized": "value"})
	s := a.settings()
	if s["site_title"] != "hello" || s["unrecognized"] != "" {
		t.Fatal("settings whitelist not enforced")
	}
	a.saveSettings(M{"upload_max_mb": 0})
	if a.settings()["upload_max_mb"] != "0" {
		t.Fatal("zero lost")
	}
}
func TestPublicRandomNoCache(t *testing.T) {
	a := testApp(t)
	a.updateSettings(map[string]string{"random_public": "1"})
	a.insert("images", M{"id": "test", "key": "a.jpg", "mime": "image/jpeg", "width": 1, "height": 1, "size": 1, "created_at": nowISO()})
	r := httptest.NewRequest("GET", "/api/random/image", nil)
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Code != 302 || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("random redirect cache behavior changed")
	}
}
func TestMalformedAndOversizedJSON(t *testing.T) {
	a := testApp(t)
	for _, payload := range []string{"not json", `[]`, `null`, strings.Repeat(" ", 65537) + `{}`} {
		w := httptest.NewRecorder()
		r := httptest.NewRequest("POST", "/api/auth/login", strings.NewReader(payload))
		a.ServeHTTP(w, r)
		if w.Code >= 500 {
			t.Fatalf("malformed payload returned %d", w.Code)
		}
		var response M
		if json.Unmarshal(w.Body.Bytes(), &response) != nil {
			t.Fatal("invalid error JSON")
		}
	}
}

func TestDailyReportSendsOnce(t *testing.T) {
	a := testApp(t)
	var calls atomic.Int32
	hook := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1); w.WriteHeader(200) }))
	defer hook.Close()
	a.updateSettings(map[string]string{"webhook_url": hook.URL, "notify_daily": "1", "notify_daily_time": "00:00"})
	a.reports()
	a.reports()
	if calls.Load() != 1 {
		t.Fatalf("daily report sent %d times", calls.Load())
	}
}

func TestTagPoolOrderWithoutEmptyTags(t *testing.T) {
	a := testApp(t)
	a.updateSettings(map[string]string{"site_tags": "unused,zebra,alpha"})
	for _, tag := range []string{"alpha", "zebra"} {
		a.insert("images", M{"id": tag, "key": tag + ".jpg", "tag": tag, "mime": "image/jpeg", "width": 1, "height": 1, "size": 1, "created_at": nowISO()})
	}
	w := httptest.NewRecorder()
	a.ServeHTTP(w, httptest.NewRequest("GET", "/api/tags", nil))
	var result struct {
		Tags []struct {
			Name string `json:"name"`
		}
	}
	if json.Unmarshal(w.Body.Bytes(), &result) != nil || len(result.Tags) != 2 || result.Tags[0].Name != "zebra" || result.Tags[1].Name != "alpha" {
		t.Fatal("tag pool order or empty tag filtering changed")
	}
}

func TestCrossOriginAPIContract(t *testing.T) {
	a := testApp(t)
	r := httptest.NewRequest("OPTIONS", "/api/images", nil)
	r.Header.Set("Origin", "https://example.com")
	r.Header.Set("Access-Control-Request-Method", "GET")
	r.Header.Set("Access-Control-Request-Headers", "authorization,content-type")
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Code != 204 || w.Header().Get("Access-Control-Allow-Origin") != "*" || !strings.Contains(w.Header().Get("Access-Control-Allow-Headers"), "authorization") {
		t.Fatal("API preflight contract lost")
	}
	r = httptest.NewRequest("GET", "/api/health", nil)
	r.Header.Set("Origin", "https://example.com")
	w = httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Header().Get("Access-Control-Allow-Origin") != "*" {
		t.Fatal("API CORS response lost")
	}
}

type disconnectedWriter struct{ header http.Header }

func (w *disconnectedWriter) Header() http.Header       { return w.header }
func (w *disconnectedWriter) WriteHeader(int)           {}
func (w *disconnectedWriter) Write([]byte) (int, error) { return 0, errors.New("client disconnected") }

func TestRenameRemainsCommittedIfClientDisconnects(t *testing.T) {
	a := testApp(t)
	a.insert("sessions", M{"token": "test-session", "user_id": "admin", "expires_at": "2099-01-01T00:00:00+00:00", "remember": 0, "created_at": nowISO()})
	a.insert("images", M{"id": "rename-test", "key": "old.jpg", "c_key": "old.webp", "owner_id": "admin", "mime": "image/jpeg", "width": 1, "height": 1, "size": 1, "created_at": nowISO()})
	for dir, name := range map[string]string{"uploads": "old.jpg", "thumbs": "old.jpg.webp", "compressed": "old.webp"} {
		if err := os.WriteFile(filepath.Join(a.data, dir, name), []byte("fixture"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	r := httptest.NewRequest("PATCH", "/api/images/rename-test", strings.NewReader(`{"filename":"new"}`))
	r.Header.Set("Authorization", "Bearer test-session")
	a.ServeHTTP(&disconnectedWriter{header: http.Header{}}, r)
	if a.image("rename-test")["key"] != "new.jpg" {
		t.Fatal("rename did not commit")
	}
	for dir, name := range map[string]string{"uploads": "new.jpg", "thumbs": "new.jpg.webp", "compressed": "new.webp"} {
		if !exists(filepath.Join(a.data, dir, name)) {
			t.Fatalf("committed file reverted after network error: %s", dir)
		}
	}
}

func TestInternalImportQueueDoesNotInflateSettingsPayload(t *testing.T) {
	a := testApp(t)
	a.updateSettings(map[string]string{"local_import_failed": strings.Repeat("x", 100000), "notify_last_daily": "2026-10-23"})
	settings := a.adminSettings()
	if _, ok := settings["local_import_failed"]; ok {
		t.Fatal("internal queue leaked into settings form")
	}
	if _, ok := settings["notify_last_daily"]; ok {
		t.Fatal("report bookkeeping leaked into settings form")
	}
	payload, err := json.Marshal(settings)
	if err != nil || len(payload) > 65536 {
		t.Fatal("settings form exceeds JSON request limit")
	}
}

func TestRestoreRejectsBusyImportWithoutBlockingReaders(t *testing.T) {
	a := testApp(t)
	a.setJob(M{"running": true})
	a.dataMu.RLock()
	defer a.dataMu.RUnlock()
	done := make(chan int, 1)
	go func() {
		w := httptest.NewRecorder()
		a.ServeHTTP(w, httptest.NewRequest("POST", "/api/admin/restore", nil))
		done <- w.Code
	}()
	select {
	case code := <-done:
		if code != 409 {
			t.Fatalf("status %d", code)
		}
	case <-time.After(time.Second):
		t.Fatal("restore blocked behind active importer")
	}
}

func TestWebhookJSONTemplateEscapesMultilineFields(t *testing.T) {
	payload, err := renderNotifyJSON(`{"title":"{{title}}","text":"{{text}}","fields":{{fields}},"missing":"{{unused}}"}`, M{"title": `quoted "title"`, "text": "line one\nline two", "fields": `{"reason":"quote\" and newline\n"}`})
	if err != nil {
		t.Fatal(err)
	}
	var decoded M
	if json.Unmarshal(payload, &decoded) != nil || decoded["text"] != "line one\nline two" || decoded["title"] != `quoted "title"` {
		t.Fatalf("invalid substitution: %s", payload)
	}
	if _, ok := decoded["fields"].(map[string]any); !ok {
		t.Fatal("fields placeholder is not a JSON object")
	}
	if _, err = renderNotifyJSON(`not json {{text}}`, M{"text": "value"}); err == nil {
		t.Fatal("invalid JSON template accepted")
	}
}

func TestAdministratorQuotaMatchesUnlimitedUploadPolicy(t *testing.T) {
	a := testApp(t)
	a.update("users", "id", "admin", M{"quota_mb": 1, "max_upload_mb": 1, "daily_limit": 1})
	u := a.publicUser(a.one("SELECT * FROM users WHERE id='admin'"))
	if num(u["quotaMb"]) != 0 || num(u["remainingBytes"]) != -1 || num(u["maxUploadMb"]) != 0 {
		t.Fatal("administrator UI still exposes business upload limits")
	}
	a.saveSettings(M{"comp_profile": "custom"})
	if a.effective()["label"] != "自定义方案" {
		t.Fatal("custom profile mislabeled as a preset")
	}
}
