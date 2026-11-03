package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func privacyRequest(a *App, method, path, payload, token string, cookies ...*http.Cookie) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(payload))
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	for _, c := range cookies {
		r.AddCookie(c)
	}
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	return w
}
func privacySession(a *App, uid, token string) {
	a.insert("sessions", M{"token": token, "user_id": uid, "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339), "created_at": nowISO(), "remember": 0})
}
func privacyImage(a *App, imageID, tag string) {
	a.insert("images", M{"id": imageID, "key": imageID + ".png", "owner_id": "member", "tag": tag, "mime": "image/png", "width": 1, "height": 1, "size": 7, "c_key": imageID + ".webp", "created_at": nowISO()})
	for dir, name := range map[string]string{"uploads": imageID + ".png", "thumbs": imageID + ".png.webp", "compressed": imageID + ".webp"} {
		must(os.WriteFile(filepath.Join(a.data, dir, name), []byte("payload"), 0600))
	}
}
func TestPrivateMediaRequiresLiveAdminAndNeverPublicShare(t *testing.T) {
	a := testApp(t)
	privacySession(a, "admin", "admin-token")
	a.insert("users", M{"id": "member", "username": "member", "pwd": "unused", "role": "user", "created_at": nowISO()})
	privacySession(a, "member", "member-token")
	privacyImage(a, "secret", privateTag)
	adminCookie := &http.Cookie{Name: mediaCookie, Value: "admin-token"}
	for _, path := range []string{"/files/secret.png", "/thumbs/secret.png.webp", "/compressed/secret.webp"} {
		for _, token := range []string{"", "member-token", "admin-token"} {
			if got := privacyRequest(a, "GET", path, "", token, adminCookie).Code; got != 404 {
				t.Fatalf("share %s leaked: %d", path, got)
			}
		}
		if privacyRequest(a, "GET", "/media"+path, "", "member-token").Code != 404 {
			t.Fatal("owner bypassed privacy")
		}
		if privacyRequest(a, "GET", "/media"+path, "", "", adminCookie).Code != 200 {
			t.Fatal("admin cannot render private media")
		}
	}
	a.exec("DELETE FROM sessions WHERE token='admin-token'")
	if privacyRequest(a, "GET", "/media/files/secret.png", "", "", adminCookie).Code != 404 {
		t.Fatal("revoked session still reads private bytes")
	}
}
func TestViewerCookieDoesNotAuthorizeAPIsAndSiteClosureRevokesIt(t *testing.T) {
	a := testApp(t)
	privacyImage(a, "public", "cats")
	w := privacyRequest(a, "GET", "/api/public/settings", "", "")
	cookies := w.Result().Cookies()
	if len(cookies) != 1 || !cookies[0].HttpOnly || cookies[0].SameSite != http.SameSiteStrictMode {
		t.Fatal("missing protected viewer cookie")
	}
	if privacyRequest(a, "GET", "/media/files/public.png", "", "").Code != 404 {
		t.Fatal("internal viewing URL became a public share")
	}
	if privacyRequest(a, "GET", "/media/files/public.png", "", "", cookies...).Code != 200 {
		t.Fatal("public gallery cannot render")
	}
	a.updateSettings(map[string]string{"external_links_enabled": "0"})
	if privacyRequest(a, "GET", "/files/public.png", "", "", cookies...).Code != 404 {
		t.Fatal("cookie bypassed share closure")
	}
	if privacyRequest(a, "GET", "/media/files/public.png", "", "", cookies...).Code != 200 {
		t.Fatal("share closure broke gallery")
	}
	privacySession(a, "admin", "admin-token")
	adminCookie := &http.Cookie{Name: mediaCookie, Value: "admin-token"}
	if privacyRequest(a, "PUT", "/api/admin/settings", `{"site_public":"1"}`, "", adminCookie).Code != 401 {
		t.Fatal("cookie authorized API mutation")
	}
	a.updateSettings(map[string]string{"site_public": "0"})
	if privacyRequest(a, "GET", "/media/files/public.png", "", "", cookies...).Code != 404 {
		t.Fatal("closed site accepts old guest cookie")
	}
	if privacyRequest(a, "GET", "/api/images", "", "").Code != 401 {
		t.Fatal("closed gallery metadata leaked")
	}
	if privacyRequest(a, "GET", "/media/files/public.png", "", "", adminCookie).Code != 200 {
		t.Fatal("closed site locked out admin media")
	}
}
func TestPrivateTagFiltersAndEditsCannotBeBypassed(t *testing.T) {
	a := testApp(t)
	a.insert("users", M{"id": "member", "username": "member", "role": "user", "pwd": "unused", "created_at": nowISO()})
	privacySession(a, "admin", "admin-token")
	privacySession(a, "member", "member-token")
	privacyImage(a, "secret", privateTag)
	privacyImage(a, "visible", "cats")
	for _, token := range []string{"", "member-token", "admin-token"} {
		w := privacyRequest(a, "GET", "/api/images", "", token)
		var v M
		must(json.Unmarshal(w.Body.Bytes(), &v))
		if num(v["total"]) != 1 {
			t.Fatal("private image visible by default")
		}
	}
	for _, path := range []string{"/api/images?include_private=1", "/api/tags?include_private=1"} {
		if strings.Contains(privacyRequest(a, "GET", path, "", "member-token").Body.String(), privateTag) {
			t.Fatal("member opted into private content")
		}
		if !strings.Contains(privacyRequest(a, "GET", path, "", "admin-token").Body.String(), privateTag) {
			t.Fatal("admin opt-in missing")
		}
	}
	for _, path := range []string{"/api/images/secret", "/api/images/batch", "/api/images/batch/download"} {
		method := "PATCH"
		if strings.HasSuffix(path, "download") {
			method = "POST"
		}
		if privacyRequest(a, method, path, `{"ids":["secret"],"tag":"cats"}`, "member-token").Code != 404 {
			t.Fatal("owner bypassed private protection: " + path)
		}
	}
	if privacyRequest(a, "PATCH", "/api/images/visible", `{"tag":"私密"}`, "member-token").Code != 403 {
		t.Fatal("member can assign private tag")
	}
}
func TestSharedDerivativeFailsClosedForMixedPrivacy(t *testing.T) {
	a := testApp(t)
	privacyImage(a, "visible", "cats")
	privacyImage(a, "secret", privateTag)
	a.exec("UPDATE images SET c_key='visible.webp' WHERE id='secret'")
	if privacyRequest(a, "GET", "/compressed/visible.webp", "", "").Code != 404 {
		t.Fatal("shared derivative exposed private bytes")
	}
}
