package main

import "testing"

func TestPersonalCopiedMediaWorksWithoutPublicAccess(t *testing.T) {
	a := testApp(t)
	privacyImage(a, "copyable", "cats")
	privacyImage(a, "private", privateTag)
	u := a.one("SELECT * FROM users WHERE id='admin'")
	a.updateSettings(map[string]string{"site_public": "0", "external_links_enabled": "0"})
	item := a.itemJSON(a.one("SELECT * FROM images WHERE key='copyable.png'"), u)
	links := item["personalUrls"].(M)
	if len(links) != 3 || len(item["shareUrls"].(M)) != 0 {
		t.Fatal("personal and anonymous links were not separated")
	}
	for _, value := range links {
		p := str(value)
		if privacyRequest(a, "GET", p, "", "").Code != 200 {
			t.Fatal("personal media cannot be opened without a session cookie")
		}
		if privacyRequest(a, "HEAD", p, "", "").Code != 200 {
			t.Fatal("personal media HEAD denied")
		}
	}
	if len(a.itemJSON(a.one("SELECT * FROM images WHERE key='private.png'"), u)["personalUrls"].(M)) != 0 {
		t.Fatal("private image exposed through personal copy")
	}
	if len(a.itemJSON(a.one("SELECT * FROM images WHERE key='copyable.png'"), nil)["personalUrls"].(M)) != 0 {
		t.Fatal("anonymous response contains personal token")
	}
	a.exec("UPDATE users SET pwd='changed' WHERE id='admin'")
	for _, value := range links {
		if privacyRequest(a, "GET", str(value), "", "").Code != 404 {
			t.Fatal("old copied URL survived password change")
		}
	}
}
