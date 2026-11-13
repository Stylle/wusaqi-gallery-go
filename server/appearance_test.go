package main

import (
	"html"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestHTMLPaletteIsCurrentBeforeAppLoads(t *testing.T) {
	a := testApp(t)
	must(os.WriteFile(filepath.Join(a.web, "index.html"), []byte(`<!doctype html><html data-style="solid"><body>app</body></html>`), 0600))
	for _, palette := range []string{"solid", "gradient", "solid", `"><script>bad</script>`} {
		a.updateSettings(map[string]string{"theme_style": palette})
		expected := palette
		if expected != "gradient" {
			expected = "solid"
		}
		for _, path := range []string{"/", "/index.html", "/about"} {
			r := httptest.NewRequest("GET", path, nil)
			// A settings-only change must not incorrectly reuse cached HTML.
			r.Header.Set("If-Modified-Since", "Mon, 01 Jan 2091 00:00:00 GMT")
			w := httptest.NewRecorder()
			a.ServeHTTP(w, r)
			if w.Code != 200 || !strings.Contains(w.Body.String(), `data-style="`+expected+`"`) || strings.Contains(w.Body.String(), "<script>") {
				t.Fatalf("palette %q at %s: %d %s", palette, path, w.Code, w.Body.String())
			}
			if w.Header().Get("Cache-Control") != "no-cache" || !strings.Contains(w.Header().Get("Content-Type"), "text/html") {
				t.Fatal("HTML response headers incorrect")
			}
		}
	}
	w := privacyRequest(a, "HEAD", "/", "", "")
	if w.Code != 200 || w.Body.Len() != 0 || w.Header().Get("Content-Length") == "" {
		t.Fatal("HEAD response incorrect")
	}
}

func TestHTMLTitleIsCurrentAndEscapedBeforeAppLoads(t *testing.T) {
	a := testApp(t)
	must(os.WriteFile(filepath.Join(a.web, "index.html"), []byte(`<!doctype html><html data-style="solid"><head><title>wusaqi-gallery</title></head><body>app</body></html>`), 0600))
	for _, title := range []string{"乌索契图床", "更新后的站点 & Gallery", `</title><script>alert("x")</script>`, ""} {
		a.updateSettings(map[string]string{"site_title": title})
		for _, path := range []string{"/", "/index.html", "/about"} {
			r := httptest.NewRequest("GET", path, nil)
			r.Header.Set("If-Modified-Since", "Mon, 01 Jan 2091 00:00:00 GMT")
			w := httptest.NewRecorder()
			a.ServeHTTP(w, r)
			if w.Code != 200 || !strings.Contains(w.Body.String(), "<title>"+html.EscapeString(title)+"</title>") || strings.Contains(w.Body.String(), "<script>") {
				t.Fatalf("title %q at %s: %d %s", title, path, w.Code, w.Body.String())
			}
		}
	}
}
