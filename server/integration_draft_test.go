package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestGalleryDraftIntegrationsDoNotPersist(t *testing.T) {
	a := testApp(t)
	hits := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		if strings.HasSuffix(r.URL.Path, "getMe") {
			fmt.Fprint(w, `{"ok":true,"result":{"username":"FixtureBot","id":1}}`)
		} else {
			fmt.Fprint(w, `{"ok":true,"result":{"message_id":1}}`)
		}
	}))
	defer srv.Close()
	before := a.settings()
	a.telegram.client = srv.Client()
	a.telegram.baseURL = srv.URL
	raw, _ := json.Marshal(M{"webhook_url": srv.URL, "notify_method": "POST", "notify_body_type": "json", "notify_headers": "{}", "notify_body_tpl": ""})
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/api/admin/notify/test", strings.NewReader(string(raw)))
	a.testNotifyDraft(w, r)
	if w.Code != 200 || hits != 1 {
		t.Fatal("draft webhook failed", w.Code)
	}
	after := a.settings()
	for _, k := range []string{"webhook_url", "telegram_enabled", "telegram_bot_token", "_telegram_bindings"} {
		if before[k] != after[k] {
			t.Fatal("test changed saved configuration")
		}
	}
}
