# The deep-learning route (SLEAP)

Use it if the classical pipeline struggles: crowding on the cell, uneven lighting, or a vertical dish
with many belly views. SLEAP learns body parts and identity from frames you label, and beetrack then
imports its predictions and computes trajectories, visits and metrics as usual.

## Setup on a Mac

SLEAP runs on Apple Silicon. Follow the current install guide at <https://sleap.ai> (conda/mamba
environment). Training is much faster on an NVIDIA GPU, so the lab's RTX 2060 PC is a good
training box even if analysis runs on the Mac.

## Workflow

1. **Skeleton**: nodes `head`, `thorax`, `abdomen` (optionally antennae tips), edges head→thorax→abdomen.
2. **Label** about 200–500 frames from several videos, with emphasis on crowded moments at the cell.
   For identity, assign each instance to a **track named exactly like the bee IDs** (`W01` … `W10`).
3. **Train** a top-down **ID model** (centroid + multi-class top-down). Its classes are the bee IDs,
   learned from the paint marks.
4. **Predict and export**:
   ```bash
   sleap-track video.mp4 -m models/centroid -m models/topdown_id -o preds.slp
   sleap-convert preds.slp --format analysis -o preds.analysis.h5
   ```
5. **Analyse** with beetrack (the setup still provides the dish scale and queen cell):
   ```bash
   beetrack analyze video.mp4 -s setup.json --sleap preds.analysis.h5 -o results/
   ```

beetrack reads `tracks`, `track_names` and `node_names` from the analysis file. Nodes named `head`,
`thorax` and `abdomen` are used for position, heading and the head point (see
`detection/sleap_import.py`).

## Which route when?

| | Classical (default) | SLEAP |
|---|---|---|
| Labelling | none | 200–500 frames (about a day) |
| GPU | no | yes, for training; inference faster with one |
| Speed | ≈130 fps on a Mac | slower (NAPS reported ≈3.6 fps on an A100 with 50 bees at 3664²) |
| Crowding | blobs merge | handles touching animals |
| Head/antenna precision | estimated | measured |
