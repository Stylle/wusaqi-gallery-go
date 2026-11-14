package main

import (
	probe "github.com/Stylle/wusaqi-gallery-go/server/internal/integrationtest"
	"net/http"
)

func (a *App) testNotifyDraft(w http.ResponseWriter, r *http.Request) {
	v, e := probe.Read(r.Body)
	if e != nil {
		fail(400, e.Error())
	}
	s := a.settings()
	for _, k := range []string{"webhook_url", "notify_method", "notify_body_type", "notify_headers", "notify_body_tpl"} {
		value, e := probe.String(v, k, s[k])
		if e != nil {
			fail(400, e.Error())
		}
		s[k] = value
	}
	if s["notify_method"] != "GET" && s["notify_method"] != "POST" && s["notify_method"] != "PUT" {
		fail(400, "Webhook 方法仅支持 GET/POST/PUT")
	}
	if s["notify_body_type"] != "json" && s["notify_body_type"] != "text" {
		fail(400, "正文类型无效")
	}
	ok, message := a.sendNotifySettings(notification{"test", "图床 · 当前表单 Webhook 测试（未保存配置）", M{}}, s)
	respond(w, M{"ok": ok, "error": message, "persisted": false})
}
