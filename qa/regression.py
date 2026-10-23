"""Go release regression: real HTTP, Pillow jobs, legacy SQLite, restart, ZIP.

Run after building server/gallery[.exe] and frontend/dist:
    python qa/regression.py
All data is disposable and isolated in .qa-data. No production credentials used.
"""
import concurrent.futures
import hashlib
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(os.environ.get("QA_BINARY", str(ROOT / "server" / ("gallery.exe" if os.name == "nt" else "gallery"))))
TEMP = ROOT / ".qa-data"
TEMP.mkdir(exist_ok=True)
passed = 0
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(name, condition):
    global passed
    if not condition:
        raise AssertionError(name)
    passed += 1
    print(f"PASS {name}", flush=True)


def pic(fmt="PNG", size=(64, 48)):
    out = io.BytesIO()
    image = Image.new("RGB", size, "#678fc2")
    if fmt == "GIF":
        image.save(out, fmt, save_all=True, append_images=[Image.new("RGB", size, "#edb287")], duration=100, loop=0)
    else:
        image.save(out, fmt)
    return out.getvalue()


def multipart(files, fields=None):
    boundary = "qa-" + os.urandom(12).hex()
    parts = []
    for k, v in (fields or {}).items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for field, name, data in files:
        parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(), data, b"\r\n"])
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def run(data, legacy_python=None, legacy_backend=None):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "DATA_DIR": str(data), "WEB_DIR": str(ROOT / "frontend/dist"),
           "IMAGE_WORKER": str(ROOT / "backend/image_worker.py"), "LISTEN_ADDR": f"127.0.0.1:{port}",
           "ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "qa-pass-123", "ADMIN_SYNC": "0",
           "TRUSTED_PROXIES": "127.0.0.1/32", "PYTHON": sys.executable}
    log = open(data / "qa-server.log", "ab")
    command = [str(BIN)]
    cwd = ROOT
    if legacy_python:
        command = [str(legacy_python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
        cwd = legacy_backend
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log)

    def call(method, path, value=None, token="", headers=None, raw=False):
        body = value
        h = dict(headers or {})
        if value is not None and not isinstance(value, bytes):
            body = json.dumps(value).encode()
            h["Content-Type"] = "application/json"
        if token:
            h["Authorization"] = "Bearer " + token
        req = urllib.request.Request(base + path, data=body, headers=h, method=method)
        try:
            res = opener.open(req, timeout=60)
        except urllib.error.HTTPError as e:
            res = e
        with res:
            content = res.read()
            return res.status, content if raw else json.loads(content or b"{}")

    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError((data / "qa-server.log").read_text(errors="replace"))
        try:
            if call("GET", "/api/health")[0] == 200:
                break
        except OSError:
            time.sleep(.1)
    return proc, log, call, env


def seed_legacy(data):
    # Python release's exact PBKDF2 encoding and pre-v3 images table. Migration
    # must add owner/tag/orig_name and upload limits without replacing records.
    (data / "uploads/uploads/20260101").mkdir(parents=True)
    db = sqlite3.connect(data / "metadata.db")
    db.executescript("""
    CREATE TABLE images(id TEXT PRIMARY KEY,key TEXT UNIQUE NOT NULL,mime TEXT NOT NULL,
        width INTEGER NOT NULL,height INTEGER NOT NULL,size INTEGER NOT NULL,c_key TEXT,
        c_mime TEXT,c_width INTEGER,c_height INTEGER,c_size INTEGER,created_at TEXT NOT NULL);
    CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,pwd TEXT NOT NULL,
        role TEXT NOT NULL,quota_mb INTEGER DEFAULT 0,max_upload_mb INTEGER DEFAULT 0,
        comp_format TEXT,comp_quality INTEGER,comp_max_width INTEGER,enabled INTEGER DEFAULT 1,created_at TEXT NOT NULL);
    CREATE TABLE settings(k TEXT PRIMARY KEY,v TEXT NOT NULL);
    """)
    salt = bytes.fromhex("0123456789abcdef0123456789abcdef")
    digest = hashlib.pbkdf2_hmac("sha256", b"qa-pass-123", salt, 200000).hex()
    db.execute("INSERT INTO users(id,username,pwd,role,created_at) VALUES(?,?,?,?,?)",
               ("legacy-admin", "owner", f"pbkdf2_sha256$200000${salt.hex()}${digest}", "admin", "2026-01-01T00:00:00+00:00"))
    db.execute("INSERT INTO settings VALUES('site_title','Legacy gallery')")
    for n in range(83):
        key = f"uploads/20260101/legacy-{n:03d}.png"
        payload = pic()
        (data / "uploads" / key).write_bytes(payload)
        db.execute("INSERT INTO images(id,key,mime,width,height,size,created_at) VALUES(?,?,?,?,?,?,?)",
                   (f"legacy-{n:03d}", key, "image/png", 64, 48, len(payload), "2026-01-01T00:00:00+00:00"))
    db.commit()
    db.close()


def suite(data):
    seed_legacy(data)
    proc, log, call, env = run(data)
    try:
        check("legacy site settings survive", call("GET", "/api/public/settings")[1]["site_title"] == "Legacy gallery")
        status, login = call("POST", "/api/auth/login", {"username": "owner", "password": "qa-pass-123", "remember": True})
        check("legacy Python password verifies in Go", status == 200)
        token = login["token"]
        settings = call("GET", "/api/admin/settings", token=token)[1]
        check("all editable settings returned without internal bookkeeping", set(settings) == set(json.loads((ROOT / "server/defaults.json").read_text(encoding="utf-8"))))
        system = call("GET", "/api/admin/system", token=token)[1]
        check("compression profiles and formats available", len(system["profiles"]) == 3 and len(system["formats"]) == 6 and system["pool"]["active"] == 0)
        backup_stats = call("GET", "/api/admin/backup/stats", token=token)[1]
        check("backup usage counts actual fixture files", backup_stats["counts"]["images"] == 83 and backup_stats["dirs"]["uploads"]["files"] == 83)
        stats = call("GET", "/api/admin/stats", token=token)[1]
        check("visit statistics and yesterday uploads", len(stats["days"]) == 3 and stats["library"]["count"] == 83 and stats["yesterday"]["uploads"] == 0)
        check("wrong old password keeps session valid", call("POST", "/api/auth/password", {"old": "wrong", "new": "qa-new-pass"}, token)[0] == 401 and call("GET", "/api/auth/me", token=token)[0] == 200)
        check("change password succeeds", call("POST", "/api/auth/password", {"old": "qa-pass-123", "new": "qa-new-pass"}, token)[0] == 200)
        check("new password authenticates", call("POST", "/api/auth/login", {"username": "owner", "password": "qa-new-pass"})[0] == 200)
        call("POST", "/api/auth/password", {"old": "qa-new-pass", "new": "qa-pass-123"}, token)
        check("legacy IDs and ownership migrate", login["user"]["id"] == "legacy-admin" and login["user"]["imageCount"] == 83)
        check("empty tags hidden despite configured pool", call("GET", "/api/tags")[1]["tags"] == [])
        for path in ("/api/admin/upload", "/api/admin/reindex", "/api/admin/verify", "/api/unused"):
            check("removed endpoint " + path, call("POST", path, {}, token)[0] == 404)
        check("admin requires login", call("GET", "/api/admin/settings")[0] == 401)
        check("random requires login by default", call("GET", "/api/random")[0] == 401)
        check("invalid JSON returns 400", call("POST", "/api/auth/login", b"{bad", headers={"Content-Type": "application/json"})[0] == 400)
        check("invalid cursor returns 400", call("GET", "/api/images?cursor=bad")[0] == 400)
        first = call("GET", "/api/images?limit=36", token=token)[1]
        check("first cursor batch", len(first["items"]) == 36 and first["hasMore"] and first["nextCursor"])
        # Insert a new head and remove an already-viewed record between batches.
        body, headers = multipart([("files", "new.png", pic())], {"tag": "landscape"})
        status, uploaded = call("POST", "/api/upload", body, token, headers)
        check("real Pillow upload", status == 200 and uploaded["results"][0]["ok"])
        image = uploaded["results"][0]["item"]
        check("original/thumbnail/compressed URLs all serve", all(call("GET", image[k], raw=True)[0] == 200 for k in ("url", "thumb", "compressed")))
        check("used tag appears with count", call("GET", "/api/tags")[1]["tags"] == [{"name": "landscape", "count": 1}])
        call("DELETE", "/api/images/" + first["items"][0]["id"], token=token)
        seen = [x["id"] for x in first["items"]]
        cursor = first["nextCursor"]
        while cursor:
            batch = call("GET", "/api/images?limit=36&cursor=" + cursor, token=token)[1]
            seen += [x["id"] for x in batch["items"]]
            cursor = batch["nextCursor"]
        check("cursor survives head insertion/deletion without duplicates/skips", len(seen) == 83 and len(set(seen)) == 83 and all(x.startswith("legacy-") for x in seen))
        status, renamed = call("PATCH", "/api/images/" + image["id"], {"filename": "renamed-photo", "tag": ""}, token)
        check("rename changes all three assets", status == 200 and all(call("GET", renamed[k], raw=True)[0] == 200 for k in ("url", "thumb", "compressed")))
        check("last tag removal clears gallery filter list", call("GET", "/api/tags")[1]["tags"] == [])
        status, _ = call("PUT", "/api/admin/settings", {"site_title": "QA gallery", "upload_max_mb": 0, "comp_profile": "tiny", "random_public": 1}, token)
        check("hot settings preserve zero upload limit", status == 200 and call("GET", "/api/public/settings")[1]["upload_max_mb"] == "0")
        check("public random works", call("GET", "/api/random")[0] == 200)
        status, user = call("POST", "/api/users", {"username": "tester", "password": "test-pass", "quota_mb": 0, "max_upload_mb": 0, "daily_limit": 0, "weekly_limit": 0, "monthly_limit": 0}, token)
        check("user defaults/explicit unlimited values", status == 200 and user["user"]["quotaMb"] == 0 and user["user"]["maxUploadMb"] == 0)
        uid = user["user"]["id"]
        ut = call("POST", "/api/auth/login", {"username": "tester", "password": "test-pass"})[1]["token"]
        check("regular user cannot access admin", call("GET", "/api/admin/system", token=ut)[0] == 403)
        check("regular user cannot edit others", call("PATCH", "/api/images/" + image["id"], {"tag": "bad"}, ut)[0] == 403)
        body, headers = multipart([("files", "large.bmp", pic("BMP", (1600, 1200)))])
        _, up = call("POST", "/api/upload", body, ut, headers)
        check("zero global cap permits >5MiB image", up["results"][0]["ok"] and up["results"][0]["item"]["size"] > 5 * 1048576)
        owned = up["results"][0]["item"]
        check("mine filter only returns own uploads", [x["id"] for x in call("GET", "/api/images?mine=1", token=ut)[1]["items"]] == [owned["id"]])
        call("PATCH", "/api/users/" + uid, {"daily_limit": 1}, token)
        body, headers = multipart([("files", "limited.png", pic())])
        check("daily limit enforced", not call("POST", "/api/upload", body, ut, headers)[1]["results"][0]["ok"])
        call("PATCH", "/api/users/" + uid, {"daily_limit": 0, "quota_mb": 1}, token)
        check("quota enforced", not call("POST", "/api/upload", body, ut, headers)[1]["results"][0]["ok"])
        call("PATCH", "/api/users/" + uid, {"quota_mb": 0}, token)
        call("PATCH", "/api/users/" + uid, {"max_upload_mb": 1}, token)
        large_body, large_headers = multipart([("files", "limited.bmp", pic("BMP", (800, 600)))])
        check("per-user single image limit enforced", not call("POST", "/api/upload", large_body, ut, large_headers)[1]["results"][0]["ok"])
        call("PATCH", "/api/users/" + uid, {"max_upload_mb": 0, "weekly_limit": 1}, token)
        check("weekly upload limit enforced", not call("POST", "/api/upload", body, ut, headers)[1]["results"][0]["ok"])
        call("PATCH", "/api/users/" + uid, {"weekly_limit": 0, "monthly_limit": 1}, token)
        check("monthly upload limit enforced", not call("POST", "/api/upload", body, ut, headers)[1]["results"][0]["ok"])
        call("PATCH", "/api/users/" + uid, {"monthly_limit": 0}, token)
        for fmt, ext in (("JPEG", "jpg"), ("WEBP", "webp"), ("GIF", "gif")):
            body, headers = multipart([("files", "fixture." + ext, pic(fmt))])
            _, up = call("POST", "/api/upload", body, ut, headers)
            check("input " + fmt, up["results"][0]["ok"])
            if fmt == "GIF":
                gif = up["results"][0]["item"]
                check("GIF stays animated and has no compressed version", gif["compressed"] is None and Image.open(io.BytesIO(call("GET", gif["url"], raw=True)[1])).n_frames == 2)
        call("PATCH", "/api/users/" + uid, {"enabled": 0}, token)
        check("disabled user session rejected", call("GET", "/api/auth/me", token=ut)[0] == 401)
        call("PATCH", "/api/users/" + uid, {"enabled": 1}, token)
        check("cannot disable last enabled admin", call("PATCH", "/api/users/legacy-admin", {"enabled": 0}, token)[0] == 400)
        check("invalid settings fail without 500", call("PUT", "/api/admin/settings", {"comp_quality": "nonsense"}, token)[0] == 400)
        check("combined enum value rejected", call("PUT", "/api/admin/settings", {"comp_format": "webp,jpeg"}, token)[0] == 400)
        for output, expected in (("jpeg", "JPEG"), ("png", "PNG")):
            call("PUT", "/api/admin/settings", {"comp_format": output}, token)
            body, headers = multipart([("files", "output.png", pic())])
            result = call("POST", "/api/upload", body, token, headers)[1]["results"][0]
            check("compressed output " + output, result["ok"] and Image.open(io.BytesIO(call("GET", result["item"]["compressed"], raw=True)[1])).format == expected)
        call("PUT", "/api/admin/settings", {"comp_format": "webp"}, token)
        if "AVIF" in Image.registered_extensions().values():
            body, headers = multipart([("files", "input.avif", pic("AVIF"))])
            check("AVIF input codec", call("POST", "/api/upload", body, token, headers)[1]["results"][0]["ok"])
        exif = Image.Exif()
        exif[274] = 6
        oriented = io.BytesIO()
        Image.new("RGB", (80, 40), "blue").save(oriented, "JPEG", exif=exif)
        body, headers = multipart([("files", "oriented.jpg", oriented.getvalue())])
        oriented_item = call("POST", "/api/upload", body, token, headers)[1]["results"][0]["item"]
        check("EXIF orientation applied to derivative", Image.open(io.BytesIO(call("GET", oriented_item["compressed"], raw=True)[1])).size == (40, 80))
        before = set((data / "uploads").rglob("*"))
        body, headers = multipart([("files", "broken.png", b"not an image")])
        check("invalid image rejected", not call("POST", "/api/upload", body, token, headers)[1]["results"][0]["ok"])
        check("failed upload leaves no orphan original", {p for p in (data / "uploads").rglob("*") if p.is_file()} == {p for p in before if p.is_file()})

        received = queue.Queue()
        class Hook(BaseHTTPRequestHandler):
            def do_POST(self):
                received.put((self.command, dict(self.headers), self.rfile.read(int(self.headers.get("Content-Length", 0)))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            do_PUT = do_POST
            do_GET = do_POST
            def log_message(self, *args):
                pass
        hook = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=hook.serve_forever, daemon=True).start()
        try:
            call("PUT", "/api/admin/settings", {"webhook_url": f"http://127.0.0.1:{hook.server_port}/hook", "notify_headers": '{"X-QA":"test"}'}, token)
            check("webhook test delivered", call("POST", "/api/admin/notify/test", token=token)[1]["ok"])
            method, hook_headers, payload = received.get(timeout=5)
            check("webhook JSON includes readable text and custom header", json.loads(payload)["event"] == "test" and "text" in json.loads(payload) and hook_headers.get("X-Qa") == "test")
            call("PUT", "/api/admin/settings", {"notify_method": "PUT", "notify_body_type": "text", "notify_body_tpl": "QA {{event}} {{site}} {{unused}}"}, token)
            call("POST", "/api/admin/notify/test", token=token)
            method, _, payload = received.get(timeout=5)
            check("webhook method and template", method == "PUT" and payload.decode() == "QA test QA gallery ")
            call("PUT", "/api/admin/settings", {"notify_method": "POST", "notify_body_type": "json", "notify_body_tpl": "", "notify_admin_login": 1}, token)
            call("POST", "/api/auth/login", {"username": "owner", "password": "qa-pass-123"})
            check("async admin login notification", json.loads(received.get(timeout=5)[2])["event"] == "admin_login")
            call("PUT", "/api/admin/settings", {"notify_body_tpl": '{"title":"{{title}}","content":"{{text}}","fields":{{fields}}}'}, token)
            check("JSON template with multiline text sends valid JSON", call("POST", "/api/admin/notify/test", token=token)[1]["ok"] and isinstance(json.loads(received.get(timeout=5)[2])["fields"], dict))
        finally:
            call("PUT", "/api/admin/settings", {"webhook_url": "", "notify_admin_login": 0, "notify_body_tpl": ""}, token)
            hook.shutdown()
            hook.server_close()
        # Local import, missing asset generation, GIF exclusion and bad files.
        (data / "uploads/local-photo.png").write_bytes(pic())
        (data / "uploads/invalid.png").write_bytes(b"not an image")
        scan = call("GET", "/api/admin/local/scan", token=token)[1]
        check("local scan separates valid and invalid files", scan["pendingCount"] == 1 and scan["invalidCount"] == 1)
        check("background import starts", call("POST", "/api/admin/local/import", token=token)[0] == 200)
        for _ in range(150):
            job = call("GET", "/api/admin/local/status", token=token)[1]
            if not job["running"]:
                break
            time.sleep(.1)
        check("local import completes", not job["running"] and job["imported"] == 1)
        call("PUT", "/api/admin/settings", {"comp_profile": "custom", "comp_max_pixels": 1, "comp_concurrency": 1}, token)
        (data / "uploads/pixel-limit.png").write_bytes(pic("PNG", (1600, 800)))
        call("POST", "/api/admin/local/import", token=token)
        for _ in range(150):
            failed_job = call("GET", "/api/admin/local/status", token=token)[1]
            if not failed_job["running"]:
                break
            time.sleep(.1)
        check("failed import retries and persists queue", failed_job["failed"] == 1 and failed_job["retried"] == 2 and failed_job["queue"][0]["attempts"] == 3)
        call("PUT", "/api/admin/settings", {"comp_max_pixels": 40}, token)
        call("POST", "/api/admin/local/import", token=token)
        for _ in range(150):
            retried_job = call("GET", "/api/admin/local/status", token=token)[1]
            if not retried_job["running"]:
                break
            time.sleep(.1)
        check("retry after fixing limits clears failure queue", retried_job["imported"] == 1 and retried_job["queueSize"] == 0)
        for n in range(12):
            (data / f"uploads/cancel-{n}.png").write_bytes(pic())
        call("POST", "/api/admin/local/import", token=token)
        check("restore during import returns busy", call("POST", "/api/admin/restore", {}, token)[0] == 409)
        call("POST", "/api/admin/local/import/cancel", token=token)
        for _ in range(150):
            cancelled_job = call("GET", "/api/admin/local/status", token=token)[1]
            if not cancelled_job["running"]:
                break
            time.sleep(.1)
        check("cancel import completes without leaving running state", cancelled_job["cancel"] and not cancelled_job["running"])
        call("POST", "/api/admin/local/import", token=token)
        for _ in range(150):
            resumed_job = call("GET", "/api/admin/local/status", token=token)[1]
            if not resumed_job["running"]:
                break
            time.sleep(.1)
        check("resume import indexes remaining files", call("GET", "/api/admin/local/scan", token=token)[1]["pendingCount"] == 0)
        call("PUT", "/api/admin/settings", {"comp_profile": "tiny"}, token)
        _, comp = call("POST", "/api/admin/local/compress?dry_run=false&limit=2", token=token)
        check("missing asset repair works", comp["done"] == 2 and not comp["failed"])
        # Snapshot is consistent SQLite; restore invalidates every old session.
        status, backup = call("GET", "/api/admin/backup", token=token, raw=True)
        check("backup ZIP streams", status == 200 and zipfile.is_zipfile(io.BytesIO(backup)))
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            check("backup contains manifest, DB, originals and variants", {"metadata.db", "MANIFEST.json"} <= set(z.namelist()) and any(x.startswith("thumbs/") for x in z.namelist()) and not any(".backup-" in x for x in z.namelist()))
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../escaped.txt", "bad")
        body, headers = multipart([("file", "bad.zip", bad.getvalue())])
        check("unsafe ZIP rejected before restore", call("POST", "/api/admin/restore", body, token, headers)[0] == 400)
        check("failed restore leaves library live", call("GET", "/api/auth/me", token=token)[0] == 200)
        invalid_db = io.BytesIO()
        with zipfile.ZipFile(invalid_db, "w") as z:
            z.writestr("metadata.db", b"not a SQLite database")
        body, headers = multipart([("file", "invalid-db.zip", invalid_db.getvalue())])
        check("corrupt database backup rejected safely", call("POST", "/api/admin/restore", body, token, headers)[0] == 400 and call("GET", "/api/auth/me", token=token)[0] == 200)
        call("PUT", "/api/admin/settings", {"site_title": "will be restored"}, token)
        body, headers = multipart([("file", "backup.zip", backup)])
        status, restore = call("POST", "/api/admin/restore", body, token, headers)
        check("restore succeeds and requests relogin", status == 200 and restore["relogin"])
        check("restored settings match snapshot", call("GET", "/api/public/settings")[1]["site_title"] == "QA gallery")
        check("restored legacy session invalidated", call("GET", "/api/auth/me", token=token)[0] == 401)
        token = call("POST", "/api/auth/login", {"username": "owner", "password": "qa-pass-123"})[1]["token"]
        check("restored account logs in", call("GET", "/api/auth/me", token=token)[0] == 200)
        _, transfer_user = call("POST", "/api/users", {"username": "transferuser", "password": "transfer-pass"}, token)
        transfer_id = transfer_user["user"]["id"]
        transfer_token = call("POST", "/api/auth/login", {"username": "transferuser", "password": "transfer-pass"})[1]["token"]
        body, headers = multipart([("files", "transfer.png", pic())])
        transfer_image = call("POST", "/api/upload", body, transfer_token, headers)[1]["results"][0]["item"]
        check("delete user transfers images by default", call("DELETE", "/api/users/" + transfer_id, token=token)[0] == 200)
        all_images = call("GET", "/api/images?limit=100", token=token)[1]["items"]
        check("transferred image belongs to administrator and remains accessible", next(x for x in all_images if x["id"] == transfer_image["id"])["ownerId"] == "legacy-admin" and call("GET", transfer_image["url"], raw=True)[0] == 200)
        # Verify account purge physically removes original + variants.
        check("delete user with purge", call("DELETE", "/api/users/" + uid + "?purge=true", token=token)[0] == 200)
        check("purge removes files as well as rows", call("GET", owned["url"], raw=True)[0] == 404)
        call("PUT", "/api/admin/settings", {"rate_limit": 2, "auth_max_fails": 2}, token)
        hdr = {"X-Real-IP": "8.8.8.8"}
        check("random rate limiting", [call("GET", "/api/random", headers=hdr)[0] for _ in range(3)] == [200, 200, 429])
        check("manual unban", call("DELETE", "/api/admin/bans/8.8.8.8", token=token)[0] == 200)
        hdr2 = {"X-Real-IP": "1.1.1.1"}
        check("login brute-force defense", [call("POST", "/api/auth/login", {"username": "bad", "password": "bad"}, headers=hdr2)[0] for _ in range(2)] == [401, 429])
        check("whitelist overrides ban", call("POST", "/api/admin/whitelist", {"pattern": "1.1.1.1"}, token)[0] == 200 and call("GET", "/api/health", headers=hdr2)[0] == 200)
        call("DELETE", "/api/admin/whitelist/1.1.1.1", token=token)
        check("blacklist CIDR", call("POST", "/api/admin/blacklist", {"pattern": "9.9.9.0/24"}, token)[0] == 200 and call("GET", "/api/health", headers={"X-Real-IP": "9.9.9.9"})[0] == 403)
        check("CIDR delete path", call("DELETE", "/api/admin/blacklist/9.9.9.0/24", token=token)[0] == 200)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            statuses = list(pool.map(lambda _: call("GET", "/api/images?limit=12")[0], range(160)))
        check("concurrent reads remain healthy", set(statuses) == {200})
        check("healthcheck subcommand supports configured listen address", subprocess.run([str(BIN), "healthcheck"], env=env, capture_output=True).returncode == 0)
        proc.terminate()
        proc.wait(timeout=10)
        log.close()
        proc, log, call, env = run(data)
        check("session persists across restart", call("GET", "/api/auth/me", token=token)[0] == 200)
        check("settings persist across restart", call("GET", "/api/public/settings")[1]["site_title"] == "QA gallery")
        print(f"\n{passed} regression checks passed")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()
        if sys.exc_info()[0] is not None:
            print((data / "qa-server.log").read_text(encoding="utf-8", errors="replace"), file=sys.stderr)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="regression-", dir=TEMP) as tmp:
        suite(Path(tmp))
