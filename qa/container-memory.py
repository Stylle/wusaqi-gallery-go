"""Measure the real image on a Linux Docker host, using disposable data.

QA_DOCKER_IMAGE=wusaqi-gallery:local python qa/container-memory.py
Reports cgroup v2 memory, Docker's cache-adjusted usage, and process RSS.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import tempfile
import threading
import time

import psutil
import regression as qa

MIB = 1048576


def main():
    image = os.environ.get("QA_DOCKER_IMAGE")
    if not image or platform.system() != "Linux":
        raise SystemExit("Set QA_DOCKER_IMAGE and run on the Linux Docker host (WSL 2 is supported)")
    with tempfile.TemporaryDirectory(prefix="container-memory-", dir=qa.TEMP) as tmp:
        data = Path(tmp)
        qa.seed_legacy(data)
        with sqlite3.connect(data / "metadata.db") as db:
            db.executemany("INSERT INTO images(id,key,mime,width,height,size,created_at) VALUES(?,?,?,?,?,?,?)",
                           [(f"metadata-{n:05d}", f"metadata/{n}.png", "image/png", 64, 48, 160,
                             "2026-01-01T00:00:00+00:00") for n in range(9917)])
        proc, log, call, env = qa.run(data)
        name = "wusaqi-regression-" + env["LISTEN_ADDR"].rsplit(":", 1)[1]
        try:
            info = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
            process = psutil.Process(info["State"]["Pid"])
            cg_path = next(line.split(":", 2)[2] for line in Path(f"/proc/{process.pid}/cgroup").read_text().splitlines()
                           if line.startswith("0::"))
            cgroup = Path("/sys/fs/cgroup") / cg_path.lstrip("/")

            def memory():
                stat = dict(line.split() for line in (cgroup / "memory.stat").read_text().splitlines())
                current = int((cgroup / "memory.current").read_text())
                inactive = int(stat.get("inactive_file", 0))
                return {"docker_usage_mib": round(max(0, current - inactive) / MIB, 2),
                        "cgroup_current_mib": round(current / MIB, 2),
                        "anonymous_mib": round(int(stat.get("anon", 0)) / MIB, 2),
                        "file_cache_mib": round(int(stat.get("file", 0)) / MIB, 2),
                        "inactive_file_mib": round(inactive / MIB, 2),
                        "process_tree_rss_mib": round(sum(p.memory_info().rss for p in [process] + process.children(recursive=True)) / MIB, 2)}

            def stats():
                return json.loads(subprocess.check_output(["docker", "stats", "--no-stream", "--format", "{{json .}}", name]))

            time.sleep(2)
            idle, idle_stats = memory(), stats()
            token = call("POST", "/api/auth/login", {"username": "owner", "password": "qa-pass-123"})[1]["token"]
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                statuses = list(pool.map(lambda n: call("GET", ("/api/images?limit=36", "/api/tags", "/api/public/settings", "/api/auth/me")[n % 4], token=token)[0], range(1024)))
            if set(statuses) != {200}:
                raise AssertionError(f"HTTP load failed: {set(statuses)}")
            browsing, browsing_stats = memory(), stats()
            body, headers = qa.multipart([("files", "large.bmp", qa.pic("BMP", (3500, 2200)))])
            samples, worker_ids = [], set()
            done = threading.Event()

            def sample():
                while not done.wait(.025):
                    try:
                        worker_ids.update(p.pid for p in process.children(recursive=True))
                        samples.append(memory())
                    except (psutil.NoSuchProcess, ProcessLookupError):
                        pass

            sampler = threading.Thread(target=sample, daemon=True)
            sampler.start()
            try:
                status, result = call("POST", "/api/upload", body, token, headers)
                if status != 200 or not result["results"][0]["ok"]:
                    raise AssertionError(result)
            finally:
                done.set()
                sampler.join()
            settled = []
            for _ in range(5):
                time.sleep(1)
                settled.append(memory())
            live = [p.name() for p in process.children(recursive=True) if p.is_running()]
            if live:
                raise AssertionError(f"Image workers did not exit: {live}")
            final_stats = stats()
            health = subprocess.run(["docker", "exec", name, "/app/gallery", "healthcheck"], capture_output=True)
            if health.returncode:
                raise AssertionError("Container healthcheck failed")
            image_info = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
            report = {"platform": platform.platform(), "engine": "go-docker", "image": image,
                      "image_id": image_info["Id"], "architecture": image_info["Architecture"],
                      "image_size_bytes": image_info["Size"], "cgroup": "v2",
                      "memory_limit_bytes": info["HostConfig"]["Memory"],
                      "cpu_limit": info["HostConfig"]["NanoCpus"] / 1e9,
                      "metric": "MiB; Docker usage = memory.current - inactive_file; RSS reported separately",
                      "library_metadata_rows": 10000, "real_fixture_files_before_upload": 83,
                      "requests": 1024, "concurrency": 16, "idle": idle, "after_browsing": browsing,
                      "upload_peak_docker_usage_mib": max((s["docker_usage_mib"] for s in samples), default=0),
                      "upload_peak_process_tree_rss_mib": max((s["process_tree_rss_mib"] for s in samples), default=0),
                      "image_worker_processes_observed": len(worker_ids), "persistent_image_workers": live,
                      "post_upload_median_docker_usage_mib": statistics.median(s["docker_usage_mib"] for s in settled),
                      "post_upload_samples": settled,
                      "docker_stats": {"idle": idle_stats, "after_browsing": browsing_stats, "after_upload": final_stats}}
            out = qa.ROOT / "artifacts/memory-docker.json"
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
            if max(idle["docker_usage_mib"], browsing["docker_usage_mib"], report["post_upload_median_docker_usage_mib"]) > 70:
                raise AssertionError("Steady-state Docker memory exceeds the 70 MiB target")
        finally:
            proc.terminate()
            proc.wait(timeout=20)
            log.close()


if __name__ == "__main__":
    main()
