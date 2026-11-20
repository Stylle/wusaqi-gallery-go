package main

import (
	"crypto/hmac"
	"encoding/base64"
	"net/http"
	"strings"
)

// Random links have a read-only credential, never the account's login session.
// Bound to the password hash and site secret so resets, disablement and deletion revoke it.
func (a *App) randomToken(u M) string {
	uid := str(u["id"])
	return "r1." + base64.RawURLEncoding.EncodeToString([]byte(uid)) + "." + viewerSignature("random-read:"+uid+":"+str(u["pwd"]), a.settings()["_viewer_secret"])
}
func (a *App) randomTokenUser(token string) M {
	if len(token) > 512 {
		return nil
	}
	parts := strings.Split(token, ".")
	if len(parts) != 3 || parts[0] != "r1" {
		return nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil || len(raw) == 0 || len(raw) > 128 {
		return nil
	}
	u := a.one("SELECT * FROM users WHERE id=? AND COALESCE(enabled,1)=1", string(raw))
	if u == nil {
		return nil
	}
	if !hmac.Equal([]byte(a.randomToken(u)), []byte(token)) {
		return nil
	}
	// The personal endpoint cannot acquire admin/private-image privileges.
	u["role"] = "user"
	return u
}
func (a *App) randomRequestUser(r *http.Request) M {
	if u := a.user(r); u != nil {
		return u
	}
	if r.Method == "GET" && (r.URL.Path == "/api/random" || r.URL.Path == "/api/random/image") {
		return a.randomTokenUser(r.URL.Query().Get("token"))
	}
	return nil
}
func randomMediaURL(path, token string) string {
	if token == "" || path == "" {
		return path
	}
	separator := "?"
	if strings.Contains(path, "?") {
		separator = "&"
	}
	return path + separator + "random_token=" + token
}
