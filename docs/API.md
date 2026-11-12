# REST API

Base URL: `http://<server>:8000/api`. Interactive docs (Swagger) are at `http://<server>:8000/docs`.

## Meta
| Method | Path | |
|---|---|---|
| GET | `/health` | version, data directory |
| GET | `/defaults` | default config (JSON + YAML), palette, default bee registry |

## Experiments
| Method | Path | Body / params |
|---|---|---|
| GET | `/experiments` | list with status (`no video`, `needs setup`, `ready`, `analysing`, `done`, `failed`) |
| POST | `/experiments` | `{name, station?, recorded_on?, notes?}` |
| GET | `/experiments/{id}` | full record: videos, setup, check (errors/warnings), config_yaml, jobs |
| PATCH | `/experiments/{id}` | any of the metadata fields |
| DELETE | `/experiments/{id}` | deletes videos and results too |

## Videos
| Method | Path | |
|---|---|---|
| POST | `/experiments/{id}/videos` | multipart `file`. Segments must share resolution and fps. The first upload auto-detects the dish. |
| DELETE | `/experiments/{id}/videos/{video_id}` | |
| GET | `/experiments/{id}/frame?t=&overlay=&trail_s=&max_width=` | JPEG at time *t* (s), optionally with geometry and tracks |
| GET | `/experiments/{id}/probe?x=&y=&t=` | median HSV around a pixel + palette classification (for tuning) |

## Setup and configuration
| Method | Path | |
|---|---|---|
| PUT | `/experiments/{id}/setup` | full `ExperimentSetup` JSON → `{setup, check}` |
| POST | `/experiments/{id}/dish` | `{diameter_mm, points?}`: 3 rim points, or omit for auto-detection |
| PUT | `/experiments/{id}/config` | `{yaml}`: overrides (empty = defaults), validated |

## Jobs
| Method | Path | |
|---|---|---|
| POST | `/experiments/{id}/analyze` | queue an analysis (409 if setup incomplete or already queued) |
| GET | `/jobs` · `/jobs/{id}` | status, stage, progress 0–1, message, error |
| POST | `/jobs/{id}/cancel` | |

## Results (latest successful run, or `?job_id=`)
| Method | Path | |
|---|---|---|
| GET | `/experiments/{id}/results` | summary, metrics, visits, binned, zones |
| GET | `/experiments/{id}/results/trajectories?bee=W01&bee=W02&step_s=1&t0=&t1=` | `{bee: {t, x, y}}` (mm) |
| GET | `/experiments/{id}/results/heatmap?bee=&bins=60` | occupancy grid (seconds per cell) |
| GET | `/experiments/{id}/geometry` | dish radius, queen cell and zone outlines in mm |
| POST | `/experiments/{id}/render` | `{video: "annotated" / "paths" / "heatmap", step_s, trail_s, fps, bees}` → render job |
| GET | `/experiments/{id}/download/{name}` | `visits.csv`, `bee_metrics.csv`, `binned_visits.csv`, `trajectories.csv`, `trajectories.parquet`, `detections.parquet`, `summary.json`, `annotations.csv`, `annotations_mot.txt`, `annotated.mp4`, `paths.mp4`, `heatmap.mp4` |

## Scripted example

```python
import requests, time
B = "http://localhost:8000/api"
e = requests.post(f"{B}/experiments", json={"name": "Colony A day 1"}).json()
requests.post(f"{B}/experiments/{e['id']}/videos", files={"file": open("seg1.mp4", "rb")})
requests.put(f"{B}/experiments/{e['id']}/setup", json=json.load(open("setup.json")))
job = requests.post(f"{B}/experiments/{e['id']}/analyze").json()
while requests.get(f"{B}/jobs/{job['id']}").json()["status"] in ("queued", "running"):
    time.sleep(5)
visits = requests.get(f"{B}/experiments/{e['id']}/results").json()["visits"]
```

The server has **no authentication**. Run it on the lab network only, not on the open internet.
