"""End-to-end check of a *packaged* beetrack app (portable folder or installed copy).

Starts the executable without a browser, then, through the REST API:
uploads a short synthetic video, saves a setup, runs an analysis (which runs in
a child process: the riskiest part of a frozen app), reads the results, and
renders a paths video. Exits non-zero with a message on any failure.

    python packaging/smoke_test.py dist/beetrack/beetrack.exe [port]
    python packaging/smoke_test.py dist/beetrack/beetrack.exe [port] --window

``--window`` checks the app window instead: it opens and loads the page, a second
start brings it to the front and exits instead of starting a second copy, and
the app writes its log file.

Needs the beetrack package installed in the *calling* Python (to make the
synthetic video) and ``requests``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


def wait(cond, timeout: float, what: str, every: float = 1.0):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = cond()
            if last:
                return last
        except requests.RequestException as e:
            last = e
        time.sleep(every)
    raise SystemExit(f"timed out waiting for {what} (last: {last})")


def app_log(work: Path) -> str:
    """The packaged app has no console: its messages are in <data>/logs/beetrack.log."""
    logs = sorted((work / "data" / "logs").glob("*.log"))
    return "\n".join(f"---- {p.name} ----\n" + p.read_text(errors="replace")[-6000:] for p in logs) or "(no log file)"


def check_window(exe: str, port: int) -> None:
    work = Path(tempfile.mkdtemp(prefix="beetrack_window_"))
    env = {**os.environ, "BEETRACK_PORT": str(port), "BEETRACK_DATA": str(work / "data")}
    env.pop("BEETRACK_NO_BROWSER", None)
    proc = subprocess.Popen([exe], env=env)
    base = f"http://127.0.0.1:{port}/api"
    try:
        wait(lambda: requests.get(f"{base}/health", timeout=2).json(), 300, "the app to start")
        first = wait(lambda: (d := requests.get(f"{base}/desktop", timeout=2).json())["window"] and d, 120,
                     "the app window to load the page")
        print("window open:", first)
        again = subprocess.run([exe], env=env, timeout=120)
        assert again.returncode == 0, f"second start exited with {again.returncode}"
        assert requests.get(f"{base}/desktop", timeout=2).json()["pid"] == first["pid"], "a second copy took over"
        assert proc.poll() is None, "the first copy stopped"
        assert (work / "data" / "logs" / "beetrack.log").exists(), "no log file"
        print("WINDOW CHECK PASSED")
    except BaseException:
        print(app_log(work))
        raise
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()


def main(exe: str, port: int = 8765) -> None:
    from beetrack.config import ExperimentSetup
    from beetrack.synthetic import SyntheticArena

    work = Path(tempfile.mkdtemp(prefix="beetrack_smoke_"))
    paths = SyntheticArena(width=640, height=360, seed=2).generate(work / "synth", duration_s=12)
    env = {**os.environ, "BEETRACK_NO_BROWSER": "1", "BEETRACK_PORT": str(port), "BEETRACK_DATA": str(work / "data")}
    log = open(work / "app.log", "w")
    proc = subprocess.Popen([exe], env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}/api"
    try:
        health = wait(lambda: requests.get(f"{base}/health", timeout=2).json(), 300, "the app to start")  # first launch: antivirus scans the new files
        print("started:", health)
        assert requests.get(f"http://127.0.0.1:{port}/", timeout=5).status_code == 200, "web page not served"
        assert requests.get(f"http://127.0.0.1:{port}/static/vendor/plotly.min.js", timeout=5).ok, "chart library missing"

        eid = requests.post(f"{base}/experiments", json={"name": "smoke"}).json()["id"]
        with open(paths["video"], "rb") as f:
            r = requests.post(f"{base}/experiments/{eid}/videos", files={"file": ("smoke.mp4", f, "video/mp4")})
        assert r.status_code == 201, r.text
        setup = ExperimentSetup.load(paths["setup"]).model_dump(mode="json")
        setup["n_bees"] = 10
        assert requests.put(f"{base}/experiments/{eid}/setup", json=setup).ok
        job = requests.post(f"{base}/experiments/{eid}/analyze").json()
        done = wait(lambda: (j := requests.get(f"{base}/jobs/{job['id']}").json())["status"] not in ("queued", "running") and j,
                    600, "the analysis")
        assert done["status"] == "done", f"analysis failed: {done.get('error') or done}"
        res = requests.get(f"{base}/experiments/{eid}/results").json()
        assert len(res["metrics"]) == 10, res["metrics"]
        print("analysis ok:", res["summary"]["n_detections"], "detections,", res["summary"]["n_visits"], "visits")

        rj = requests.post(f"{base}/experiments/{eid}/render", json={"video": "paths", "step_s": 1, "trail_s": -1}).json()
        done = wait(lambda: (j := requests.get(f"{base}/jobs/{rj['id']}").json())["status"] not in ("queued", "running") and j,
                    300, "the video render")
        assert done["status"] == "done", f"render failed: {done.get('error') or done}"
        video = requests.get(f"{base}/experiments/{eid}/download/paths.mp4").content
        assert video[4:8] == b"ftyp", "rendered file is not an MP4"
        print(f"video ok: {len(video) / 1e3:.0f} kB")
        print("SMOKE TEST PASSED")
    except BaseException:
        log.flush()
        print("---- app log ----")
        print((work / "app.log").read_text(errors="replace")[-6000:])
        print(app_log(work))
        raise
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--window"]
    port = int(args[1]) if len(args) > 1 else 8765
    (check_window if "--window" in sys.argv else main)(args[0], port)
