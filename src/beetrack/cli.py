"""Command-line interface: ``beetrack --help``.

Typical session::

    beetrack synth demo/ --duration 120          # make a test video with ground truth
    beetrack init-setup video.mp4 -o setup.json  # auto-detect the dish, write a setup template
    beetrack analyze video.mp4 -s setup.json -o results/
    beetrack evaluate results/ demo/             # compare with ground truth / annotations
    beetrack serve                               # web UI on http://localhost:8000
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer

from .config import AnalysisConfig, ExperimentSetup

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Bee tracking and queen-cell visit analysis.")


def _progress_printer():
    state = {"stage": None, "t": 0.0}

    def cb(stage: str, frac: float, msg: str) -> None:
        now = time.time()
        if stage != state["stage"] or now - state["t"] > 2 or frac >= 1:
            typer.echo(f"  [{stage:<12}] {frac * 100:5.1f}%  {msg}")
            state.update(stage=stage, t=now)

    return cb


@app.command("config-dump")
def config_dump(out: Optional[Path] = typer.Option(None, "-o", help="Write to file instead of stdout")):
    """Print the default analysis configuration as YAML (a starting point for your own)."""
    text = "# beetrack analysis configuration (defaults)\n" + AnalysisConfig().dump_yaml()
    if out:
        out.write_text(text)
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command("init-setup")
def init_setup(
    video: Path,
    out: Path = typer.Option(Path("setup.json"), "-o"),
    diameter_mm: float = typer.Option(150.0, help="Inner dish diameter"),
):
    """Detect the dish in the first frame and write a setup template (queen cell still to be drawn)."""
    from .calibration import detect_dish
    from .video import read_frame

    frame = read_frame(video, 0)
    dish = detect_dish(frame, diameter_mm)
    setup = ExperimentSetup(dish=dish)
    setup.save(out)
    if dish is None:
        typer.secho("dish not found automatically; set it in the web UI", fg="yellow")
    else:
        typer.echo(f"dish: centre={tuple(round(v) for v in dish.center_px)} radius={dish.radius_px:.0f}px "
                   f"→ {2 * dish.radius_px / diameter_mm:.2f} px/mm")
    typer.echo(f"wrote {out}. Add the queen-cell polygon and check the bee codes (or use the web UI).")


@app.command()
def analyze(
    videos: list[Path] = typer.Argument(..., help="One or more video segments, in time order"),
    setup: Path = typer.Option(..., "-s", "--setup", help="setup.json"),
    out: Path = typer.Option(Path("results"), "-o"),
    config: Optional[Path] = typer.Option(None, "-c", "--config", help="YAML analysis config"),
    sleap: Optional[Path] = typer.Option(None, help="SLEAP analysis .h5 (deep-learning route)"),
    max_frames: Optional[int] = typer.Option(None, help="Debug: analyse only this many frames"),
):
    """Run the full pipeline and write results."""
    from .pipeline import AnalysisPipeline

    cfg = AnalysisConfig.load(config)
    if max_frames:
        cfg.max_frames = max_frames
    res = AnalysisPipeline(cfg, ExperimentSetup.load(setup), _progress_printer()).run(videos, out, sleap_h5=sleap)
    s = res.summary
    typer.secho(f"\n✓ {s['analysed_frames']} frames, {len(s['bees_found'])} bees identified, "
                f"visits: {s['n_visits']}  →  {out}", fg="green")
    for w in s["warnings"]:
        typer.secho(f"  ! {w}", fg="yellow")
    if not res.metrics.empty:
        cols = [c for c in res.metrics.columns if c in ("bee_id", "tracked_fraction", "contact_visits", "contact_total_s")]
        typer.echo(res.metrics[cols].round(2).to_string(index=False))


@app.command()
def evaluate(
    results: Path = typer.Argument(..., help="Results directory"),
    truth: Path = typer.Argument(..., help="Directory with ground_truth.parquet (+ ground_truth_visits.csv), or an annotations CSV"),
    tol_mm: float = typer.Option(4.0),
):
    """Accuracy against ground truth or hand annotations."""
    import pandas as pd

    from .evaluation import compare_visits, evaluate_tracks

    pred = pd.read_parquet(results / "trajectories.parquet")
    gt = pd.read_parquet(truth / "ground_truth.parquet") if truth.is_dir() else pd.read_csv(truth)
    e = evaluate_tracks(pred, gt, tol_mm)
    typer.echo(json.dumps({k: v for k, v in e.items() if k != "per_bee"}, indent=2))
    typer.echo(e["per_bee"].round(3).to_string(index=False))
    gv = truth / "ground_truth_visits.csv" if truth.is_dir() else None
    if gv and gv.exists():
        typer.echo("\nvisits (true vs predicted):")
        typer.echo(compare_visits(pd.read_csv(results / "visits.csv"), pd.read_csv(gv)).round(1).to_string(index=False))


@app.command()
def synth(
    out: Path = typer.Argument(Path("synthetic_demo")),
    duration: float = typer.Option(60.0, help="Seconds"),
    seed: int = typer.Option(0),
    width: int = 1280,
    height: int = 720,
    fps: float = 15.0,
):
    """Generate a synthetic test video with exact ground truth."""
    from .synthetic import SyntheticArena

    paths = SyntheticArena(width=width, height=height, fps=fps, seed=seed).generate(out, duration)
    for k, p in paths.items():
        typer.echo(f"{k:>13}: {p}")


@app.command()
def record(
    device: str = typer.Argument(..., help="/dev/videoN (Linux) or AVFoundation index, e.g. 0 (macOS)"),
    out: Path = typer.Option(Path("recordings"), "-o"),
    station: str = typer.Option("station1"),
    fps: int = 15,
    width: int = 1920,
    height: int = 1080,
    dry_run: bool = typer.Option(False, help="Only print the ffmpeg command"),
):
    """Record a station in 1-hour segments (ffmpeg)."""
    from .recording import record as _record

    cmd = _record(device, out, dry_run=dry_run, station=station, fps=fps, width=width, height=height)
    typer.echo(cmd)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="0.0.0.0 = reachable from other lab computers"),
    port: int = 8000,
    data: Path = typer.Option(Path("data"), help="Where experiments, videos and results are stored"),
):
    """Start the web server (upload videos, set up experiments, run analyses, explore results)."""
    import uvicorn

    from .server.app import create_app

    typer.echo(f"beetrack server → http://localhost:{port}   (data: {data.resolve()})")
    uvicorn.run(create_app(data), host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
