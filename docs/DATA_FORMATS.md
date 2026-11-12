# Output files

Every analysis run writes one folder (CLI: `-o DIR`; server: `data/experiments/NNNN/results/job_NNNN/`).

| File | Rows | Use |
|---|---|---|
| `visits.csv` | one per visit | the main result |
| `bee_metrics.csv` | one per bee | the per-bee summary for statistics |
| `binned_visits.csv` | bee × zone × time bin | time courses |
| `trajectories.parquet` | bee × analysed frame | full paths (the UI also exports CSV) |
| `detections.parquet` | one per raw detection | debugging and re-analysis |
| `summary.json` | – | provenance: config, setup, inputs, version, timings, warnings |
| `preview.jpg` | – | first frame |
| `annotated.mp4`, `paths.mp4`, `heatmap.mp4` | – | result videos (Results → *Videos*; H.264 if ffmpeg is installed). Each has a `.json` next to it with the options used: `step_s` (recording seconds per output frame; null = real time), `trail_s` (0 = none, -1 = entire path / cumulative heatmap), `fps`, `bees` |
| `annotations.csv` *(download)* | bee × observed frame | centre, head, heading and bounding box in **pixels**, for other tools or re-labelling |
| `annotations_mot.txt` *(download)* | bee × observed frame | the same in MOT Challenge format: `frame,id,left,top,width,height,conf,-1,-1,-1` (1-based frames; ids = `track_no` in annotations.csv) |

Coordinates: **mm, origin at the dish centre, x right, y up**. Angles: degrees, counter-clockwise from +x.
Time: `time_s` = seconds from the start of the first video segment.

## visits.csv

| Column | Meaning |
|---|---|
| `bee_id` | e.g. `W03` (colour mode), or `T017` (unmarked mode: an anonymous track) |
| `zone` | `contact` / `vicinity` (or your configured zones) |
| `visit_no` | 1, 2, … per bee and zone |
| `start_frame`, `end_frame` | source-video frame indices (global across segments) |
| `start_s`, `end_s`, `duration_s` | seconds |
| `observed_fraction` | share of the visit with a measured (not bridged) position |
| `min_distance_mm` | closest approach of the head to the cell outline (0 = touching or inside) |

## bee_metrics.csv

`bee_id`, `tracked_fraction`, `observed_fraction`, `distance_m`, `mean_speed_mm_s`,
`moving_fraction`, then for each zone *z*: `z_visits`, `z_total_s`, `z_mean_s`, `z_median_s`,
`z_max_s`, `z_first_visit_s`, `z_visits_per_h`, `z_time_fraction`.

## binned_visits.csv

`zone`, `bee_id`, `bin_start_s`, `bin_end_s`, `seconds` (time in the zone within the bin; visits are
split across bins), `visits_started`.

## trajectories.parquet

| Column | Meaning |
|---|---|
| `bee_id`, `frame`, `time_s` | key |
| `x_mm`, `y_mm` | body centre (smoothed); NaN = unknown |
| `head_x_mm`, `head_y_mm` | estimated head point |
| `heading_deg` | body direction |
| `speed_mm_s` | speed |
| `observed` | detected in this frame (True) vs filled or unknown |
| `interpolated` | position filled across a gap |
| `id_confidence` | share of colour evidence for this bee in the source tracklet (halved if gap-linked) |

## detections.parquet

`frame`, `time_s`, `x_px`, `y_px`, `axis_angle` (rad, image frame), `major_px`, `minor_px`, `area_px`,
`colors`, `s1_color/x/y`, `s2_color/x/y` (paint spots), `best_match`, `best_score`, `tracklet`,
`bee_id`, `id_confidence`, `head_x_px`, `head_y_px`.

## Inputs

* **setup.json**: `ExperimentSetup`: `marking` (`color`/`none`), `dish`, `queen_cell`, `bees[]`, `n_bees`. Created by the UI or `beetrack init-setup`.
  `queen_cell` is either `{"shape": {"type": "ellipse", "cx", "cy", "length_px", "width_px", "angle_deg"}}`
  (the outline is generated from it) or `{"polygon_px": [[x, y], …]}`. Each experiment stores its own,
  so cells of any size and position are supported.
* **config.yaml**: `AnalysisConfig`. Start from `config/default.yaml` and keep one file per study.
* **Hand annotations for validation**: a CSV with `frame, bee_id, x_mm, y_mm` (see VALIDATION.md).
