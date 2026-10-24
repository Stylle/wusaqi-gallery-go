"""Batch actions, filesystem reconciliation and tag-filtered random regression.

Supports the same QA_BINARY / QA_DOCKER_IMAGE options as regression.py.
Only disposable data is used, including intentional file removal.
"""
import io
from pathlib import Path
import tempfile
import time
from urllib.parse import quote, unquote, urlsplit
import urllib.request
import zipfile

import regression as qa


def suite(data):
    proc, log, call, env = qa.run(data)
    try:
        token = call("POST", "/api/auth/login", {"username":"owner", "password":"qa-pass-123"})[1]["token"]
        call("POST", "/api/users", {"username":"batchuser", "password":"batch-pass"}, token)
        user = call("POST", "/api/auth/login", {"username":"batchuser", "password":"batch-pass"})[1]["token"]
        def upload(name, auth=token, tag="", fmt="PNG"):
            body, headers = qa.multipart([("files", name, qa.pic(fmt))], {"tag":tag})
            status, value = call("POST", "/api/upload", body, auth, headers)
            assert status == 200 and value["results"][0]["ok"], value
            return value["results"][0]["item"]
        a, b, c = upload("one.png", tag="猫 & 风景"), upload("two.png", tag="other"), upload("one.png", user, "owned")
        aid, bid, cid = a["id"], b["id"], c["id"]
        tag_query = quote("猫 & 风景")
        qa.check("tag random keeps existing authentication", call("GET", "/api/random?tag="+tag_query)[0] == 401)
        qa.check("random filters exact Unicode tag", call("GET", "/api/random?tag="+tag_query, token=token)[1]["id"] == aid)
        qa.check("unknown tag returns 404 without unrelated fallback", call("GET", "/api/random?tag=unknown", token=token)[0] == 404)
        qa.check("random tag uses SQL parameters", call("GET", "/api/random?tag="+quote("' OR 1=1--"), token=token)[0] == 404)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        old_opener = qa.opener
        qa.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            status, content = call("GET", "/api/random/image?variant=original&tag="+tag_query, token=token, raw=True)
            qa.check("tag-filtered random direct link redirects", status == 302 and a["url"].encode() in content)
        finally: qa.opener = old_opener
        qa.check("batch requires authentication", call("PATCH", "/api/images/batch", {"ids":[aid],"tag":"x"})[0] == 401)
        qa.check("batch tag validates all ownership before changing anything", call("PATCH", "/api/images/batch", {"ids":[cid,aid],"tag":"forbidden"}, user)[0] == 403 and call("GET", "/api/images?tag=forbidden")[1]["total"] == 0)
        qa.check("batch delete rejects mixed ownership before deleting anything", call("DELETE", "/api/images/batch", {"ids":[cid,aid]}, user)[0] == 403 and call("GET", "/api/images")[1]["total"] == 3)
        for ids in ([], "invalid", [1], [aid]*501):
            qa.check("invalid batch selection rejected", call("PATCH", "/api/images/batch", {"ids":ids,"tag":"x"}, token)[0] == 400)
        qa.check("batch missing tag rejected", call("PATCH", "/api/images/batch", {"ids":[aid]}, token)[0] == 400)
        qa.check("missing selection is not silently skipped", call("DELETE", "/api/images/batch", {"ids":[aid,"missing"]}, token)[0] == 404 and call("GET", "/api/images")[1]["total"] == 3)
        qa.check("ordinary user can batch edit own image", call("PATCH", "/api/images/batch", {"ids":[cid],"tag":"mine"}, user)[1]["done"] == 1)
        changed = call("PATCH", "/api/images/batch", {"ids":[aid,bid,aid],"tag":"batch"}, token)[1]
        qa.check("batch label updates and deduplicates selection", changed["done"] == 2 and call("GET", "/api/images?tag=batch")[1]["total"] == 2)
        qa.check("batch label supports clearing", call("PATCH", "/api/images/batch", {"ids":[aid,bid],"tag":""}, token)[1]["done"] == 2 and not any(t["name"]=="batch" for t in call("GET", "/api/tags")[1]["tags"]))
        call("PATCH", "/api/images/batch", {"ids":[aid,bid],"tag":"retained"}, token)
        qa.check("ZIP download requires login", call("POST", "/api/images/batch/download", {"ids":[aid]})[0] == 401)
        status, archive = call("POST", "/api/images/batch/download", {"ids":[aid,bid,cid,aid]}, user, raw=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            qa.check("ZIP contains selected originals with unique safe names", status==200 and len(z.namelist())==3 and len(set(z.namelist()))==3 and all("/" not in name and z.read(name)==qa.pic() for name in z.namelist()))
        (data / "uploads" / b["key"]).unlink()
        qa.check("ZIP validates missing originals before streaming", call("POST", "/api/images/batch/download", {"ids":[aid,bid]}, token, raw=True)[0] == 409)
        (data / "thumbs" / (a["key"]+".webp")).unlink()
        compressed_key = unquote(urlsplit(a["compressed"]).path).removeprefix("/compressed/")
        (data / "compressed" / compressed_key).unlink()
        qa.check("index inspection is admin only", call("GET", "/api/admin/local/index", token=user)[0] == 403)
        report = call("GET", "/api/admin/local/index", token=token)[1]
        qa.check("read-only index inspection distinguishes missing originals and variants", report["missingOriginals"]==1 and report["missingThumbs"]==1 and report["missingCompressed"]==1 and call("GET", "/api/images")[1]["total"]==3)
        qa.check("ordinary user cannot rebuild", call("POST", "/api/admin/local/rebuild", token=user)[0] == 403)
        result = call("POST", "/api/admin/local/rebuild", token=token)[1]
        qa.check("rebuild removes stale rows and resets broken compressed references", result["removed"]==1 and result["resetCompressed"]==1 and call("GET", "/api/images")[1]["total"]==2)
        qa.check("rebuild removes orphan derivatives for missing originals", not (data/"thumbs"/(b["key"]+".webp")).exists())
        im = next(it for it in call("GET", "/api/images", token=token)[1]["items"] if it["id"]==aid)
        qa.check("missing derivative links are null with originals still accessible", im["thumb"] is None and im["compressed"] is None and im["compressedSize"] is None and call("GET",im["url"],raw=True)[0]==200)
        qa.check("repair excludes nonexistent originals", call("POST", "/api/admin/local/compress?dry_run=false&limit=50", token=token)[1]["done"]==1)
        gif = upload("animated.gif", tag="gif", fmt="GIF")
        qa.check("GIF without a compressed copy is not a missing format", call("GET", "/api/admin/local/index", token=token)[1]["missingCompressed"]==0)
        qa.check("clear derivatives requires explicit confirmation", call("POST", "/api/admin/local/clear-derived", {}, token)[0]==400)
        qa.check("clear derivatives is admin only", call("POST", "/api/admin/local/clear-derived", {"confirm":"clear-derived"}, user)[0]==403)
        qa.check("GET cannot trigger destructive clear", call("GET", "/api/admin/local/clear-derived", token=token)[0]==404)
        before = {it["id"]:it for it in call("GET", "/api/images", token=token)[1]["items"]}
        result = call("POST", "/api/admin/local/clear-derived", {"confirm":"clear-derived"}, token)[1]
        after = call("GET", "/api/images", token=token)[1]["items"]
        qa.check("one-click clear removes all generated files", result["removedFiles"]==5 and not result["errorCount"] and all(it["thumb"] is None and it["compressed"] is None for it in after))
        qa.check("clear preserves originals, labels, ownership and IDs", len(after)==3 and all(it["tag"]==before[it["id"]]["tag"] and it["ownerId"]==before[it["id"]]["ownerId"] and call("GET",it["url"],raw=True)[0]==200 for it in after))
        qa.check("tag random falls back to original after clearing compressed images", call("GET", "/api/random?tag=retained", token=token)[1]["compressed"] is None)
        qa.check("generated files can all be recreated", call("POST", "/api/admin/local/compress?dry_run=false&limit=50", token=token)[1]["done"]==3)
        after = call("GET", "/api/images", token=token)[1]["items"]
        qa.check("regeneration changes cache keys and retains GIF semantics", all(it["thumb"]!=before[it["id"]]["thumb"] and bool(it["compressed"])==(it["mimeType"]!="image/gif") for it in after))
        bad_thumb = data/"thumbs"/(a["key"]+".webp")
        bad_thumb.unlink(); bad_thumb.mkdir(); (bad_thumb/"blocked").write_text("blocked")
        result = call("DELETE", "/api/images/batch", {"ids":[aid,gif["id"]]}, token)[1]
        qa.check("batch deletion reports partial filesystem failure accurately", result["done"]==1 and result["failed"]==1 and any(x["id"]==aid and not x["ok"] for x in result["results"]))
        (bad_thumb/"blocked").unlink(); bad_thumb.rmdir()
        result = call("DELETE", "/api/images/batch", {"ids":[aid,cid]}, token)[1]
        qa.check("retry batch deletion removes all selected records and variants", result["done"]==2 and call("GET", "/api/images")[1]["total"]==0 and call("GET", "/api/tags")[1]["tags"]==[])
        for n in range(12): (data/"uploads"/f"pending-{n}.png").write_bytes(qa.pic())
        call("POST", "/api/admin/local/import", token=token)
        qa.check("maintenance cannot race background import", call("POST", "/api/admin/local/clear-derived", {"confirm":"clear-derived"}, token)[0]==409 and call("POST", "/api/admin/local/rebuild", token=token)[0]==409)
        call("POST", "/api/admin/local/import/cancel", token=token)
        for _ in range(200):
            if not call("GET", "/api/admin/local/status", token=token)[1]["running"]: break
            time.sleep(.1)
        print(f"\n{qa.passed} feature checks passed", flush=True)
    finally:
        proc.terminate(); proc.wait(timeout=20); log.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="features-", dir=qa.TEMP) as tmp:
        suite(Path(tmp))
