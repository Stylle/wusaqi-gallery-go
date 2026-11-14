package main

import (
	"bytes"
	"context"
	"encoding/json"
	"image"
	"image/png"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

const testTelegramToken = "123456:abcdefghijklmnopqrstuvwxyz_123456789"

func telegramSetup(t *testing.T) *App {
	t.Helper()
	a := testApp(t)
	a.updateSettings(map[string]string{"telegram_enabled": "1", "telegram_bot_token": testTelegramToken, "_telegram_bindings": `{"1234567890123":"admin","42":"member"}`})
	a.insert("users", M{"id": "member", "username": "member", "role": "user", "pwd": "unused", "enabled": 1, "created_at": nowISO()})
	a.telegram.state("GalleryBot", nil)
	return a
}

func telegramMsg(text string, sender int64) *telegramMessage {
	m := &telegramMessage{Text: text, Date: time.Now().Unix()}
	m.From.ID, m.Chat.ID, m.Chat.Type = sender, sender, "private"
	return m
}

type telegramSent struct {
	method, caption, chat, protect, filename string
	data                                     []byte
}

func telegramCapture(t *testing.T, a *App) *[]telegramSent {
	t.Helper()
	sent := []telegramSent{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := telegramSent{method: filepath.Base(r.URL.Path)}
		if v.method == "setMyCommands" || v.method == "setChatMenuButton" {
			respond(w, M{"ok": true, "result": true})
			return
		}
		if strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/") {
			raw, err := io.ReadAll(r.Body)
			if err != nil || int64(len(raw)) != r.ContentLength {
				t.Error("file stream content length mismatch", err)
			}
			r.Body = io.NopCloser(bytes.NewReader(raw))
			if err = r.ParseMultipartForm(1 << 20); err != nil {
				t.Error("invalid multipart", err)
			} else {
				v.caption, v.chat, v.protect = r.FormValue("caption"), r.FormValue("chat_id"), r.FormValue("protect_content")
				for _, files := range r.MultipartForm.File {
					for _, f := range files {
						v.filename = f.Filename
						file, _ := f.Open()
						v.data, _ = io.ReadAll(file)
						file.Close()
					}
				}
				r.MultipartForm.RemoveAll()
			}
		} else {
			var payload map[string]any
			_ = json.NewDecoder(r.Body).Decode(&payload)
			v.caption, v.chat = str(payload["text"]), str(payload["chat_id"])
		}
		sent = append(sent, v)
		respond(w, M{"ok": true, "result": M{}})
	}))
	a.telegram.baseURL = srv.URL
	t.Cleanup(srv.Close)
	return &sent
}

func telegramPNG(t *testing.T, a *App, name, tag string) []byte {
	t.Helper()
	privacyImage(a, name, tag)
	var raw bytes.Buffer
	must(png.Encode(&raw, image.NewRGBA(image.Rect(0, 0, 16, 12))))
	must(os.WriteFile(filepath.Join(a.data, "uploads", name+".png"), raw.Bytes(), 0600))
	return raw.Bytes()
}

func TestTelegramAdminAPIAndWriteOnlyToken(t *testing.T) {
	a := telegramSetup(t)
	privacySession(a, "admin", "admin-session")
	privacySession(a, "member", "member-session")
	for _, path := range []string{"/api/admin/telegram/status", "/api/admin/telegram/pair", "/api/admin/telegram/unbind", "/api/admin/telegram/token/clear"} {
		method := "POST"
		if strings.HasSuffix(path, "/status") {
			method = "GET"
		}
		for _, token := range []string{"", "member-session"} {
			w := privacyRequest(a, method, path, `{}`, token)
			if w.Code != 401 && w.Code != 403 {
				t.Fatalf("non-admin reached %s: %d", path, w.Code)
			}
		}
	}
	for _, path := range []string{"/api/admin/settings", "/api/admin/telegram/status", "/api/public/settings"} {
		w := privacyRequest(a, "GET", path, "", "admin-session")
		if w.Code != 200 || strings.Contains(w.Body.String(), testTelegramToken) || strings.Contains(w.Body.String(), "abcdefghijklmnopqrstuvwxyz") {
			t.Fatal("token exposed in API response", path)
		}
	}
	a.saveSettings(M{"telegram_bot_token": "", "site_title": "Updated"})
	if a.settings()["telegram_bot_token"] != testTelegramToken || a.adminSettings()["telegram_bot_token"] != "" {
		t.Fatal("blank input replaced secret or secret was echoed")
	}
	w := privacyRequest(a, "PUT", "/api/admin/settings", `{"telegram_bot_token":"invalid","site_title":"bad"}`, "admin-session")
	if w.Code != 400 || a.settings()["site_title"] != "Updated" {
		t.Fatal("invalid token partially saved settings")
	}
	w = privacyRequest(a, "POST", "/api/admin/telegram/token/clear", `{}`, "admin-session")
	if w.Code != 200 || a.settings()["telegram_bot_token"] != "" || a.settings()["telegram_enabled"] != "0" || len(telegramBindings(a.settings())) != 0 {
		t.Fatal("explicit token removal did not disable and revoke")
	}
}

func TestTelegramPairingIsPrivateSingleUseAndExpires(t *testing.T) {
	a := telegramSetup(t)
	sent := telegramCapture(t, a)
	privacySession(a, "admin", "admin-session")
	pair := func() string {
		w := privacyRequest(a, "POST", "/api/admin/telegram/pair", `{}`, "admin-session")
		var result M
		_ = json.Unmarshal(w.Body.Bytes(), &result)
		if w.Code != 200 {
			t.Fatal("could not pair")
		}
		return str(result["command"])
	}
	command := pair()
	group := telegramMsg(command, 99)
	group.Chat.Type, group.Chat.ID = "group", -100
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", group))
	if a.telegram.bind(context.Background(), testTelegramToken, 99, "invalid") || len(*sent) != 0 {
		t.Fatal("group or bad code bound an account")
	}
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg(command, 99)))
	if telegramBindings(a.settings())["99"] != "admin" || len(*sent) != 1 {
		t.Fatal("valid private pairing failed")
	}
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg(command, 100)))
	if telegramBindings(a.settings())["100"] != "" || len(*sent) != 1 {
		t.Fatal("code reused")
	}
	old := pair()
	command = pair()
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg(old, 100)))
	a.telegram.pairExp = time.Now().Add(-time.Second)
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg(command, 100)))
	if telegramBindings(a.settings())["100"] != "" {
		t.Fatal("replaced or expired code worked")
	}
	command = pair()
	a.exec("UPDATE users SET role='user' WHERE id='admin'")
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg(command, 100)))
	if telegramBindings(a.settings())["100"] != "" {
		t.Fatal("demoted administrator could bind")
	}
}

func TestTelegramIgnoresOrdinaryUsersGroupsStaleAndDisabledAdmins(t *testing.T) {
	a := telegramSetup(t)
	sent := telegramCapture(t, a)
	telegramPNG(t, a, "public", "风景")
	for _, text := range []string{"/random", "/random 风景", "/tags", "/help", "/start", "/bind bad"} {
		for _, sender := range []int64{42, 777} {
			must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg(text, sender)))
		}
	}
	for _, modify := range []func(*telegramMessage){
		func(m *telegramMessage) { m.Chat.Type, m.Chat.ID = "supergroup", -1 },
		func(m *telegramMessage) { m.From.IsBot = true },
		func(m *telegramMessage) { m.Chat.ID++ },
		func(m *telegramMessage) { m.Date -= 180 },
		func(m *telegramMessage) { m.Text = "/random@AnotherBot" },
	} {
		msg := telegramMsg("/random", 1234567890123)
		modify(msg)
		must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", msg))
	}
	if len(*sent) != 0 {
		t.Fatal("unauthorized request caused an outgoing bot reply")
	}
	for _, stmt := range []string{"UPDATE users SET enabled=0 WHERE id='admin'", "UPDATE users SET enabled=1,role='user' WHERE id='admin'", "DELETE FROM users WHERE id='admin'"} {
		a.exec(stmt)
		must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg("/random", 1234567890123)))
	}
	if len(*sent) != 0 {
		t.Fatal("inactive administrator retained access")
	}
}

func TestTelegramTagMatchingPrivateOptInAndNoPublicLinks(t *testing.T) {
	a := telegramSetup(t)
	sent := telegramCapture(t, a)
	public := telegramPNG(t, a, "public", "夏日 海边")
	secret := telegramPNG(t, a, "secret", privateTag)
	a.updateSettings(map[string]string{"site_public": "0", "external_links_enabled": "0"})
	call := func(text string) telegramSent {
		before := len(*sent)
		must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg(text, 1234567890123)))
		if len(*sent) != before+1 {
			t.Fatalf("command not answered: %s", text)
		}
		return (*sent)[before]
	}
	v := call("/random@gallerybot 夏日 海边")
	if v.method != "sendPhoto" || !bytes.Equal(v.data, public) || v.chat != "1234567890123" || v.filename != "public.png" {
		t.Fatal("exact tag or photo stream failed", v)
	}
	if v = call("/random 夏日"); v.method != "sendMessage" {
		t.Fatal("partial tag unexpectedly matched")
	}
	if v = call("/random ' OR 1=1 --"); v.method != "sendMessage" {
		t.Fatal("tag was interpolated into SQL")
	}
	if v = call("/tags"); strings.Contains(v.caption, privateTag) || !strings.Contains(v.caption, "夏日 海边") {
		t.Fatal("private tag leaked in list or normal tag missing")
	}
	if v = call("/random 私密"); v.method != "sendMessage" || len(v.data) != 0 {
		t.Fatal("private opt-in was bypassed")
	}
	a.updateSettings(map[string]string{"telegram_include_private": "1"})
	if v = call("/random 私密"); v.method != "sendPhoto" || !bytes.Equal(v.data, secret) || v.protect != "true" {
		t.Fatal("explicit private sending failed")
	}
	for i := 0; i < 5; i++ {
		if v = call("/random"); v.filename != "public.png" {
			t.Fatal("unfiltered random selected private image")
		}
	}
	if v = call("/tags"); !strings.Contains(v.caption, privateTag) {
		t.Fatal("allowed private tag missing")
	}
	privacySession(a, "admin", "admin-session")
	w := privacyRequest(a, "POST", "/api/admin/telegram/unbind", `{"telegramId":"1234567890123"}`, "admin-session")
	before := len(*sent)
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg("/random", 1234567890123)))
	if w.Code != 200 || len(*sent) != before {
		t.Fatal("revoked binding retained access")
	}
}

func TestTelegramMissingOriginalAndDocumentFallback(t *testing.T) {
	a := telegramSetup(t)
	sent := telegramCapture(t, a)
	privacyImage(a, "webp", "only")
	_ = os.Remove(filepath.Join(a.data, "uploads", "webp.png"))
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg("/random only", 1234567890123)))
	if (*sent)[0].method != "sendMessage" {
		t.Fatal("orphan compressed file sent without original")
	}
	must(os.WriteFile(filepath.Join(a.data, "uploads", "webp.png"), []byte("not-a-supported-photo"), 0600))
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg("/random only", 1234567890123)))
	if (*sent)[1].method != "sendDocument" || (*sent)[1].filename != "webp.webp" || string((*sent)[1].data) != "payload" {
		t.Fatal("document fallback failed")
	}
	file, err := os.Create(filepath.Join(a.data, "compressed", "webp.webp"))
	must(err)
	must(file.Truncate(51 * 1024 * 1024))
	file.Close()
	file, err = os.OpenFile(filepath.Join(a.data, "uploads", "webp.png"), os.O_WRONLY, 0600)
	must(err)
	must(file.Truncate(51 * 1024 * 1024))
	file.Close()
	must(a.telegram.handle(context.Background(), testTelegramToken, "GalleryBot", telegramMsg("/random only", 1234567890123)))
	if (*sent)[2].method != "sendMessage" {
		t.Fatal("oversize image was uploaded")
	}
}

func TestTelegramErrorsNeverExposeCredentialsOrFollowRedirects(t *testing.T) {
	a := telegramSetup(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(401)
		respond(w, M{"ok": false, "error_code": 401, "description": testTelegramToken})
	}))
	a.telegram.baseURL = srv.URL
	err := a.telegram.call(context.Background(), testTelegramToken, "getMe", M{}, nil)
	if err == nil || strings.Contains(err.Error(), testTelegramToken) {
		t.Fatal("API error exposed token")
	}
	srv.Close()
	err = a.telegram.call(context.Background(), testTelegramToken, "getMe", M{}, nil)
	if err == nil || strings.Contains(err.Error(), testTelegramToken) || strings.Contains(err.Error(), srv.URL) {
		t.Fatal("transport error exposed token or URL")
	}
	var redirected bool
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { redirected = true }))
	defer target.Close()
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, 307) }))
	defer srv.Close()
	a.telegram.baseURL = srv.URL
	err = a.telegram.call(context.Background(), testTelegramToken, "getMe", M{}, nil)
	if err == nil || redirected {
		t.Fatal("secret request followed a redirect")
	}
}

func TestTelegramLongPollingCheckpointRestartAndShutdown(t *testing.T) {
	a := telegramSetup(t)
	telegramPNG(t, a, "public", "风景")
	var mu sync.Mutex
	var offsets []int64
	polling := make(chan struct{}, 10)
	imageSent := make(chan struct{}, 2)
	updates := make(chan telegramUpdate, 2)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch filepath.Base(r.URL.Path) {
		case "setMyCommands", "setChatMenuButton":
			respond(w, M{"ok": true, "result": true})
		case "getMe":
			respond(w, M{"ok": true, "result": M{"username": "GalleryBot", "is_bot": true}})
		case "getUpdates":
			var v M
			_ = json.NewDecoder(r.Body).Decode(&v)
			offset := num(v["offset"])
			mu.Lock()
			offsets = append(offsets, offset)
			mu.Unlock()
			if offset == -1 {
				respond(w, M{"ok": true, "result": []telegramUpdate{{ID: 99, Message: telegramMsg("/random", 1234567890123)}}})
				return
			}
			polling <- struct{}{}
			select {
			case update := <-updates:
				respond(w, M{"ok": true, "result": []telegramUpdate{update}})
			case <-r.Context().Done():
			}
		case "sendPhoto":
			_, _ = io.Copy(io.Discard, r.Body)
			imageSent <- struct{}{}
			respond(w, M{"ok": true, "result": M{}})
		default:
			t.Error("unexpected Bot API call", r.URL.Path)
		}
	}))
	defer srv.Close()
	a.telegram.baseURL = srv.URL
	wait := func(ch <-chan struct{}) {
		t.Helper()
		select {
		case <-ch:
		case <-time.After(4 * time.Second):
			t.Fatal("bot did not reach expected state")
		}
	}
	a.workerWG.Add(1)
	go a.telegram.run()
	t.Cleanup(func() { a.workerCancel(); a.workerWG.Wait() })
	wait(polling)
	if len(imageSent) != 0 {
		t.Fatal("cold-start backlog executed")
	}
	updates <- telegramUpdate{ID: 100, Message: telegramMsg("/random 风景", 1234567890123)}
	wait(imageSent)
	wait(polling)
	a.dataMu.RLock()
	offset := a.settings()["_telegram_offset"]
	a.dataMu.RUnlock()
	if offset != "101" {
		t.Fatal("offset not persisted before sending", offset)
	}
	a.telegram.changed() // Simulate restart with the same persisted config.
	wait(polling)
	mu.Lock()
	last := offsets[len(offsets)-1]
	mu.Unlock()
	if last != 101 || len(imageSent) != 0 {
		t.Fatal("restart replayed updates or discarded persisted cursor")
	}
	start := time.Now()
	a.workerCancel()
	a.workerWG.Wait()
	if time.Since(start) > 2*time.Second {
		t.Fatal("shutdown waited for long poll timeout")
	}
}
