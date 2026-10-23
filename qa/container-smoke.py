"""Deployment smoke test, also suitable for ARM64 under QEMU.

QA_DOCKER_IMAGE=wusaqi-gallery:multi QA_DOCKER_PLATFORM=linux/arm64 python qa/container-smoke.py
"""
import io
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

import regression as qa


def main():
    if not os.environ.get("QA_DOCKER_IMAGE"):
        raise SystemExit("Set QA_DOCKER_IMAGE to the image to verify")
    with tempfile.TemporaryDirectory(prefix="container-smoke-", dir=qa.TEMP) as tmp:
        data = Path(tmp)
        qa.seed_legacy(data)
        proc, log, call, env = qa.run(data)
        try:
            qa.check("image serves bundled Vue UI", b'<div id="app">' in call("GET", "/", raw=True)[1])
            status, login = call("POST", "/api/auth/login", {"username": "owner", "password": "qa-pass-123"})
            qa.check("legacy account authenticates inside image", status == 200)
            token = login["token"]
            qa.check("legacy images migrate", len(call("GET", "/api/images?limit=100", token=token)[1]["items"]) == 83)
            body, headers = qa.multipart([("files", "container.png", qa.pic())], {"tag":"container"})
            status, uploaded = call("POST", "/api/upload", body, token, headers)
            qa.check("container Pillow processes upload", status == 200 and uploaded["results"][0]["ok"])
            item = uploaded["results"][0]["item"]
            for key in ("url", "thumb", "compressed"):
                qa.check("container serves " + key, bool(item.get(key)) and call("GET", item[key], raw=True)[0] == 200)
            qa.check("admin settings save", call("PUT", "/api/admin/settings", {"site_title":"Container smoke"}, token)[0] == 200)
            status, backup = call("GET", "/api/admin/backup", token=token, raw=True)
            qa.check("container backup streams a valid ZIP", status == 200 and zipfile.is_zipfile(io.BytesIO(backup)))
            qa.check("image healthcheck succeeds", subprocess.run(qa.service_command(env, healthcheck=True), capture_output=True).returncode == 0)
            proc.terminate()
            proc.wait(timeout=20)
            log.close()
            proc, log, call, env = qa.run(data)
            qa.check("container restart retains session", call("GET", "/api/auth/me", token=token)[0] == 200)
            qa.check("container restart retains settings", call("GET", "/api/public/settings")[1]["site_title"] == "Container smoke")
            print(f"\n{qa.passed} container smoke checks passed", flush=True)
        finally:
            proc.terminate()
            proc.wait(timeout=20)
            log.close()


if __name__ == "__main__":
    main()
