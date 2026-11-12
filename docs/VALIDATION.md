# Validating on real footage

Synthetic tests show the code works. They don't show it works on *your* bees, paint and lighting.
Before using results in a paper, measure accuracy on real frames and report it.

## 1. Pilot checks (1 hour of video)

* **Explorer tab**: scrub through and check that labels sit on the right bees, especially at the cell.
* **Colour probe**: click 3–5 spots of each paint colour. If a measured hue is more than about 5 away
  from the palette value, edit the palette in the configuration.
* `summary.json → detections_identified_fraction` should be > 0.8. Per-bee `tracked_fraction` in
  `bee_metrics.csv` should be > 0.8.
* Warnings in the Results tab.

## 2. Identity accuracy (for the paper)

1. Pick about 50 random frames (spread over the recording, and include frames with bees on the cell).
2. For each frame, record every visible bee's ID and centre: `frame, bee_id, x_mm, y_mm`. The
   Explorer overlay helps; correct anything that's wrong. A spreadsheet is enough.
3. Run:
   ```bash
   beetrack evaluate results/ annotations.csv --tol-mm 4
   ```
4. Report `id_accuracy`, `wrong_id_rate`, `coverage` and the number of annotated pairs.

## 3. Visit accuracy

Pick 10 visits from `visits.csv` and 10 random 1-minute windows. Watch them in the Explorer, then
note any missed or false visits and the start/end errors. Report agreement, for example:
"18/20 visits confirmed; median boundary error 0.7 s".

## 4. Freeze the parameters

After the pilot, save the configuration as `config/study_<name>.yaml` and use it, unchanged, for
every experiment in the study. Every `summary.json` records the exact config used.
