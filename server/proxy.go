package main

import (
	"net/http"
	"os"
	"strings"
)

func requestHTTPS(r *http.Request) bool {
	if r.TLS != nil || os.Getenv("PUBLIC_HTTPS") == "1" {
		return true
	}
	for _, pat := range strings.Split(os.Getenv("TRUSTED_PROXIES"), ",") {
		if matchIP(remoteIP(r), strings.TrimSpace(pat)) {
			return strings.EqualFold(r.Header.Get("X-Forwarded-Proto"), "https")
		}
	}
	return false
}
