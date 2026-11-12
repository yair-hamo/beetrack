"""Desktop launcher: what ``beetrack.exe`` (Windows) and ``beetrack-desktop`` run.

Double-click → the server starts on this computer only (127.0.0.1) and the
browser opens on it. Closing the console window stops beetrack.

* **Data** goes to ``Documents/beetrack`` (override with ``BEETRACK_DATA``), so
  installing a new version never touches experiments.
* **Already running?** If a beetrack server already answers on the port, the
  browser is just opened on it: a second double-click doesn't start a second server.
* **Port**: 8000, or the next free one. ``BEETRACK_PORT`` asks for exactly that port (an error if it's taken).
* **ffmpeg** shipped next to the executable is put on ``PATH``, so result videos
  are re-encoded to H.264.
* ``BEETRACK_NO_BROWSER=1`` skips opening the browser (used by the build checks).

The packaged app runs analyses in child processes (``spawn``), so the frozen
executable must call :func:`multiprocessing.freeze_support` before anything
else; ``packaging/launcher.py`` does.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8000


def data_dir() -> Path:
    """Where experiments live: ``$BEETRACK_DATA`` or ``~/Documents/beetrack``."""
    env = os.environ.get("BEETRACK_DATA")
    if env:
        return Path(env).expanduser()
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "beetrack"


def bundle_dir() -> Path | None:
    """Folder with the files shipped inside a packaged app (PyInstaller), or None when run from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return None


def add_bundled_ffmpeg_to_path() -> None:
    b = bundle_dir()
    if b is None:
        return
    for folder in (b / "ffmpeg", b, Path(sys.executable).parent):
        if (folder / "ffmpeg.exe").exists() or (folder / "ffmpeg").exists():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            return


def running_beetrack(port: int, timeout: float = 1.0) -> bool:
    """Is a beetrack server already answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception:
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_port(preferred: int) -> int:
    for p in range(preferred, preferred + 50):
        if port_free(p):
            return p
    with socket.socket() as s:  # anything the OS gives us
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_when_ready(server, url: str) -> None:
    for _ in range(600):  # up to a minute
        if getattr(server, "started", False):
            webbrowser.open(url)
            return
        time.sleep(0.1)


def main() -> None:
    import uvicorn

    from . import __version__
    from .server.app import create_app

    explicit = os.environ.get("BEETRACK_PORT")
    preferred = int(explicit or DEFAULT_PORT)
    browser = os.environ.get("BEETRACK_NO_BROWSER", "") not in ("1", "true", "yes")
    if running_beetrack(preferred):
        print(f"beetrack is already running: opening http://localhost:{preferred}", flush=True)
        if browser:
            webbrowser.open(f"http://localhost:{preferred}")
        return

    add_bundled_ffmpeg_to_path()
    if explicit and not port_free(preferred):
        raise SystemExit(f"port {preferred} (BEETRACK_PORT) is in use by another program")
    port = preferred if explicit else choose_port(preferred)
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    url = f"http://localhost:{port}"
    ffmpeg = shutil.which("ffmpeg")
    print(f"beetrack {__version__}", flush=True)
    print(f"  open:    {url}", flush=True)
    print(f"  data:    {data}", flush=True)
    print(f"  ffmpeg:  {ffmpeg or 'not found (result videos will play in fewer players)'}", flush=True)
    print("  Keep this window open while you work. Close it to stop beetrack.\n", flush=True)

    server = uvicorn.Server(uvicorn.Config(create_app(data), host="127.0.0.1", port=port, log_level="warning"))
    if browser:
        threading.Thread(target=_open_when_ready, args=(server, url), daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
