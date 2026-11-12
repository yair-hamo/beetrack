"""Recording helper: build (and optionally run) the ffmpeg command for one station.

Records in 1-hour segments with wall-clock timestamps, H.264, at a fixed
frame rate and resolution. Supports macOS (AVFoundation) and Linux (v4l2).

Camera settings (exposure, white balance, focus) must be **locked** before
recording; see the main README. Linux: ``v4l2-ctl``. macOS has no built-in
equivalent: use a UVC control tool (e.g. ``uvc-util``) or the camera vendor's
utility, and lock the settings before starting.
"""

from __future__ import annotations

import platform
import shlex
import subprocess
from pathlib import Path


def list_devices_command() -> list[str]:
    if platform.system() == "Darwin":
        return ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    return ["v4l2-ctl", "--list-devices"]


def build_command(
    device: str,
    out_dir: str | Path,
    station: str = "station1",
    width: int = 1920,
    height: int = 1080,
    fps: int = 15,
    segment_s: int = 3600,
    crf: int = 22,
    input_format: str = "mjpeg",
) -> list[str]:
    """ffmpeg argv. ``device`` is ``/dev/videoN`` (Linux) or an AVFoundation index like ``0`` (macOS)."""
    out = Path(out_dir) / f"{station}_%Y%m%d_%H%M%S.mkv"
    if platform.system() == "Darwin":
        src = ["-f", "avfoundation", "-framerate", str(fps), "-video_size", f"{width}x{height}",
               "-use_wallclock_as_timestamps", "1", "-i", f"{device}:none"]
        enc = ["-c:v", "h264_videotoolbox", "-b:v", "6M"]  # hardware encoder on Macs
    else:
        src = ["-f", "v4l2", "-input_format", input_format, "-video_size", f"{width}x{height}",
               "-framerate", str(fps), "-use_wallclock_as_timestamps", "1", "-i", device]
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", *src,
        "-r", str(fps), *enc, "-g", str(2 * fps), "-pix_fmt", "yuv420p",
        "-f", "segment", "-segment_time", str(segment_s), "-reset_timestamps", "0", "-strftime", "1",
        str(out),
    ]


def record(device: str, out_dir: str | Path, dry_run: bool = False, **kw) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    cmd = build_command(device, out_dir, **kw)
    printable = shlex.join(cmd)
    if not dry_run:
        subprocess.run(cmd, check=True)
    return printable
