package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	probe "github.com/Stylle/wusaqi-gallery-go/server/internal/integrationtest"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
)

var telegramTokenPattern = regexp.MustCompile(`^[0-9]{5,20}:[A-Za-z0-9_-]{20,128}$`)

type telegramBot struct {
	a       *App
	client  *http.Client
	baseURL string // Fixed in production; tests substitute a local Bot API server.
	wake    chan struct{}
	mu      sync.Mutex
	cancel  context.CancelFunc
	bot     string
	err     string
	lastAt  string
	pair    [32]byte
	pairUID string
	pairExp time.Time
}

type telegramMessage struct {
	Date int64  `json:"date"`
	Text string `json:"text"`
	From struct {
		ID    int64 `json:"id"`
		IsBot bool  `json:"is_bot"`
	} `json:"from"`
	Chat struct {
		ID   int64  `json:"id"`
		Type string `json:"type"`
	} `json:"chat"`
}

type telegramUpdate struct {
	ID      int64            `json:"update_id"`
	Message *telegramMessage `json:"message"`
}

type telegramAPIError struct{ code, retry int }

func (e telegramAPIError) Error() string {
	switch e.code {
	case 401, 404:
		return "Telegram Token 无效或已撤销，请重新配置"
	case 409:
		return "此 Bot 正被其他轮询或 Webhook 占用，请使用独立 Bot"
	case 429:
		return "Telegram 请求过于频繁，稍后自动重连"
	}
	return fmt.Sprintf("Telegram API 请求失败（HTTP %d）", e.code)
}

func newTelegramBot(a *App) *telegramBot {
	return &telegramBot{a: a, baseURL: "https://api.telegram.org", wake: make(chan struct{}, 1),
		client: &http.Client{Timeout: 55 * time.Second,
			// A redirect must never forward a bot token or an uploaded image.
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
			Transport:     &http.Transport{Proxy: http.ProxyFromEnvironment, MaxIdleConns: 2, MaxIdleConnsPerHost: 2, IdleConnTimeout: 30 * time.Second}}}
}

func (b *telegramBot) changed() {
	b.mu.Lock()
	if b.cancel != nil {
		b.cancel()
	}
	b.bot, b.err, b.pairUID = "", "", ""
	b.mu.Unlock()
	select {
	case b.wake <- struct{}{}:
	default:
	}
}

func (b *telegramBot) state(bot string, err error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.bot, b.err = bot, ""
	if err != nil && !errors.Is(err, context.Canceled) {
		b.err = err.Error()
	}
	if err == nil && bot != "" {
		b.lastAt = nowISO()
	}
}

// Do not expose Telegram descriptions, response bodies or transport errors:
// net/url errors include the secret token embedded in the request URL.
func (b *telegramBot) request(ctx context.Context, token, method, contentType string, body io.Reader, size int64, out any) error {
	req, err := http.NewRequestWithContext(ctx, "POST", b.baseURL+"/bot"+token+"/"+method, body)
	if err != nil {
		return errors.New("Telegram 请求配置无效")
	}
	req.Header.Set("Content-Type", contentType)
	if size >= 0 {
		req.ContentLength = size
	}
	res, err := b.client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return errors.New("无法连接 Telegram，请检查出站网络或 HTTPS_PROXY")
	}
	defer res.Body.Close()
	var envelope struct {
		OK         bool            `json:"ok"`
		Result     json.RawMessage `json:"result"`
		ErrorCode  int             `json:"error_code"`
		Parameters struct {
			RetryAfter int `json:"retry_after"`
		} `json:"parameters"`
	}
	err = json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(&envelope)
	if res.StatusCode != 200 || (err == nil && !envelope.OK) {
		code := res.StatusCode
		if envelope.ErrorCode != 0 {
			code = envelope.ErrorCode
		}
		return telegramAPIError{code, min(60, max(1, envelope.Parameters.RetryAfter))}
	}
	if err != nil {
		return errors.New("Telegram 返回数据无效")
	}
	if out != nil && json.Unmarshal(envelope.Result, out) != nil {
		return errors.New("Telegram 返回数据无效")
	}
	return nil
}

func (b *telegramBot) call(ctx context.Context, token, method string, v any, out any) error {
	raw, err := json.Marshal(v)
	if err != nil {
		return errors.New("Telegram 请求参数无效")
	}
	return b.request(ctx, token, method, "application/json", bytes.NewReader(raw), int64(len(raw)), out)
}

func telegramBindings(s map[string]string) map[string]string {
	v := map[string]string{}
	_ = json.Unmarshal([]byte(s["_telegram_bindings"]), &v)
	if v == nil {
		v = map[string]string{}
	}
	return v
}

func (b *telegramBot) administrator(s map[string]string, sender int64) M {
	uid := telegramBindings(s)[strconv.FormatInt(sender, 10)]
	if uid == "" {
		return nil
	}
	return b.a.one("SELECT id,username FROM users WHERE id=? AND role='admin' AND enabled=1", uid)
}

// Called while the API holds dataMu (and writeMu for mutations).
func (b *telegramBot) route(w http.ResponseWriter, r *http.Request, u M) {
	a, p, m := b.a, r.URL.Path, r.Method
	s := a.settings()
	switch {
	case p == "/api/admin/telegram/status" && m == "GET":
		bindings := []M{}
		for sender, uid := range telegramBindings(s) {
			user := a.one("SELECT username,role,enabled FROM users WHERE id=?", uid)
			active := user != nil && user["role"] == "admin" && num(user["enabled"]) == 1
			bindings = append(bindings, M{"telegramId": sender, "username": str(user["username"]), "active": active})
		}
		sort.Slice(bindings, func(i, j int) bool { return str(bindings[i]["telegramId"]) < str(bindings[j]["telegramId"]) })
		b.mu.Lock()
		out := M{"enabled": s["telegram_enabled"] == "1", "configured": s["telegram_bot_token"] != "", "bot": b.bot, "error": b.err, "lastConnectedAt": b.lastAt, "bindings": bindings}
		b.mu.Unlock()
		respond(w, out)
	case p == "/api/admin/telegram/pair" && m == "POST":
		if s["telegram_enabled"] != "1" || s["telegram_bot_token"] == "" {
			fail(400, "请先保存 Token 并开启 Telegram 机器人")
		}
		code := id(12)
		b.mu.Lock()
		if b.bot == "" {
			b.mu.Unlock()
			fail(400, "请等待 Telegram 机器人连接成功后再绑定")
		}
		b.pair, b.pairUID, b.pairExp = sha256.Sum256([]byte(code)), str(u["id"]), time.Now().Add(5*time.Minute)
		b.mu.Unlock()
		respond(w, M{"command": "/bind " + code, "expiresIn": 300})
	case p == "/api/admin/telegram/unbind" && m == "POST":
		bindings := telegramBindings(s)
		delete(bindings, str(body(r)["telegramId"]))
		raw, _ := json.Marshal(bindings)
		a.updateSettings(map[string]string{"_telegram_bindings": string(raw)})
		b.changed()
		respond(w, M{"ok": true})
	case p == "/api/admin/telegram/token/clear" && m == "POST":
		a.updateSettings(map[string]string{"telegram_bot_token": "", "telegram_enabled": "0", "_telegram_bindings": "{}"})
		b.changed()
		respond(w, a.adminSettings())
	default:
		notFound()
	}
}

func (b *telegramBot) wait(ctx context.Context, d time.Duration) {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-b.wake:
	case <-t.C:
	}
}

func (b *telegramBot) run() {
	defer b.a.workerWG.Done()
	defer b.client.CloseIdleConnections()
	backoff := time.Second
	for b.a.workerContext.Err() == nil {
		ctx, cancel := context.WithCancel(b.a.workerContext)
		// Install cancellation before reading config: saving new settings cannot
		// race past a stale snapshot and leave the old bot polling for 25 seconds.
		b.mu.Lock()
		b.cancel = cancel
		b.mu.Unlock()
		b.a.dataMu.RLock()
		s := b.a.settings()
		b.a.dataMu.RUnlock()
		if s["telegram_enabled"] != "1" || s["telegram_bot_token"] == "" {
			b.state("", nil)
			b.wait(ctx, 30*time.Second)
			cancel()
			continue
		}
		if !telegramTokenPattern.MatchString(s["telegram_bot_token"]) {
			b.state("", errors.New("Telegram Bot Token 格式无效"))
			b.wait(ctx, 30*time.Second)
			cancel()
			continue
		}
		err := b.session(ctx, s["telegram_bot_token"])
		if ctx.Err() != nil {
			backoff = time.Second
		} else {
			b.state("", err)
			delay := backoff
			var apiErr telegramAPIError
			if errors.As(err, &apiErr) && apiErr.code == 429 {
				delay = time.Duration(apiErr.retry) * time.Second
			}
			b.wait(ctx, delay)
			backoff = min(30*time.Second, backoff*2)
		}
		cancel()
	}
}

func telegramFingerprint(token string) string {
	digest := sha256.Sum256([]byte(token))
	return hex.EncodeToString(digest[:])
}

func (b *telegramBot) session(ctx context.Context, token string) (err error) {
	defer func() {
		if recover() != nil {
			err = errors.New("Telegram 任务异常，稍后自动重连")
		}
	}()
	var me struct {
		Username string `json:"username"`
		IsBot    bool   `json:"is_bot"`
	}
	if err = b.call(ctx, token, "getMe", M{}, &me); err != nil {
		return err
	}
	if !me.IsBot || me.Username == "" {
		return errors.New("Telegram Bot 身份校验失败")
	}
	b.registerMenu(ctx, token, 0)
	fingerprint := telegramFingerprint(token)
	b.a.dataMu.RLock()
	s := b.a.settings()
	b.a.dataMu.RUnlock()
	offset := num(s["_telegram_offset"])
	for sender := range telegramBindings(s) {
		if id, e := strconv.ParseInt(sender, 10, 64); e == nil && b.administrator(s, id) != nil {
			b.registerMenu(ctx, token, id)
		}
	}
	if s["_telegram_token_hash"] != fingerprint {
		// New credentials skip the backlog; old commands must not be executed
		// after an administrator subsequently binds an account.
		var updates []telegramUpdate
		if err = b.call(ctx, token, "getUpdates", M{"offset": -1, "limit": 1, "timeout": 0, "allowed_updates": []string{"message"}}, &updates); err != nil {
			return err
		}
		offset = 0
		if len(updates) > 0 {
			offset = updates[len(updates)-1].ID + 1
		}
		if !b.checkpoint(ctx, token, offset) {
			return context.Canceled
		}
	}
	for ctx.Err() == nil {
		b.state(me.Username, nil)
		var updates []telegramUpdate
		if err = b.call(ctx, token, "getUpdates", M{"offset": offset, "limit": 10, "timeout": 25, "allowed_updates": []string{"message"}}, &updates); err != nil {
			return err
		}
		for _, update := range updates {
			if update.ID < offset {
				continue
			}
			offset = update.ID + 1
			// Persist before sending. An uncertain network result must never
			// cause an image to be resent automatically after restart.
			if !b.checkpoint(ctx, token, offset) {
				return context.Canceled
			}
			if err = b.handle(ctx, token, me.Username, update.Message); err != nil {
				return err
			}
		}
	}
	return ctx.Err()
}

func (b *telegramBot) checkpoint(ctx context.Context, token string, offset int64) bool {
	b.a.dataMu.RLock()
	defer b.a.dataMu.RUnlock()
	b.a.writeMu.Lock()
	defer b.a.writeMu.Unlock()
	s := b.a.settings()
	if ctx.Err() != nil || s["telegram_enabled"] != "1" || s["telegram_bot_token"] != token {
		return false
	}
	b.a.updateSettings(map[string]string{"_telegram_offset": strconv.FormatInt(offset, 10), "_telegram_token_hash": telegramFingerprint(token)})
	return true
}

func telegramCommand(text, bot string) (string, string) {
	text = strings.TrimSpace(text)
	if len(text) > 4096 {
		return "", ""
	}
	end := strings.IndexFunc(text, unicode.IsSpace)
	command, arg := text, ""
	if end >= 0 {
		command, arg = text[:end], strings.TrimSpace(text[end:])
	}
	if name, target, ok := strings.Cut(command, "@"); ok {
		if !strings.EqualFold(target, bot) {
			return "", ""
		}
		command = name
	}
	return strings.ToLower(command), arg
}

func (b *telegramBot) bind(ctx context.Context, token string, sender int64, code string) bool {
	a := b.a
	a.dataMu.RLock()
	defer a.dataMu.RUnlock()
	a.writeMu.Lock()
	defer a.writeMu.Unlock()
	s := a.settings()
	if ctx.Err() != nil || s["telegram_enabled"] != "1" || s["telegram_bot_token"] != token {
		return false
	}
	hash := sha256.Sum256([]byte(code))
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.pairUID == "" || !time.Now().Before(b.pairExp) || subtle.ConstantTimeCompare(hash[:], b.pair[:]) != 1 {
		return false
	}
	user := a.one("SELECT id FROM users WHERE id=? AND role='admin' AND enabled=1", b.pairUID)
	if user == nil {
		return false
	}
	bindings := telegramBindings(s)
	if len(bindings) >= 100 {
		return false
	}
	bindings[strconv.FormatInt(sender, 10)] = str(user["id"])
	raw, _ := json.Marshal(bindings)
	a.updateSettings(map[string]string{"_telegram_bindings": string(raw)})
	b.pairUID = "" // One use, and only ever in a private chat.
	return true
}

func (b *telegramBot) text(ctx context.Context, token string, sender int64, text string) error {
	return b.call(ctx, token, "sendMessage", M{"chat_id": sender, "text": text}, nil)
}

func (b *telegramBot) handle(ctx context.Context, token, bot string, msg *telegramMessage) error {
	if msg == nil || msg.From.IsBot || msg.From.ID <= 0 || msg.Chat.Type != "private" || msg.Chat.ID != msg.From.ID || msg.Date < time.Now().Unix()-120 || msg.Date > time.Now().Unix()+30 {
		return nil
	}
	command, arg := telegramCommand(msg.Text, bot)
	if command == "/bind" {
		if b.bind(ctx, token, msg.From.ID, arg) {
			b.registerMenu(ctx, token, msg.From.ID)
			return b.text(ctx, token, msg.From.ID, "管理员绑定成功。发送 /random 获取随机图，/random 标签名 按标签取图，/tags 查看可用标签。")
		}
		return nil
	}
	a := b.a
	// All authorization, image selection and file opens happen under the data
	// lease. No network request holds a DB/restore or settings write lock.
	a.dataMu.RLock()
	s := a.settings()
	if ctx.Err() != nil || s["telegram_enabled"] != "1" || s["telegram_bot_token"] != token || b.administrator(s, msg.From.ID) == nil {
		a.dataMu.RUnlock()
		return nil // Ordinary users receive no bot replies, including /help.
	}
	var file *os.File
	var method, label, reply string
	var private bool
	switch command {
	case "/start", "/help":
		reply = "/random — 随机一张图\n/random 标签名 — 按完整标签精确取图\n/tags — 查看可用标签\n仅绑定且启用的站点管理员可用，仅支持私聊。"
	case "/tags":
		filter, args := "COALESCE(tag,'')!=?", []any{privateTag}
		if s["telegram_include_private"] == "1" {
			filter, args = "1=1", nil
		}
		tags := []string{}
		for _, row := range a.rows("SELECT tag,COUNT(*) AS n FROM images WHERE trim(COALESCE(tag,''))!='' AND ("+filter+") GROUP BY tag ORDER BY tag LIMIT 80", args...) {
			tags = append(tags, str(row["tag"])+"（"+str(row["n"])+"）")
		}
		reply = "可用标签：\n" + strings.Join(tags, "\n")
		if len(tags) == 0 {
			reply = "暂无可用标签。使用 /random 可获取未标注图片。"
		}
		reply = truncate(reply, 3900)
	case "/random", "/rand":
		if len([]rune(arg)) > 40 {
			reply = "标签名最多 40 字。用法：/random 或 /random 标签名"
		} else if arg == privateTag && s["telegram_include_private"] != "1" {
			reply = "Telegram 私密图片发送未开启。"
		} else {
			file, method, label, private = b.chooseImage(arg)
			if file == nil {
				reply = "没有可发送的图片，请检查标签、原图和 50 MB 文件限制；缺失文件可在后台重建索引。"
			}
		}
	default:
		a.dataMu.RUnlock()
		return nil
	}
	a.dataMu.RUnlock()
	if file == nil {
		return b.text(ctx, token, msg.From.ID, reply)
	}
	defer file.Close()
	return b.sendFile(ctx, token, msg.From.ID, file, method, label, private)
}

func (b *telegramBot) chooseImage(tag string) (*os.File, string, string, bool) {
	filter, args := "COALESCE(tag,'')!=?", []any{privateTag}
	if tag != "" {
		filter, args = "tag=?", []any{tag}
	}
	// Bound memory and tolerate a few stale index entries without mutating the
	// gallery from the bot. An existing original is always required.
	for _, im := range b.a.rows("SELECT key,c_key,tag FROM images WHERE "+filter+" ORDER BY RANDOM() LIMIT 25", args...) {
		original := pathIn(filepath.Join(b.a.data, "uploads"), str(im["key"]))
		if fi, err := os.Stat(original); err != nil || !fi.Mode().IsRegular() {
			continue
		}
		paths := []string{original}
		if str(im["c_key"]) != "" {
			paths = append([]string{pathIn(filepath.Join(b.a.data, "compressed"), str(im["c_key"]))}, paths...)
		}
		var fallback *os.File
		for _, path := range paths {
			file, err := os.Open(path)
			if err != nil {
				continue
			}
			fi, err := file.Stat()
			if err != nil || !fi.Mode().IsRegular() || fi.Size() <= 0 || fi.Size() > 50*1024*1024 {
				file.Close()
				continue
			}
			method := "sendDocument"
			if strings.EqualFold(filepath.Ext(path), ".gif") {
				method = "sendAnimation"
			} else if fi.Size() <= 10*1024*1024 {
				cfg, format, err := image.DecodeConfig(file)
				_, _ = file.Seek(0, io.SeekStart)
				if err == nil && (format == "jpeg" || format == "png") && cfg.Width > 0 && cfg.Height > 0 && cfg.Width+cfg.Height <= 10000 && max(cfg.Width, cfg.Height) <= 20*min(cfg.Width, cfg.Height) {
					method = "sendPhoto"
				}
			}
			if method != "sendDocument" {
				if fallback != nil {
					fallback.Close()
				}
				return file, method, str(im["tag"]), str(im["tag"]) == privateTag
			}
			if fallback == nil {
				fallback = file
			} else {
				file.Close()
			}
		}
		if fallback != nil {
			return fallback, "sendDocument", str(im["tag"]), str(im["tag"]) == privateTag
		}
	}
	return nil, "", "", false
}

func (b *telegramBot) sendFile(ctx context.Context, token string, sender int64, file *os.File, method, label string, private bool) error {
	fi, err := file.Stat()
	if err != nil {
		return errors.New("待发送图片已不可读")
	}
	if label == "" {
		label = "无标签"
	}
	var headers bytes.Buffer
	writer := multipart.NewWriter(&headers)
	_ = writer.WriteField("chat_id", strconv.FormatInt(sender, 10))
	_ = writer.WriteField("caption", "随机图 · 标签："+label)
	if private {
		_ = writer.WriteField("protect_content", "true")
	}
	field := map[string]string{"sendPhoto": "photo", "sendAnimation": "animation", "sendDocument": "document"}[method]
	if method == "sendDocument" {
		_ = writer.WriteField("disable_content_type_detection", "true")
	}
	// Use the stored random key, never the uploaded personal filename. Stream
	// bytes from disk: large images are not buffered in the resident Go heap.
	_, err = writer.CreateFormFile(field, filepath.Base(file.Name()))
	if err != nil {
		return errors.New("无法准备 Telegram 图片")
	}
	boundary := headers.Len()
	_ = writer.Close()
	raw := headers.Bytes()
	body := io.MultiReader(bytes.NewReader(raw[:boundary]), io.LimitReader(file, fi.Size()), bytes.NewReader(raw[boundary:]))
	return b.request(ctx, token, method, writer.FormDataContentType(), body, int64(len(raw))+fi.Size(), nil)
}

func (b *telegramBot) registerMenu(ctx context.Context, token string, chat int64) {
	commands := []probe.Command{{Command: "start", Description: "使用说明"}, {Command: "bind", Description: "绑定网站账户（后接绑定码）"}}
	if chat > 0 {
		commands = []probe.Command{{Command: "random", Description: "随机图片，可附标签"}, {Command: "tags", Description: "查看可用标签"}, {Command: "help", Description: "使用帮助"}, {Command: "bind", Description: "绑定网站账户（后接绑定码）"}}
	}
	_ = (probe.Telegram{HTTP: b.client, BaseURL: b.baseURL}).Menu(ctx, token, chat, commands)
}
