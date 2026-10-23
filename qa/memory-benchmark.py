"""Measure the built service, including post-upload worker exit.

python -m pip install psutil
python qa/memory-benchmark.py

RSS/working set is OS-specific; it is not Docker cgroup usage. Creates an
isolated legacy database with 10,000 metadata rows and 83 real fixture files.
"""
import concurrent.futures
import argparse
import importlib.util
import json
import platform
from pathlib import Path
import sqlite3
import statistics
import tempfile
import threading
import time

import psutil

spec = importlib.util.spec_from_file_location("regression", Path(__file__).with_name("regression.py"))
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


def memory(process):
    infos = [process.memory_info()] + [p.memory_info() for p in process.children(recursive=True)]
    return {"rss_mib": round(sum(info.rss for info in infos) / 1048576, 2),
            "private_mib": round(sum(getattr(info, "private", info.vms) for info in infos) / 1048576, 2)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-python", type=Path)
    parser.add_argument("--legacy-backend", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="memory-", dir=qa.TEMP) as temp:
        data = Path(temp)
        qa.seed_legacy(data)
        db = sqlite3.connect(data / "metadata.db")
        db.executemany("INSERT INTO images(id,key,mime,width,height,size,created_at) VALUES(?,?,?,?,?,?,?)",
                       [(f"metadata-{n:05d}", f"metadata/{n}.png", "image/png", 64, 48, 160, "2026-01-01T00:00:00+00:00") for n in range(9917)])
        db.commit()
        db.close()
        proc, log, call, env = qa.run(data, args.legacy_python, args.legacy_backend)
        process = psutil.Process(proc.pid)
        try:
            time.sleep(1)
            baseline_children = {p.pid for p in process.children(recursive=True)}
            idle = memory(process)
            token = call("POST", "/api/auth/login", {"username": "owner", "password": "qa-pass-123"})[1]["token"]
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                statuses = list(pool.map(lambda n: call("GET", ("/api/images?limit=36", "/api/tags", "/api/public/settings", "/api/auth/me")[n % 4], token=token)[0], range(1024)))
            if set(statuses) != {200}:
                raise AssertionError(f"load failure: {set(statuses)}")
            browsing = memory(process)
            body, headers = qa.multipart([("files", "large.bmp", qa.pic("BMP", (3500, 2200)))])
            samples = []
            children_seen = set()
            done = threading.Event()

            def sample():
                while not done.wait(.025):
                    children = process.children(recursive=True)
                    children_seen.update(p.pid for p in children)
                    total = process.memory_info().rss
                    for child in children:
                        try:
                            total += child.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                    samples.append(total / 1048576)

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
                settled.append(memory(process))
            live_children = [p.name() for p in process.children(recursive=True) if p.is_running() and p.pid not in baseline_children]
            if live_children:
                raise AssertionError(f"persistent image workers: {live_children}")
            report = {"platform": platform.platform(), "metric": "process RSS / Windows working set; MiB; not Docker cgroup",
                      "engine": "legacy-python" if args.legacy_python else "go",
                      "library_metadata_rows": 10000, "real_fixture_files_before_upload": 83,
                      "requests": 1024, "concurrency": 16, "idle": idle, "after_browsing": browsing,
                      "upload_process_tree_peak_mib": round(max(samples, default=0), 2),
                      "image_worker_processes_observed": len(children_seen - baseline_children), "persistent_image_workers": live_children,
                      "post_upload_median_rss_mib": statistics.median(x["rss_mib"] for x in settled),
                      "post_upload_samples": settled,
                      "docker_measurement": "pending container build and test"}
            out = qa.ROOT / "artifacts/memory-windows.json"
            if platform.system() != "Windows":
                out = qa.ROOT / "artifacts/memory-native.json"
            if args.legacy_python:
                out = out.with_name("memory-legacy-" + platform.system().lower() + ".json")
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
            if not args.legacy_python and max(idle["rss_mib"], browsing["rss_mib"], report["post_upload_median_rss_mib"]) > 70:
                raise AssertionError("steady-state process RSS exceeds the 70MiB target")
        finally:
            children = process.children(recursive=True)
            for child in children:
                child.terminate()
            psutil.wait_procs(children, timeout=10)
            proc.terminate()
            proc.wait(timeout=10)
            log.close()


if __name__ == "__main__":
    main()
