"""Desktop app: what ``beetrack.exe`` (Windows) and ``beetrack-desktop`` run.

Double-click → beetrack opens in **its own window** (no console, no browser tab).
Behind the window a web server runs on this computer only (127.0.0.1); the window
shows the same pages a browser would, so everything in the interface works the same.

* **One window, one copy.** Starting beetrack again while it runs brings the open
  window to the front instead of starting a second copy (the running copy writes its
  port to ``<data>/.beetrack-instance.json``).
* **Safe close.** Closing the window while an analysis runs, or with an unsaved setup,
  asks first. Quitting stops the server and any running analysis.
* **Data** goes to ``Documents/beetrack`` (override with ``BEETRACK_DATA``), so
  installing a new version never touches experiments. The packaged app has no console:
  its messages go to ``<data>/logs/beetrack.log``.
* **No app window possible?** (the Microsoft Edge WebView2 runtime missing, or running
  from source without ``pywebview``) → the browser opens instead, and a small
  "beetrack is running — OK to stop" message box (Windows) or the console keeps it alive.
* **Port**: 8000, or the next free one. ``BEETRACK_PORT`` asks for exactly that port (an error if it's taken).
* **ffmpeg** shipped next to the executable is put on ``PATH``, so result videos
  are re-encoded to H.264.
* ``BEETRACK_NO_BROWSER=1`` runs the server only, without a window or browser (the build checks use it).

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
import traceback
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8000
INSTANCE_FILE = ".beetrack-instance.json"
LOG_MAX_BYTES = 5_000_000


# --------------------------------------------------------------------------- #
# places
# --------------------------------------------------------------------------- #
def data_dir() -> Path:
    """Where experiments live: ``$BEETRACK_DATA`` or ``~/Documents/beetrack``."""
    env = os.environ.get("BEETRACK_DATA")
    if env:
        return Path(env).expanduser()
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "beetrack"


def webview_storage_dir() -> Path:
    """Where the app window keeps its browser state (e.g. the chosen light/dark theme)."""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".cache") / "beetrack" / "webview"


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


def log_to_file(data: Path) -> Path:
    """Send ``print`` and server messages to ``<data>/logs/beetrack.log`` (the packaged app has no console)."""
    logs = data / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "beetrack.log"
    if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
        path.replace(logs / "beetrack.previous.log")
    f = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f
    return path


def alert(title: str, message: str) -> None:
    """A message the user sees even without a console: a Windows message box, else stderr."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x10000)  # information icon, foreground
            return
        except Exception:
            pass
    print(f"{title}: {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# ports and the running copy
# --------------------------------------------------------------------------- #
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


def read_instance(data: Path) -> int | None:
    """Port of the beetrack already running on this data folder, if it still answers."""
    try:
        port = int(json.loads((data / INSTANCE_FILE).read_text())["port"])
    except Exception:
        return None
    return port if running_beetrack(port) else None


def write_instance(data: Path, port: int) -> None:
    (data / INSTANCE_FILE).write_text(json.dumps({"port": port, "pid": os.getpid()}))


def remove_instance(data: Path) -> None:
    try:
        if json.loads((data / INSTANCE_FILE).read_text()).get("pid") == os.getpid():
            (data / INSTANCE_FILE).unlink()
    except Exception:
        pass


def bring_to_front(port: int) -> bool:
    """Ask the running copy to show its window. False if it has no window (e.g. an older version)."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/desktop/show", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=3) as r:
            return bool(json.loads(r.read().decode()).get("shown"))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# the window
# --------------------------------------------------------------------------- #
class DesktopState:
    """What the window and the server share: the window itself, and whether the page has unsaved work."""

    def __init__(self, db=None):
        self.db = db
        self.window = None
        self.loaded = threading.Event()
        self.unsaved = False
        self.quitting = False
        self.asking = False

    def active_jobs(self) -> int:
        """Analyses and video renders queued or running."""
        if self.db is None:
            return 0
        from .server.db import Job

        with self.db.session() as s:
            return s.query(Job).filter(Job.status.in_(("queued", "running"))).count()

    def close_reasons(self) -> list[str]:
        reasons = []
        n = self.active_jobs()
        if n:
            what = "An analysis or video is" if n == 1 else f"{n} analyses or videos are"
            reasons.append(f"{what} still running or waiting. Quitting stops {'it' if n == 1 else 'them'}: "
                           "you will have to start again.")
        if self.unsaved:
            reasons.append("The setup has changes that are not saved.")
        return reasons

    def on_closing(self) -> bool:
        """Window close button. Returns False to keep the window open (then asks in a dialog)."""
        if self.quitting:
            return True
        if self.asking:
            return False
        try:
            reasons = self.close_reasons()
        except Exception:
            reasons = []
        if not reasons:
            self.quitting = True
            return True
        # The close handler runs on the window's own thread: a dialog opened from here would freeze it.
        self.asking = True
        threading.Thread(target=self._ask_and_quit, args=(reasons,), daemon=True).start()
        return False

    def _ask_and_quit(self, reasons: list[str]) -> None:
        try:
            if self.window.create_confirmation_dialog("Quit beetrack?", "\n\n".join(reasons + ["Quit anyway?"])):
                self.quitting = True
                self.window.destroy()
        finally:
            self.asking = False

    def show(self) -> bool:
        w = self.window
        if w is None:
            return False
        try:
            w.restore()
            w.show()
            w.on_top = True   # brings it in front of other programs; then behave normally again
            w.on_top = False
        except Exception:
            pass
        return True


class PageApi:
    """Called from the page (``window.pywebview.api``)."""

    def __init__(self, state: DesktopState):
        self._state = state

    def set_unsaved(self, flag) -> None:
        self._state.unsaved = bool(flag)


def add_desktop_routes(app, state: DesktopState) -> None:
    @app.get("/api/desktop", include_in_schema=False)
    def desktop_status():
        return {"window": state.loaded.is_set(), "pid": os.getpid()}

    @app.post("/api/desktop/show", include_in_schema=False)
    def desktop_show():
        return {"shown": state.show()}


def open_window(url: str, state: DesktopState, title: str) -> None:
    """Show the app window and return when it's closed. Raises if no window can be made here."""
    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True              # "⬇ Download" buttons save files
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    w = webview.create_window(title, url, js_api=PageApi(state), width=1360, height=880,
                              min_size=(960, 640), text_select=True, background_color="#f6f7f9")
    state.window = w
    w.events.closing += state.on_closing
    w.events.loaded += state.loaded.set
    storage = webview_storage_dir()
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage))


def wait_in_browser(url: str, server_thread: threading.Thread) -> None:
    """No app window: open the browser and keep beetrack alive until the user stops it."""
    webbrowser.open(url)
    if sys.platform == "win32":
        alert("beetrack", f"beetrack is open in your web browser:\n{url}\n\n"
                          "Keep this message open while you work. Click OK to stop beetrack.")
        return
    print("  Keep this window open while you work. Close it (or Ctrl+C) to stop beetrack.\n", flush=True)
    try:
        while server_thread.is_alive():
            server_thread.join(0.5)
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    frozen = bundle_dir() is not None
    data = data_dir()
    log = None
    if frozen or sys.stdout is None:
        data.mkdir(parents=True, exist_ok=True)
        log = log_to_file(data)
    try:
        _main(data)
    except SystemExit as e:
        if frozen and e.code not in (None, 0):
            alert("beetrack could not start", str(e.code))
        raise
    except Exception:
        traceback.print_exc()
        if frozen:
            alert("beetrack could not start", f"Something went wrong while starting beetrack.\n\nDetails are in:\n{log}")
        raise


def _main(data: Path) -> None:
    import uvicorn

    from . import __version__
    from .server.app import create_app

    explicit = os.environ.get("BEETRACK_PORT")
    preferred = int(explicit or DEFAULT_PORT)
    headless = os.environ.get("BEETRACK_NO_BROWSER", "") in ("1", "true", "yes")

    # already running? → show that one
    data.mkdir(parents=True, exist_ok=True)
    other = read_instance(data) or (preferred if running_beetrack(preferred) else None)
    if other is not None:
        print(f"beetrack is already running on port {other}", flush=True)
        if not headless and not bring_to_front(other):
            webbrowser.open(f"http://localhost:{other}")   # an older beetrack without a window
        return

    add_bundled_ffmpeg_to_path()
    if explicit and not port_free(preferred):
        raise SystemExit(f"port {preferred} (BEETRACK_PORT) is in use by another program")
    port = preferred if explicit else choose_port(preferred)
    url = f"http://localhost:{port}"
    print(f"beetrack {__version__}  ({time.strftime('%Y-%m-%d %H:%M:%S')})", flush=True)
    print(f"  address: {url}", flush=True)
    print(f"  data:    {data}", flush=True)
    print(f"  ffmpeg:  {shutil.which('ffmpeg') or 'not found (result videos will play in fewer players)'}", flush=True)

    app = create_app(data)
    state = DesktopState(app.state.db)
    add_desktop_routes(app, state)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    if headless:
        write_instance(data, port)
        try:
            server.run()
        finally:
            remove_instance(data)
        return

    thread = threading.Thread(target=server.run, name="beetrack-server", daemon=True)
    thread.start()
    for _ in range(600):  # up to a minute (first start: antivirus scans the new files)
        if server.started or not thread.is_alive():
            break
        time.sleep(0.1)
    if not server.started:
        raise SystemExit("the beetrack server did not start (see the log for details)")
    write_instance(data, port)
    try:
        try:
            open_window(url, state, f"beetrack {__version__}")
        except Exception as e:
            print(f"  no app window ({type(e).__name__}: {e}); using the browser instead", flush=True)
            if state.window is None or not state.loaded.is_set():
                wait_in_browser(url, thread)
    finally:
        remove_instance(data)
        server.should_exit = True     # also stops the analysis worker and any running analysis
        thread.join(30)
    print("beetrack stopped", flush=True)


if __name__ == "__main__":
    main()
