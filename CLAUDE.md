# CLAUDE.md: handover notes for agents working on beetrack

Read this first. It says what the project is, how the code is laid out, how to run and test it, how to
contribute (branch + PR), which design decisions are deliberate (don't undo them), what is known to be weak,
and what to do next. The user-facing README is short on purpose; the deep information lives here and in `docs/`.

## 1. What the project is

A research lab films **~10 honeybee workers + one queen cell (with a queen larva)** in a petri dish,
for up to 48 h, and wants to know **which worker visits the queen cell, how often and for how long**, plus the
**full path of every bee**. The experiment lead is a doctor at the university; the user (Yair, GitHub
`yair-hamo`) builds the rig and the software. He writes informal English, sometimes with Hebrew file names.

```
beetrack/                     ← repository root (github.com/yair-hamo/beetrack, public)
├── README.md                 short user guide with result GIFs
├── CLAUDE.md                 this file
├── LICENSE                   MIT
├── pyproject.toml            package metadata; version
├── config/default.yaml       all analysis parameters (regenerate: beetrack config-dump -o config/default.yaml)
├── docs/                     HARDWARE (rig, camera, lighting, marking, budget) · ARCHITECTURE · PIPELINE ·
│   │                         DATA_FORMATS · API · VALIDATION · SLEAP
│   └── assets/               README GIFs (annotated, paths, heatmap) + concept drawing
├── src/beetrack/             the package (see §4)
├── tests/                    173 tests (see §8)
├── data/                     the user's experiments (git-ignored, never commit)
└── demo/                     synthetic demo video (git-ignored)
```

Outside the repository, in its parent folder on the user's Mac, the user keeps `artifacts/` (videos he
rendered with the app; the README GIFs were made from them) and sometimes sample videos.

The **real setup** (from the sample `output.mp4`, 452×414, 15 fps, 62 s): a *vertical* dish standing on wood, a
comb-foundation background (cream hexagons), the queen cell hanging at the top (dark brown wax, bees cluster
on it), a water tube on the right, dark yellow food at the bottom left. Lighting is uneven, condensation fogs
parts of the dish. Marks seen so far: plum, pink, red, blue/violet, mint, white, small and pale at 452 px.
The user plans to mark both sides of the bees and to use **fluorescent (neon) paint**. The dish's inner
diameter is unknown (the bees suggest ~75 mm).

## 2. Running it

```bash
python3 -m venv .venv && source .venv/bin/activate     # Python ≥ 3.10 (dev machine: 3.12, macOS)
pip install -e ".[dev]" && playwright install chromium   # once
beetrack serve                         # web app → http://localhost:8000 (data in ./data)
beetrack analyze VIDEO -s setup.json -o results/           # same pipeline without the web app
beetrack synth demo/ --duration 60     # synthetic video with exact ground truth
pytest                                 # 173 tests, ~3.5 min (≈60 are browser tests)
pytest -m "not ui"                     # skip browser tests
pytest tests/test_ui.py --headed --slowmo 300              # watch the browser tests
```

| CLI command | Purpose |
|---|---|
| `beetrack serve [--port 8000] [--data data/] [--host 127.0.0.1]` | web app (listens on all interfaces by default) |
| `beetrack analyze VIDEO... -s setup.json [-c config.yaml] [-o results/] [--sleap preds.h5]` | run the pipeline |
| `beetrack init-setup VIDEO -o setup.json` | auto-detect the dish and write a setup template |
| `beetrack evaluate RESULTS TRUTH` | accuracy against ground truth or hand annotations |
| `beetrack synth OUT --duration 60` | synthetic test video |
| `beetrack record DEVICE --station s1 [--dry-run]` | record 1-hour segments with ffmpeg |
| `beetrack config-dump` | print the default configuration |

**The user runs `beetrack serve` himself.** Python loads code once, so after any change to `src/`, tell the
user to stop the server (Ctrl+C) and start it again. A page/server version mismatch shows a red banner
(§7). Recurrent past confusion: the user tested against a server started hours earlier.

Sandbox note: starting a server on a port and calling it with `curl` from the shell was refused by the
sandbox. Test the API in-process (`fastapi.testclient.TestClient`, as `tests/test_api.py` does) and the UI
with the Playwright tests, which start uvicorn inside the pytest process; both work.

`data/` holds the user's real experiments (SQLite `beetrack.sqlite` + `experiments/NNNN/videos|results`).
Read it to debug what the user saw; **never delete or rewrite it** without asking, and never commit it.

## 3. Git workflow (required)

- `main` is the published branch. **Every change goes on a new branch and is merged through a pull request**
  (the user asked for this explicitly). Never commit straight to `main`.
- Branch names: `fix/<short-topic>`, `feat/<short-topic>`, `docs/<short-topic>`.
- Before opening a PR: `pytest` passes (or say exactly which tests fail and why), docs/CLAUDE.md updated if
  behaviour changed, version bumped if the web UI or outputs changed (§7).
- Open PRs with `gh pr create` (gh is logged in as `yair-hamo`). PR description: what changed, why, how it
  was tested; end with the attribution line the session gives. Don't merge unless the user asks.
- The repo is public: never commit `data/`, videos (`*.mp4`, `*.mkv`), the user's email, or anything from
  outside this folder. Commits use the GitHub no-reply address configured in this repo's local git config.
- README GIFs live in `docs/assets/`; keep each under ~4 MB (ffmpeg palettegen, ≤ 480 px wide, 10 fps).

## Releases

Windows app, built and published by GitHub Actions (`.github/workflows/windows-app.yml`), free for this public repo:

- **Contents**: `beetrack-setup-X.Y.Z.exe` (Inno Setup, per-user, no admin; Start-menu/desktop shortcuts;
  upgrades in place) and `beetrack-portable-X.Y.Z-windows.zip` (unzip and run). ~100–150 MB compressed,
  ~350 MB installed. Python, all libraries and an **LGPL ffmpeg** are bundled; users install nothing.
- **How it starts**: `packaging/launcher.py` → `beetrack.desktop.main()`: `multiprocessing.freeze_support()`
  first (analyses run in spawned child processes), server on 127.0.0.1:8000 (or the next free port), browser
  opens, data in `Documents\beetrack` (`BEETRACK_DATA`), console window = close to stop; a second launch just
  opens the browser. `BEETRACK_PORT` forces a port, `BEETRACK_NO_BROWSER=1` for checks.
- **Recipe**: `packaging/beetrack.spec` (PyInstaller, one folder) + `packaging/beetrack.iss` (installer).
  The workflow downloads the LGPL ffmpeg from BtbN/FFmpeg-Builds; LGPL ffmpeg has no libx264, so `videos.py`
  tries `libx264` → `h264_mf` (Windows) → `h264_videotoolbox` (macOS).
- **Checks**: `packaging/smoke_test.py` runs the *packaged* app end to end (start, upload, analyse in the
  frozen worker, render a video) on the portable build and again after a silent install.
- **To release**: bump the version in the three places (§7), merge, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
  The tag must equal the pyproject version or the workflow stops. Pull requests that touch packaging run the
  same build and checks without publishing (files kept 7 days as a workflow artifact).
- **Keep all releases** (the user's choice): results record the version that made them.
- Unsigned: Windows SmartScreen shows "Windows protected your PC" → More info → Run anyway. Code signing
  (paid) would remove it. On macOS a first launch of a fresh build can take minutes (Gatekeeper scan).
- Local build on the Mac (for debugging the recipe): `pip install pyinstaller requests && pyinstaller
  packaging/beetrack.spec --noconfirm --distpath build/dist --workpath build/pyi && python
  packaging/smoke_test.py build/dist/beetrack/beetrack 8772`.

## 4. Code map (`src/beetrack/`)

| Module | Role |
|---|---|
| `config.py` | Pydantic models. `AnalysisConfig` = *how* (thresholds; mm and seconds only, never px/frames). `ExperimentSetup` = *what* is in one video: `marking` ("color"/"none"), `dish`, `queen_cell` (ellipse `shape` or `polygon_px`), `ignore_areas`, `bees` (bee_id + one mark `color`), `n_bees` (bees in the dish, marked or not), learned `palette` + `mark_model`, identity overrides `id_min_votes/id_min_purity/id_min_probability`. `setup.effective_config(cfg)` applies the per-experiment palette/thresholds; `setup.check(cfg)` returns errors/warnings shown in the UI. Legacy fields are migrated in validators (`thorax/abdomen` bees, `dot_on_thorax`). |
| `calibration.py` | `Geometry`: px↔mm (origin dish centre, **y up**), arena/ignore/queen-cell masks, `exclusion_mask()`, distance to the cell, zone outlines. `detect_dish()` (Hough). |
| `video.py` | `Recording`: several 1-h segments as one timeline; `read_frame` falls back to earlier frames on variable-frame-rate files. |
| `detection/background.py` | `BackgroundDetector`: dark bees on a light background. Per-frame grey closing (resting bees stay visible), the queen cell uses a temporal median (`learn_background`), ignore areas removed, **bee size measured from the video** (robust to a wrong dish diameter), blobs of k bee-areas split by seeded k-means. `set_threshold()` re-learns size + static masks. |
| `detection/sleap_import.py` | Reads a SLEAP analysis .h5 (deep-learning route; track names = bee IDs). |
| `identity/discover.py` | **Learns the paint colours from the video**: cuticle model (bees' hue band, colourfulness, brightest body pixel) → spots outside it (other hue, much more vivid = neon, or white) → Lab clustering → named groups with example crops. The `exclude` mask keeps the queen cell and ignore areas out. |
| `identity/color_id.py` | Reads marks per detection: learned path (same `collect_spots` as discovery + nearest Lab centre) or the old HSV palette. Produces `color_scores` (evidence per bee). |
| `tracking/tracker.py` | Online Hungarian tracker with a capped speed gate → short, clean *tracklets*. |
| `identity/resolver.py` | Splits tracklets where colour readings switch bee; the old open-ended naming (used only when the bee count is unknown). |
| `identity/closed_group.py` | **Main identity model.** Exactly N identities (W… marked + U… unmarked). Anchors from mark readings, then longest-first assignment by colour + motion likelihood; no identity in two places; extra pieces dropped as false detections. Outputs `bee_id`, `id_confidence` (posterior), `id_source` ("mark"/"motion"). Reports `never_read` registered colours. |
| `identity/anonymous.py` | Joins tracklets only when unambiguous (unmarked mode, unknown N → T001…). |
| `trajectories.py` | Per-bee mm paths on a regular grid, careful gap filling (`_fill_gaps`), smoothing, speed, heading. Learns per bee whether the mark is ahead of (thorax) or behind (abdomen) the body centre (`learn_mark_positions`). |
| `behavior/visits.py`, `metrics.py` | Queen-cell visits per zone (contact 3 mm, vicinity 10 mm around the outline, head point; gaps < 1.5 s merged, visits < 1 s dropped), per-bee metrics, time bins. Both carry `id_probability`. |
| `pipeline.py` | `AnalysisPipeline(cfg, setup).run(videos, out)`: calibrate the detector (bee size, sensitivity tuned to `n_bees`) → detect/read/track → identity → trajectories → visits → files + `summary.json` (full config, setup, version, warnings, `closed_group`, `mark_readings`, `mark_positions`, `detection_threshold`). |
| `videos.py` | Result videos: annotated recording, paths map, occupancy heatmap; step/trail/fps/bees options; H.264 via ffmpeg. |
| `export.py` | Path annotations as CSV and MOT format. |
| `synthetic.py` | Synthetic arena with ground truth; `colours=NEON`, `mark_at="abdomen"` for testing. |
| `evaluation.py` | Accuracy vs ground truth or hand annotations. |
| `recording.py` | ffmpeg recorder (macOS AVFoundation / Linux v4l2). |
| `desktop.py` | Desktop launcher used by the Windows app (see Releases). |
| `server/` | FastAPI (`api.py`), SQLite (`db.py`, migrates columns on startup), job worker (`worker.py`: one job at a time in a spawned process; analyses and video renders), overlay drawing, static single-page UI (`static/app.js`, ~1400 lines, no build step, Plotly vendored in `static/vendor`). |

Pipeline in one line: `video ─► detect ─► read marks ─► link (tracklets) ─► identity (closed group) ─►
trajectories (mm) ─► visits ─► metrics ─► files`. Details: `docs/PIPELINE.md`, `docs/ARCHITECTURE.md`.

Using the results in Python or R:

```python
import pandas as pd
visits = pd.read_csv("results/visits.csv")                # one row per visit (id_probability per visit)
traj   = pd.read_parquet("results/trajectories.parquet")  # one row per bee per frame (id_confidence per row)
visits.query("zone == 'contact'").groupby("bee_id").duration_s.agg(["count", "sum", "mean"])
```

## 5. Deliberate design decisions (keep them unless the user asks otherwise)

1. **Closed group.** When the number of bees is known, there are exactly N identities, never more. Every
   position has a probability. This was the user's explicit request ("don't give more IDs than bees").
2. **Identity is assigned once, after tracking, using the whole recording**; nothing is labelled early and
   overwritten. Track pieces are cut wherever linking is doubtful.
3. **Marks are learned from the video, not configured.** The user rejected a fixed palette. The built-in
   palette still exists for old setups, but Setup warns when it's in use.
4. **Unknown is better than invented**: gaps are filled only when physically plausible; impossible jumps
   stay NaN; extra blobs are dropped, not named.
5. **Results show the setup they were made with** (`summary.json` → `server.worker.load_run`); if the setup
   was edited later, Results shows a "setup was edited" banner. Renders also use the run's setup.
6. **Reproducible**: k-means is seeded; two runs of the same video give identical results (tested).
7. **Units**: configuration in mm and s; outputs in mm, origin dish centre, y up; angles CCW from +x.
8. The **queen cell is a fixed region**, not a moving queen. Visits are measured with the bee's head point.
9. Two kinds of experiment: **colour marks** (named bees W…, plus U… for unmarked members of the group)
   and **unmarked** (U… with a bee count, otherwise open-ended T… tracks).

## 6. Accuracy so far (keep these numbers honest; re-measure after changes)

Synthetic, 60 s, 10 bees, crowding at the cell (`SyntheticArena(seed=1)`, 1280×720, 15 fps, ~4.4 px/mm):
identity accuracy ≈ 0.84–0.87, wrong identity ≈ 9–12 %, median position error ≈ 0.4 mm. Positions named from a
mark ≈ 97 % right; named by motion only ≈ 35–40 % right (that's what a low `id_confidence` flags). With
`id_min_probability = 0.5`: wrong ≈ 2 %, coverage ≈ 79 %. Contact time is under-counted ≈ 15–25 % when bees pile
up on the cell; time in the 10 mm vicinity is within ≈ 5 %. Speed ≈ 130 frames/s on an Apple-silicon Mac
(1 h at 15 fps ≈ 7 min).

Neon paint, marks on the abdomen (synthetic): all 6 paints found, including neon orange (the bees' own hue,
found only by vividness); accuracy > 0.85; mark position learned as "abdomen".

Real `output.mp4`, learned marks, 10 bees: 9.7 bees per frame, every identity followed 79–100 % of the clip,
mean probability ≈ 0.45 (most positions are named by motion; the marks are tiny at 452 px), ≈ 17 % of
detections dropped as beyond 10 bees (mostly split blobs in the cluster at the cell). **Never validated by a
person**: there is no hand-annotated ground truth for real footage yet (see `docs/VALIDATION.md`).

## 7. Conventions and gotchas

- **Version bump in three places together**: `src/beetrack/__init__.py`, `pyproject.toml`, and `UI_VERSION`
  in `src/beetrack/server/static/app.js` (a unit test enforces the match; the UI shows a red banner on a
  mismatch). Current: **0.3.0**.
- `app.js` is plain JS; after editing, syntax-check it (node is not installed on the dev Mac):
  `osascript -l JavaScript -e 'ObjC.import("Foundation"); var s=$.NSString.stringWithContentsOfFileEncodingError("src/beetrack/server/static/app.js",$.NSUTF8StringEncoding,null).js; new Function(s); "ok"'`
  then run `pytest tests/test_ui.py`.
- In `tabResults` (app.js), don't use `S` (summary) before `const S = r.summary` (a TDZ bug happened once).
- `JobWorker` must not name an attribute `_stop` (it shadows `threading.Thread._stop`); it uses `_stop_event`.
- SQLite schema changes: add the column in `server/db.py` **and** in `Database._migrate()` (the user's DB exists).
- Setup JSON is stored per experiment in the DB; new setup fields need defaults so old experiments still load.
- Every bug fix gets a test in `tests/test_regressions.py` that fails without the fix.
- `cv2.kmeans` must be seeded (`cv2.setRNGSeed`) wherever it's used.
- Pixel thresholds use the **processing scale** (`pipeline.proc_px_per_mm`, from the measured bee size), not
  the dish scale, because the dish diameter is often unknown or wrong.
- Mark discovery and identification share `collect_spots`; keep them consistent. Discovery excludes the queen
  cell + ignore areas; identification excludes only ignore areas (bees *on* the cell must stay readable).
- If the closing disc ever detects the queen cell itself as a bee, `detection.ignore_queen_cell: true` exists,
  but `queen_cell.learn_background` (default) normally handles it.

## 8. Tests (`tests/`, 173)

`conftest.py` session fixtures: `synthetic` (easy, 45 s), `result` (its analysis), `crowded` / `crowded_result`
(bees pile up on the cell: for probability tests). Files: `test_units.py` (small units), `test_pipeline.py`
(end-to-end accuracy thresholds), `test_identity.py` (closed group on hand-built tables), `test_marks.py`
(discovery, neon, mark position), `test_regressions.py` (one per bug), `test_api.py` (REST), `test_ui.py`
(Playwright; runs in file order on one shared page, each step building on the previous one). A full run
occasionally hits a render timeout when the machine is busy; re-run before assuming a bug.

## 9. History and state (2026-11-12)

- v0.1–0.2: classical pipeline, web app, colour dots, unmarked mode, queen-cell editor, ignore areas, result
  videos, annotation exports, browser tests.
- v0.3.0 (last session): review and fixes across the code (setup snapshots per run, render vs analysis
  statuses, worker error handling, thread-shadowing bug, seeded k-means, sensitivity tuned by per-frame error
  with size re-measurement, quadratic stitching replaced, timeline bisection, single-frame and zero-gap
  crashes); the probabilistic closed-group rewrite (`id_confidence` with meaning, `id_source`, `never_read`);
  learned mark position (thorax/abdomen); neon support in discovery; ID-certainty columns and filter; and the
  bug the user reported last, **"Find the marks" learned the food and the queen cell as marks** (fixed via
  `exclude` masks; tests added).
- First push to GitHub (this README, CLAUDE.md, GIFs, hardware plan in `docs/HARDWARE.md`).

**Docs not yet updated for v0.3** (small, do it in a `docs/` PR): `docs/PIPELINE.md` §4c (probabilities,
`id_source`, `silence_s`, `never_read`) and the mark-position section; `docs/DATA_FORMATS.md` (new columns
`id_source` in detections, `id_probability` in visits/metrics; summary keys `mark_readings`,
`mark_positions`, `closed_group.never_read/mark_share`); `config/default.yaml` (regenerate).

## 10. Open questions and next steps (rough priority)

1. **Validate on real footage.** Hand-annotate ~50 random frames of a real video (frame, bee_id, x_mm, y_mm)
   and run `beetrack evaluate`. Every accuracy number for real video is unknown until then.
2. **Fluorescent paint.** Advice given to the user: neon paint under normal white light is the cheap first
   step (discovery already handles neon, including orange/yellow by vividness); a UV torch is a problem because
   bees see UV (it changes behaviour), so only short synchronised flashes after the doctor agrees; the robust
   48 h option is IR light + printed black/white tags (as in NAPS, below). When neon footage arrives, run
   discovery and check the groups.
3. **SLEAP route** (`docs/SLEAP.md`): not trained yet; beetrack imports a SLEAP analysis .h5. Neon marks would
   help a SLEAP identity model too.
4. Contact time is under-counted in crowds, and ~17 % of real detections are dropped as extra blobs: better
   splitting of touching bees (or SLEAP) would help.
5. Vertical dish: bees on the near face show their belly; marking both sides (planned) should raise the read
   rate (≈ 0.37 on real footage now).
6. Rig problems, not software: condensation, a moving camera. `docs/HARDWARE.md` covers the fixed 3D-printed rig.
7. 48 h recordings: memory grows with length (several GB); a streaming detection writer is the planned fix.
   Until then analyse 6–12 h blocks.

## 11. Related work

- Wolf et al. 2023, *NAPS: Integrating pose estimation and tag-based tracking*, Methods Ecol. Evol.
  ([PMC11052584](https://pmc.ncbi.nlm.nih.gov/articles/PMC11052584/), code: [kocherlab/naps](https://github.com/kocherlab/naps)).
  Bumblebees with ArUco tags + SLEAP; identity as a separate layer voting over time, like here.
- Walter & Couzin 2021, *TRex*, eLife ([PMC8096434](https://pmc.ncbi.nlm.nih.gov/articles/PMC8096434/)).
- Pereira et al. 2022, *SLEAP*, Nature Methods ([sleap.ai](https://sleap.ai)).
