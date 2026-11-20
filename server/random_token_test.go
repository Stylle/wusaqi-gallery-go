package main

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPublicRandomFollowsSiteAccessWithoutSecondarySwitch(t *testing.T) {
	a := testApp(t)
	privacyImage(a, "visible", "cats")
	privacyImage(a, "hidden", privateTag)
	a.updateSettings(map[string]string{"site_public": "1", "random_public": "0"})
	if w := privacyRequest(a, "GET", "/api/random", "", ""); w.Code != 200 {
		t.Fatal("public random still requires login")
	}
	if w := privacyRequest(a, "GET", "/api/random/image", "", ""); w.Code != 302 {
		t.Fatal("public random image unavailable")
	}
	if privacyRequest(a, "GET", "/api/random?tag=私密", "", "").Code != 404 {
		t.Fatal("private image leaked")
	}
	a.updateSettings(map[string]string{"external_disabled_tags": `["cats"]`})
	if privacyRequest(a, "GET", "/api/random", "", "").Code != 404 {
		t.Fatal("disabled external tag bypassed")
	}
	a.updateSettings(map[string]string{"external_links_enabled": "0"})
	if privacyRequest(a, "GET", "/api/random", "", "").Code != 403 {
		t.Fatal("external switch bypassed")
	}
}
func TestPersonalRandomLinkWorksWithoutCookiesAndIsReadOnly(t *testing.T) {
	a := testApp(t)
	privacyImage(a, "visible", "cats")
	privacyImage(a, "hidden", privateTag)
	privacySession(a, "admin", "login-session")
	a.updateSettings(map[string]string{"site_public": "0"})
	w := privacyRequest(a, "GET", "/api/auth/random-token", "", "login-session")
	var data M
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &data) != nil {
		t.Fatal("personal credential unavailable")
	}
	token := str(data["token"])
	if token == "" || token == "login-session" {
		t.Fatal("login session reused as URL credential")
	}
	if privacyRequest(a, "GET", "/api/random", "", "").Code != 401 {
		t.Fatal("private site open to anonymous")
	}
	w = privacyRequest(a, "GET", "/api/random/image?variant=compressed&token="+token, "", "")
	if w.Code != 302 || !strings.HasPrefix(w.Header().Get("Location"), "/media/compressed/visible.webp?") {
		t.Fatal("personal redirect failed")
	}
	if privacyRequest(a, "GET", w.Header().Get("Location"), "", "").Code != 200 {
		t.Fatal("personal image depends on cookies")
	}
	if privacyRequest(a, "GET", "/media/files/hidden.png?random_token="+token, "", "").Code != 404 {
		t.Fatal("read credential acquired private-image access")
	}
	if privacyRequest(a, "GET", "/api/random?token="+token+"&tag=私密&include_private=1", "", "").Code != 404 {
		t.Fatal("private filter bypassed")
	}
	for _, path := range []string{"/api/auth/me", "/api/admin/settings", "/api/images"} {
		if privacyRequest(a, "GET", path+"?token="+token, "", "").Code != 401 {
			t.Fatal("random token became a login")
		}
	}
	if privacyRequest(a, "PUT", "/api/admin/settings", `{"site_public":"1"}`, token).Code != 401 {
		t.Fatal("random token authorized settings mutation")
	}
	if privacyRequest(a, "GET", "/api/random?token="+token+"x", "", "").Code != 401 {
		t.Fatal("tampered token accepted")
	}
	if a.count("SELECT COUNT(*) FROM visits WHERE path LIKE '%token=%'") != 0 {
		t.Fatal("credential stored in visit log")
	}
	a.updateAccount("admin", M{"pwd": password("new-test-password")})
	if privacyRequest(a, "GET", "/api/random?token="+token, "", "").Code != 401 {
		t.Fatal("password change did not revoke random token")
	}
}
func TestRandomTokenRespectsAccountDisableAndDeletion(t *testing.T) {
	a := testApp(t)
	privacyImage(a, "visible", "cats")
	a.updateSettings(map[string]string{"site_public": "0"})
	u := a.one("SELECT * FROM users WHERE id='admin'")
	token := a.randomToken(u)
	a.exec("UPDATE users SET enabled=0 WHERE id='admin'")
	if privacyRequest(a, "GET", "/api/random?token="+token, "", "").Code != 401 {
		t.Fatal("disabled account still accesses random")
	}
	a.exec("DELETE FROM users WHERE id='admin'")
	if privacyRequest(a, "GET", "/api/random?token="+token, "", "").Code != 401 {
		t.Fatal("deleted account still accesses random")
	}
}
func TestPublicSettingsAdvertiseEffectiveRandomAccess(t *testing.T) {
	a := testApp(t)
	a.updateSettings(map[string]string{"site_public": "1", "random_public": "0"})
	w := httptest.NewRecorder()
	a.ServeHTTP(w, httptest.NewRequest("GET", "/api/public/settings", nil))
	var data M
	json.Unmarshal(w.Body.Bytes(), &data)
	if data["random_public"] != "1" {
		t.Fatal("legacy frontend sees a stale random gate")
	}
}
