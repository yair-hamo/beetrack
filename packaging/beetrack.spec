# PyInstaller recipe for the desktop app: one folder with beetrack.exe (console window = "close to stop").
# Build:  pyinstaller packaging/beetrack.spec --noconfirm --distpath dist --workpath build/pyi
# Optional inputs (the GitHub workflow provides them on Windows):
#   build/ffmpeg/ffmpeg.exe (+ FFMPEG-LICENSE.txt)  → bundled, so result videos are H.264
#   packaging/beetrack.ico                          → the exe icon
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

hidden = collect_submodules("beetrack") + collect_submodules("uvicorn")
for mod in ("multipart", "python_multipart"):  # python-multipart changed its import name
    try:
        hidden += collect_submodules(mod)
    except Exception:
        pass

datas = collect_data_files("beetrack") + [(os.path.join(ROOT, "LICENSE"), ".")]
binaries = []
ffmpeg_dir = os.path.join(ROOT, "build", "ffmpeg")
for name in ("ffmpeg.exe", "ffmpeg"):
    if os.path.exists(os.path.join(ffmpeg_dir, name)):
        binaries.append((os.path.join(ffmpeg_dir, name), "ffmpeg"))
if os.path.exists(os.path.join(ffmpeg_dir, "FFMPEG-LICENSE.txt")):
    datas.append((os.path.join(ffmpeg_dir, "FFMPEG-LICENSE.txt"), "ffmpeg"))

icon = os.path.join(SPECPATH, "beetrack.ico")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "pytest", "playwright", "IPython", "jupyter", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="beetrack",
    console=True,
    icon=icon if os.path.exists(icon) else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="beetrack")
