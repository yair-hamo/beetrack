# The analysis pipeline, step by step

Parameter names refer to [`config/default.yaml`](../config/default.yaml). Lengths are in mm and times in
seconds.

## 0. Geometry and scale

`ExperimentSetup.dish` gives the dish centre and radius in pixels plus its real diameter, so
`px_per_mm = 2·radius_px / diameter_mm`. Outputs use mm with the origin at the **dish centre, y up**.
The queen cell is a polygon in pixels. Each zone is that polygon grown by `margin_mm`.

## 1. Detection (`detection/background.py`)

*Ignore areas* (`setup.ignore_areas`) are removed from the arena. Inside the queen-cell outline the
background is the temporal median, so the cell's wax isn't foreground (`queen_cell.learn_background`).
With a known bee count, `auto_threshold` tries sensitivities on sample frames and keeps the one whose bee
count matches best, preferring the stricter one on ties. The tried values are shown in Results →
*Detection balance*.

The camera sees dark bees on a light, evenly lit dish.

1. **Background.** With `method: morphological` (default), a grey-level *closing* with a disc about
   1.8 × the bee width erases every dark object narrower than the disc (bees) and keeps wider ones
   (the queen cell, dish features). It's computed per frame at half resolution, so a bee that rests
   for an hour is still detected. `median` uses a temporal median instead (faster, but resting bees vanish).
2. **Foreground**: pixels at least `diff_threshold` grey levels darker than the background, inside
   the dish minus `arena_margin_mm`. Then open/close, and fill holes (paint spots are bright).
3. **Blobs**: connected components. Smaller than `min_area_fraction` × one bee = noise. About *k*
   bee-areas = *k* touching bees, split with k-means on pixel coordinates (up to `max_bees_per_blob`).
4. **Shape**: image moments give the centroid, the body-axis angle (180° ambiguous) and the
   major/minor lengths.

## 2. Reading the paint dot (`identity/palette.py`, `identity/color_id.py`)

Inside each bee mask (slightly grown), pixels are classified in HSV:

* **chromatic paint**: `S ≥ min_saturation` and `V ≥ min_value`, hue within `max_hue_distance` of a
  palette hue (circular distance on OpenCV's 0–179 wheel);
* **white**: `S ≤ white_max_saturation` and `V ≥ white_min_value`, only *strictly inside* the body
  (the light background next to a bee also looks white).

Each bee carries **one dot of a unique colour** on the thorax. Connected spots ≥ `min_spot_area_mm2`
are collected and their area is summed per colour (a dot split by glare counts once):

| Observation | Evidence |
|---|---|
| one colour | 1.0 for the bee with that colour |
| two colours, the larger ≥ `dominance` × the smaller | 1.0 for the larger |
| two colours of similar size (touching bees, a false spot) | shared in proportion to area |
| nothing readable (hidden, or the bee upside down) | none |

**Tuning.** The default palette has 10 colours (white plus 9 hues about 12 steps apart), and
`max_hue_distance` is 6. **Orange paint has the same hue as the bees' amber abdomen bands**; only
brightness separates them (paint V ≈ 240 vs cuticle V ≈ 120, hence `min_value: 160`). Measure your
paints with the colour probe, and drop orange for another colour if the cuticle is classified as orange.

## 3. Linking (`tracking/tracker.py`)

Constant-velocity prediction plus Hungarian assignment. The gate is
`max_speed_mm_s · min(Δt, gate_max_dt_s) + gate_slack_mm`. The cap stops a track that lost its
bee from jumping to a blob across the dish a second later. A track that is unmatched for longer than `max_gap_s` is
closed. The tracker prefers **short, pure tracklets**: identity comes later.

## 4. Identity (`identity/resolver.py`)

1. **Switch splitting.** Inside a tracklet, full-code matches are smoothed with a rolling majority
   (`switch_window`). If the label changes and each side has ≥ `switch_min_votes` matches, the
   tracklet is cut.
2. **Voting.** Evidence per (tracklet, bee) is summed.
3. **Conflict-free assignment.** Candidates are sorted by evidence × purity. A bee can't hold two
   tracklets that overlap in time. A candidate needs ≥ `min_votes` and purity ≥ `min_purity`.
4. **Gap linking.** An unnamed tracklet that starts ≤ `link_max_gap_s` after (or ends before) a named
   one, within `link_max_dist_mm`, takes that bee if it is the *only* candidate. Confidence is
   halved to mark it as inferred.

## 4b. Unmarked bees (`identity/anonymous.py`, `setup.marking: none`)

No colour step. Tracklets are joined into anonymous tracks **only when unambiguous**: tracklet *b*
starts ≤ `unmarked.stitch_max_gap_s` after *a* ends, ≤ `stitch_max_dist_mm` away, and no other
candidate is nearly as close (`stitch_ambiguity_ratio`). Two bees separating after a contact are
ambiguous by definition, so they get new track IDs instead of a guess. Tracks shorter than
`min_track_s` are dropped. Tracks are named `T001…` by start time. `id_confidence` is empty.

## 4c. Closed group (`identity/closed_group.py`, when the number of bees is known)

Exactly N identities: registry bees (W…) + `N − marked` unmarked (U…). Units are track pieces that are
certainly one bee. The log-likelihood of piece *c* being identity *i* combines:

* **colour:** a marked bee shows its own mark in a fraction *r* of detections (estimated from the data),
  rarely another colour (ε), otherwise nothing; an unmarked bee gives only rare spurious readings. So
  silence over a long piece is evidence *against* marked identities;
* **motion:** the join with the identity's previous and next piece is Gaussian in distance
  (σ = 3 mm + 10 mm/s · gap), and impossible beyond 40 mm/s · gap + 6 mm.

Identities never overlap in time. Strong colour pieces are fixed first (*anchors*). The rest are placed
longest first, each with the most probable free identity. `id_confidence` = that posterior. Pieces with no
free identity (more than N blobs at once) are false detections and are dropped. Nothing is decided early
and overwritten: identities are assigned once, after tracking, using the whole recording.

## 4d. Learned marks (`identity/discover.py`)

Spots are pixels outside the *cuticle model* learned from the video (bee bodies share one hue band;
white paint is brighter than any body pixel), different from that bee's own body (ΔE ≥ 15), compact, and
not belonging to a neighbouring bee. They are clustered in Lab (lightness weighted 0.35, since blur changes
lightness) and merged under ΔE 13. Groups mostly at the dish rim, or very bright and colourless, are flagged
as glare. Confirmed groups become `setup.palette` (Lab centres + tolerance) and `setup.mark_model`;
identification then uses the same spot finder.

## 5. Trajectories (`trajectories.py`)

Per bee, on the grid of analysed frames:

* positions in mm; `observed` = detected in that frame;
* **gap filling**: linear for gaps ≤ `max_interp_gap_s`, and only if crossing the gap needs ≤
  `max_interp_speed_mm_s` (otherwise it was a tracking jump, not a walk, and is left empty). Up to `max_still_gap_s` only if the bee
  reappears within `still_gap_max_move_mm` of where it vanished (a resting bee hidden in a cluster).
  Everything else stays NaN;
* rolling-median smoothing (`smooth_window_s`), velocity and speed;
* **heading**: the body-centre → thorax-dot vector when the dot is seen (works when still; turn off
  with `color.dot_on_thorax: false` if dots are placed elsewhere), otherwise the velocity direction when moving, otherwise continuity;
* **head point** = centroid + `head_offset_fraction` × the bee's median body length along the heading.

## 6. Visits (`behavior/visits.py`)

For each bee and zone: `inside[t]` = the head point (or the centroid, per `visits.point`) lies within
the zone. Unknown frames are not "outside". Bouts closer than `merge_gap_s` are merged. Visits
shorter than `min_visit_s` are dropped. Each visit records `observed_fraction` (data quality) and
`min_distance_mm`.

Default zones: **contact** = 3 mm (about antenna reach), **vicinity** = 10 mm. These are biological
definitions: agree on them with the PI before the study and keep them fixed.

## 7. Metrics (`behavior/metrics.py`)

Per bee: coverage (`tracked_fraction`, `observed_fraction`), distance walked, mean speed, moving
fraction. Per zone: visits, total, mean, median and max duration, first-visit latency, visits per
tracked hour, and fraction of tracked time in the zone. Time-binned (`bin_s`): seconds in the zone
and visits started, per bee per bin.
