package main

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPasswordChangesRevokeOnlyTargetSessions(t *testing.T) {
	a := testApp(t)
	u := a.one("SELECT * FROM users WHERE role='admin'")
	for _, token := range []string{"fixture-one", "fixture-two"} {
		a.insert("sessions", M{"token": token, "user_id": u["id"], "expires_at": "2099-01-01T00:00:00+00:00", "remember": 1, "created_at": nowISO()})
	}
	call := func(body string) int {
		r := httptest.NewRequest("POST", "/api/auth/password", strings.NewReader(body))
		r.Header.Set("Authorization", "Bearer fixture-one")
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		return w.Code
	}
	if call(`{"old":"wrong","new":"replacement"}`) != 401 || a.tokenUser("fixture-two") == nil {
		t.Fatal("wrong password revoked valid session")
	}
	if call(`{"old":"test-password","new":"replacement"}`) != 200 {
		t.Fatal("password update failed")
	}
	if a.tokenUser("fixture-one") != nil || a.tokenUser("fixture-two") != nil {
		t.Fatal("old sessions survived")
	}
	if !verify("replacement", str(a.one("SELECT pwd FROM users WHERE id=?", u["id"])["pwd"])) {
		t.Fatal("password not changed")
	}
	// The same atomic helper is used by administrator resets.
	a.insert("sessions", M{"token": "reset-fixture", "user_id": u["id"], "expires_at": "2099-01-01T00:00:00+00:00", "remember": 1, "created_at": nowISO()})
	a.updateAccount(u["id"], M{"pwd": password("reset-value")})
	if a.tokenUser("reset-fixture") != nil {
		t.Fatal("reset left session valid")
	}
	a.insert("sessions", M{"token": "rescue-fixture", "user_id": u["id"], "expires_at": "2099-01-01T00:00:00+00:00", "remember": 1, "created_at": nowISO()})
	t.Setenv("ADMIN_SYNC", "1")
	t.Setenv("ADMIN_PASSWORD", "rescue-replacement")
	a.initDB(true)
	if a.tokenUser("rescue-fixture") != nil {
		t.Fatal("startup rescue retained session")
	}
}
