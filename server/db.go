package main

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

// The schema, settings keys and password encoding match the Python release.
//
//go:embed schema.sql
var schema string

//go:embed indexes.sql
var indexes string

//go:embed defaults.json
var defaultsJSON []byte

//go:embed profiles.json
var profilesJSON []byte

type M = map[string]any
type apiError struct {
	status  int
	message string
}

func fail(status int, message string) { panic(apiError{status, message}) }
func must(err error) {
	if err != nil {
		panic(err)
	}
}
func str(v any) string {
	if v == nil {
		return ""
	}
	return fmt.Sprint(v)
}
func num(v any) int64             { n, _ := strconv.ParseFloat(str(v), 64); return int64(n) }
func clamp(n, lo, hi int64) int64 { return max(lo, min(hi, n)) }
func truth(v any) bool {
	s := strings.ToLower(str(v))
	return s == "1" || s == "true" || s == "on" || s == "yes" || s == "y" || s == "t"
}
func env(k, fallback string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return fallback
}
func adminUsername() string {
	name := strings.TrimSpace(env("ADMIN_USERNAME", "admin"))
	if name == "" {
		return "admin"
	}
	return name
}
func nowISO() string { return time.Now().UTC().Format("2006-01-02T15:04:05+00:00") }
func since(days int) string {
	return time.Now().UTC().Add(-time.Duration(days) * 24 * time.Hour).Format("2006-01-02T15:04:05+00:00")
}
func id(n int) string {
	b := make([]byte, n)
	_, err := rand.Read(b)
	must(err)
	return hex.EncodeToString(b)
}
func password(pw string) string {
	salt := id(16)
	raw, _ := hex.DecodeString(salt)
	dk, err := pbkdf2.Key(sha256.New, pw, raw, 200000, 32)
	must(err)
	return fmt.Sprintf("pbkdf2_sha256$200000$%s$%x", salt, dk)
}
func verify(pw, stored string) bool {
	p := strings.Split(stored, "$")
	if len(p) != 4 || p[0] != "pbkdf2_sha256" {
		return false
	}
	it, err := strconv.Atoi(p[1])
	if err != nil || it < 1 || it > 10000000 {
		return false
	}
	salt, e := hex.DecodeString(p[2])
	if e != nil {
		return false
	}
	dk, e := pbkdf2.Key(sha256.New, pw, salt, it, 32)
	if e != nil {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(hex.EncodeToString(dk)), []byte(p[3])) == 1
}

func openDB(path string) *sql.DB {
	d, err := sql.Open("sqlite", path)
	must(err)
	// One connection bounds SQLite's per-connection page cache and serializes SQL.
	d.SetMaxOpenConns(1)
	d.SetMaxIdleConns(1)
	for _, q := range []string{"PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=15000", "PRAGMA foreign_keys=ON", "PRAGMA cache_size=-2048", "PRAGMA mmap_size=0", "PRAGMA temp_store=FILE"} {
		_, err = d.Exec(q)
		must(err)
	}
	return d
}
func (a *App) exec(q string, args ...any) sql.Result {
	r, e := a.db.Exec(q, args...)
	must(e)
	return r
}
func (a *App) rows(q string, args ...any) []M {
	rows, e := a.db.Query(q, args...)
	must(e)
	defer rows.Close()
	cols, e := rows.Columns()
	must(e)
	out := []M{}
	for rows.Next() {
		vals := make([]any, len(cols))
		ptr := make([]any, len(cols))
		for i := range vals {
			ptr[i] = &vals[i]
		}
		must(rows.Scan(ptr...))
		m := M{}
		for i, k := range cols {
			if b, ok := vals[i].([]byte); ok {
				m[k] = string(b)
			} else {
				m[k] = vals[i]
			}
		}
		out = append(out, m)
	}
	must(rows.Err())
	return out
}
func (a *App) one(q string, args ...any) M {
	r := a.rows(q, args...)
	if len(r) == 0 {
		return nil
	}
	return r[0]
}
func (a *App) count(q string, args ...any) int64 {
	r := a.one(q, args...)
	for _, v := range r {
		return num(v)
	}
	return 0
}
func (a *App) settings() map[string]string {
	s := map[string]string{}
	for _, r := range a.rows("SELECT k,v FROM settings") {
		s[str(r["k"])] = str(r["v"])
	}
	return s
}
func (a *App) updateSettings(p map[string]string) {
	tx, e := a.db.Begin()
	must(e)
	defer tx.Rollback()
	for k, v := range p {
		_, e = tx.Exec("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", k, v)
		must(e)
	}
	must(tx.Commit())
}
func (a *App) update(table, key string, value any, fields M) {
	if len(fields) == 0 {
		return
	}
	set := []string{}
	args := []any{}
	for k, v := range fields {
		set = append(set, k+"=?")
		args = append(args, v)
	}
	args = append(args, value)
	a.exec("UPDATE "+table+" SET "+strings.Join(set, ",")+" WHERE "+key+"=?", args...)
}
func (a *App) insert(table string, fields M) {
	cols := []string{}
	ph := []string{}
	args := []any{}
	for k, v := range fields {
		cols = append(cols, k)
		ph = append(ph, "?")
		args = append(args, v)
	}
	a.exec("INSERT INTO "+table+" ("+strings.Join(cols, ",")+") VALUES ("+strings.Join(ph, ",")+")", args...)
}
func (a *App) initDB(syncAdmin bool) {
	a.exec(schema)
	for table, cols := range map[string]map[string]string{"images": {"owner_id": "TEXT", "tag": "TEXT", "orig_name": "TEXT"}, "users": {"daily_limit": "INTEGER NOT NULL DEFAULT 0", "weekly_limit": "INTEGER NOT NULL DEFAULT 0", "monthly_limit": "INTEGER NOT NULL DEFAULT 0"}} {
		existing := map[string]bool{}
		for _, r := range a.rows("PRAGMA table_info(" + table + ")") {
			existing[str(r["name"])] = true
		}
		for k, ddl := range cols {
			if !existing[k] {
				a.exec("ALTER TABLE " + table + " ADD COLUMN " + k + " " + ddl)
			}
		}
	}
	must(json.Unmarshal(defaultsJSON, &a.defaults))
	for k, v := range a.defaults {
		if k == "rate_limit" {
			v = env("RATE_LIMIT", v)
		}
		a.exec("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", k, v)
	}
	admin := a.one("SELECT * FROM users WHERE role='admin' ORDER BY created_at LIMIT 1")
	if admin == nil {
		name := adminUsername()
		for a.one("SELECT id FROM users WHERE username=?", name) != nil {
			name = "admin-" + id(4)
		}
		a.insert("users", M{"id": "admin", "username": name, "pwd": password(env("ADMIN_PASSWORD", "changeme")), "role": "admin", "quota_mb": 0, "created_at": nowISO()})
		admin = a.one("SELECT * FROM users WHERE id='admin'")
	} else if syncAdmin && truth(os.Getenv("ADMIN_SYNC")) {
		fields := M{"pwd": password(env("ADMIN_PASSWORD", "changeme"))}
		name := adminUsername()
		if a.one("SELECT id FROM users WHERE username=? AND id!=?", name, admin["id"]) == nil {
			fields["username"] = name
		}
		a.update("users", "id", admin["id"], fields)
	}
	a.exec("UPDATE images SET owner_id=? WHERE owner_id IS NULL", admin["id"])
	a.exec("UPDATE users SET enabled=1 WHERE enabled IS NULL")
	a.exec(indexes)
	a.exec("DELETE FROM sessions WHERE expires_at<=?", nowISO())
	a.purgeVisits()
}
func (a *App) purgeVisits() {
	a.exec("DELETE FROM visits WHERE day<?", time.Now().AddDate(0, 0, -3).Format("2006-01-02"))
	a.exec("DELETE FROM ip_geo WHERE checked_at<?", since(7))
	a.exec("DELETE FROM bans WHERE until_ts<=?", time.Now().Unix())
}
func pathIn(root, rel string) string {
	rel = strings.ReplaceAll(rel, "\\", "/")
	if strings.HasPrefix(rel, "/") || strings.Contains(rel, ":") {
		fail(400, "invalid path")
	}
	for _, part := range strings.Split(rel, "/") {
		if part == ".." {
			fail(400, "invalid path")
		}
	}
	full := filepath.Join(root, filepath.FromSlash(rel))
	return full
}
