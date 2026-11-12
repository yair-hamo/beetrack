# Architecture

## Goals that shaped the design

1. **Reproducible science.** Every result folder contains `summary.json` with the exact configuration,
   experiment setup, software version and input files. Runs are never overwritten.
2. **One analysis, many front-ends.** The pipeline is a plain library (`AnalysisPipeline`). The CLI,
   the web worker, tests and notebooks all call the same code.
3. **Physical units everywhere.** Configuration is in mm and seconds. Pixels and frames appear only
   inside the pipeline, so a different camera or frame rate doesn't change the meaning of a parameter.
4. **Unknown ≠ outside.** Missing data stays missing (NaN). Every metric reports its coverage.
5. **Swappable stages.** Detection and identity sit behind small interfaces. The deep-learning route
   (SLEAP) and a possible tag reader plug in without touching visits or metrics.

## Layers

```
┌───────────────────────────── server/ ──────────────────────────────┐
│  static/ (SPA)  ⇄  api.py (FastAPI)  ─  db.py (SQLite)  store.py   │
│                          │ queue job                               │
│                    worker.py ── spawns ──► child process           │
└──────────────────────────────────────────────┬─────────────────────┘
                                                │ AnalysisPipeline.run()
┌──────────────────────────── core library ────▼─────────────────────┐
│ config.py   video.py   calibration.py                              │
│ detection/ ─► identity/color_id ─► tracking/ ─► identity/resolver  │
│        └─(or) detection/sleap_import ─────────────┐                │
│                                                    ▼               │
│               trajectories.py ─► behavior/visits ─► behavior/metrics│
└────────────────────────────────────────────────────────────────────┘
```

* **Core library**: no web or database imports. Pure functions and small classes, tested on synthetic video.
* **Server**: thin. It stores metadata, moves files, queues jobs, and serves results and frame previews.

## Main types

| Type | Where | Role |
|---|---|---|
| `AnalysisConfig` | `config.py` | *How* to analyse. Shared across a study, saved as YAML. |
| `ExperimentSetup` | `config.py` | *What* is in a video: dish geometry, queen-cell polygon, bee registry (ID + dot colour). |
| `Recording` | `video.py` | One or more segments presented as one timeline (global frame index, seconds). |
| `Geometry` | `calibration.py` | px↔mm conversion, arena mask, distance to the queen cell, zone outlines. |
| `Detection` | `models.py` | One bee-sized blob in one frame, enriched stage by stage (colours → tracklet → bee). |
| `Detector` (protocol) | `detection/base.py` | `prepare(samples)`, `detect(frame) → (detections, masks)`. |
| `ColorCodeIdentifier` | `identity/color_id.py` | Mask + frame → observed colours, spot positions, evidence per bee. |
| `OnlineTracker` | `tracking/tracker.py` | Frame-to-frame linking → tracklet IDs. |
| `IdentityResolver` | `identity/resolver.py` | Tracklets + evidence → bee IDs (switch splitting, conflict-free assignment, gap linking). |
| `VisitDetector` | `behavior/visits.py` | Trajectories → visits per zone. |
| `AnalysisPipeline` | `pipeline.py` | Orchestration, progress reporting, output files. |

## Data flow and tables

During detection, frames are processed one at a time. Only detection rows are kept, compacted into
DataFrame chunks, plus a small evidence dict per detection for the identity step. One hour
(about 0.5 M detections) needs a few hundred MB. **A 48 h run (about 26 M detections) needs
several GB of RAM** in this version. Until a streaming writer is added (planned: write detection
chunks to Parquet and resolve identity per time window), analyse long recordings in 6–12 h blocks
(one experiment per block) on a Mac with 16 GB.

After detection, stages exchange `pandas` tables: `detections` → `trajectories` → `visits` /
`metrics` / `binned`. Their schemas are in [DATA_FORMATS.md](DATA_FORMATS.md).

## Server design

* **Storage**: SQLite (WAL mode) holds metadata only. Videos and results are ordinary files under
  `data/experiments/NNNN/` and stay usable without the server.
* **Jobs**: `JobWorker` (a thread) runs one job at a time in a `spawn`ed child process. The child writes
  progress to SQLite, and the UI polls `/api/jobs/{id}`. Cancelling terminates the process. Jobs
  interrupted by a server restart are marked failed at startup.
* **UI**: one static page (`index.html`, `app.js`, `styles.css`), no build step, Plotly from a CDN for
  charts. Frames are rendered server-side with overlays (`overlay.py`), so the browser never decodes
  the raw video.

## Extension points

| You want… | Do this |
|---|---|
| A deep-learning detector (YOLO, SLEAP live) | Implement `Detector`, or produce a SLEAP analysis `.h5` and pass `--sleap`. |
| Tags instead of paint | Write a `TagIdentifier` with the same `identify(frame, dets, patches)` that fills `color_scores` with tag evidence. The resolver works unchanged. |
| More zones (e.g. the feeder) | Add a `Zone` to `visits.zones`. For a second object, generalise `ExperimentSetup.queen_cell` to a list of named ROIs. |
| Bee–bee interactions | Add `behavior/interactions.py` working on `trajectories` (head-to-head distance, durations). |
| Live recording from the UI | Wrap `recording.build_command` in a job type. |
