# Bee Imaging Rig: Queen + Worker Behaviour Tracking

A low-cost, repeatable setup for filming **10 colour-marked worker bees and a queen cell (with a queen larva)** in a large petri dish for up to **48 hours**, recording several stations at once on one desktop PC, and turning the videos into **per-bee trajectories and queen-cell visits** (which worker visits, how often, for how long).

**Software:** see the [main README](../README.md): analysis pipeline, web app, docs and tests.

The original concept drawing (2 stations: LED panel → diffuser → petri dish with queen cage → camera at 20–30 cm → recorder → PC/NAS, with an opaque divider between stations).

---

## Contents
1. [Goals](#1-goals)
2. [Design review: what to change in the concept drawing](#2-design-review-what-to-change-in-the-concept-drawing)
3. [Marking the bees](#3-marking-the-bees)
4. [Lighting](#4-lighting)
5. [Camera ($20–30)](#5-camera-2030)
6. [Recording PC, USB and storage](#6-recording-pc-usb-and-storage)
7. [Fixed rig (3D printed, Bambu Lab P2S)](#7-fixed-rig-3d-printed-bambu-lab-p2s)
8. [Video analysis pipeline](#8-video-analysis-pipeline)
9. [Budget](#9-budget)
10. [Open questions for the PI](#10-open-questions-for-the-pi)
11. [Pilot plan](#11-pilot-plan)
12. [Sources](#12-sources)

---

## 1. Goals

- **Identity:** every bee is individually recognisable for the whole recording (unique mark on the back).
- **Repeatability:** same camera distance, angle, framing, lighting and camera settings in every experiment, so data from different runs can be compared and pooled.
- **Scale:** several stations recorded at the same time on one old desktop through USB.
- **Output:** for every bee and every frame, position (mm), heading and a confidence value, giving a dataset of worker–queen behaviour.

---

## 2. Design review: what to change in the concept drawing

| # | Issue in the drawing | Why it matters | Fix |
|---|---|---|---|
| A | **The LED panel is behind the dish (backlight).** | Bees appear as dark silhouettes, so **the colour marks on their backs are invisible.** | Add **soft front lighting** beside the camera (Section 4). Dim the back panel to a plain even background, or replace it with a matte white or light-grey card. |
| B | **The dish stands vertically.** | Bees walk on both faces of the dish. On the face nearest the camera they show their **belly**, so no mark is visible. A flat dish has the same problem when bees walk on the lid. | PI decision: keep it vertical (comb-like) and accept short ID gaps that the tracker fills by continuity, **or** lay the dish flat with the camera above (standard, fewer belly views), **or** use a shallow arena. |
| C | The camera sits on its own stand on the table. | The distance is not really fixed: any knock changes the scale and framing. | Mount the camera and the dish on **one rigid rail** (Section 7). |
| D | No light/dark cycle is specified. | Colour marks need visible light. With IR night recording the image is black and white. | If dark periods are needed, use black-and-white printed tags instead of paint (Section 3). Note: tags need a higher-resolution camera than the $20–30 class. |
| E | Not covered in the drawing. | Over 48 h with bees, food and warmth, the **lid fogs up**. | Ventilation holes (mesh-covered), an anti-fog coated lid, and stable temperature and humidity. |
| F | Camera auto settings. | Auto exposure and auto white balance drift over 48 h and change colours, which breaks colour ID. | Lock focus, exposure, gain and white balance (Section 6). |
| G | Frame timing. | A USB camera set to "15 fps" may really run at 14.98, which drifts by minutes over 48 h. | Save a **wall-clock timestamp per frame**. |

Kept from the drawing (good ideas): an **opaque matte divider** between stations, a **calibration scale** in the image, the **camera optical axis centred on the dish**, and **manual focus with fixed exposure**.

---

## 3. Marking the bees

### Option 1 (default): one paint dot per bee
- **One dot on the thorax, a unique colour for each bee**: 10 workers need 10 colours. The software's default palette is white, yellow, lime, green, cyan, blue, purple, pink, red and orange.
- Choose paints that are as different as possible, and check each with the colour probe in the software. **Orange can be confused with the bees' own amber bands**, so replace it if the probe shows confusion.
- With 10 single colours, red/orange/pink and blue/purple are the risky pairs on compressed video. Good front light and locked white balance matter most.
- Use opaque paint markers (Posca / Uni Paint). Dot size is about **2–3 mm**.
- **Queen:** standard numbered queen-marking disc (opalith) in its own colour.
- Paint can be groomed or worn off over 48 h, so check the marks at the end and photograph each bee before and after.

### Option 2: printed fiducial tags (AprilTag / BEEtag)
- About 2.5–3 mm black-and-white tags glued to the thorax. They give near-certain identity and **work under IR** (night or dark conditions).
- They need about **10+ px/mm**, which in practice means a 4K camera (about $50–80), above the current budget. Consider this only if dark-period recording or near-perfect ID is required.

---

## 4. Lighting

- **Front light, soft and indirect:** two LED strips or small panels with diffusers, placed beside the camera at about **30–45°** to the optical axis, so their reflections in the lid miss the lens.
- **Surround the camera with matte black** (lens hood, black card, or the black inside of the printed shroud), so the camera and the room don't reflect in the lid.
- **Background:** the original LED panel turned low, or a matte white or light-grey card. An even background makes tracking much easier.
- **Constant, flicker-free LEDs:** cheap PWM-dimmed LEDs can flicker and show banding on video. Run them at full power, or use DC/constant-current drivers.
- **The same light level in every run:** mark the dimmer position, or use fixed resistors.
- If the PI wants a "dark" period without IR, note that bees see red light poorly (above about 650 nm). Colours will still look different under red-only light, so test it.

---

## 5. Camera ($20–30)

### Is a $20–30 camera good enough?
**Yes, with paint marks.** A 1080p camera framing the dish gives about **5.5–6 px/mm**. A bee thorax (about 4 mm) is then about 22–24 px across and a 2–3 mm paint dot about 12–18 px, which is enough for detection, tracking and colour ID **if the lighting is good and the settings are locked**. Bees walk slowly, so 10–15 fps is plenty.

1080p also makes recording much easier: small files, easy live encoding on an old CPU, and less load on USB.

Limits of this choice:
- Fiducial tags are not realistic at this resolution (paint only).
- Cheap sensors have noisier, less accurate colour, so good front light matters more.
- Quality varies between units, so **buy one, test it, then buy the rest of the same listing**.

### Required spec

| Spec | Requirement | Why |
|---|---|---|
| Type | **USB board camera module** ("USB camera module", "industrial", "UVC") | Cheap, small, mounts on a printed holder |
| Interface | USB 2.0, **UVC / driverless** | Plug-and-play on Linux and Windows |
| Resolution | **1920×1080** | Enough for paint IDs |
| Frame rate | 1080p at **≥15 fps in MJPEG** | MJPEG keeps USB bandwidth low |
| Sensor | Ideally **Sony IMX291 / IMX307 / IMX323**. Acceptable: GC2053, SC2336, OV2710 | Sony sensors give better colour and low noise |
| Lens | **M12 (S-mount), manual focus, "no distortion" / low distortion**, focal length 4–6 mm. **Not autofocus, not fisheye / 170°** | Autofocus hunts and changes the scale. Fisheye bends the image. M12 lenses are swappable and cost $3–5. |
| Controls | Must expose **manual exposure, gain and white balance** through UVC | Required for stable colours. Some very cheap modules lack manual white balance: check the listing or reviews, and test it. |
| IR filter | **With IR-cut filter** (normal colour camera) | Correct colours |
| Mounting | Module with screw holes (usually 32×32 mm or 38×38 mm board) | Easy to design the printed holder around |
| Price | about **$20–30**, plus an optional spare M12 lens for $3–5 | — |

**AliExpress search terms:** `USB camera module 1080P IMX291 M12 lens UVC`, `IMX307 USB camera module manual focus`, `1080P USB board camera no distortion lens`. In the listing, confirm the sensor, "manual focus", the MJPEG frame rates, and the lens field of view.

### Choosing the lens and distance

For a typical 1/2.8"–1/2.9" 1080p sensor (image height about 3.1 mm), with a target view of about 180–190 mm (150 mm dish plus margin):

| Lens | Distance (lens → dish) | Vertical field of view | Resolution |
|---|---|---|---|
| 3.6 mm | ~22 cm | ~190 mm | ~5.7 px/mm |
| **4 mm** | **~25 cm** | **~195 mm** | **~5.5 px/mm** |
| **6 mm** | **~35 cm** | **~180 mm** | **~6 px/mm, least distortion** |

Formula: `field_of_view = sensor_height × distance / focal_length`.

Prefer the 6 mm lens at about 35 cm if space allows. A longer lens distorts less, and the extra distance also makes reflections easier to control.

After focusing, **lock the lens** with its lock screw plus a drop of glue or nail polish, so focus never changes between experiments.

---

## 6. Recording PC, USB and storage

### Computer
- Any old desktop with a quad-core CPU (or better) is fine for **recording** several 1080p streams.
- **Analysis** needs a GPU (Section 8). That can be a used NVIDIA GTX 1660 or RTX 3060 12 GB in the same desktop, or a university GPU server.
- OS: **Ubuntu LTS** is recommended (simple v4l2 camera control, stable for 48 h runs).

### USB
- Each UVC camera reserves USB bandwidth. **Several cameras on one cheap hub often fail** ("No space left on device" on Linux).
- Use **MJPEG**, not uncompressed YUYV, at a fixed resolution and frame rate.
- Spread the cameras across **different motherboard USB ports or controllers**, or add a PCIe USB card. Use a **powered** hub only after testing all cameras together for several hours.
- Keep USB 2.0 cables at 5 m or less. Use short, good-quality cables.

### Lock camera settings (Linux)
```bash
v4l2-ctl --list-devices                      # find /dev/videoN for each camera
v4l2-ctl -d /dev/video0 --list-ctrls         # see the control names this camera exposes
v4l2-ctl -d /dev/video0 --list-formats-ext   # confirm MJPEG 1920x1080 at the frame rate you want

# Example (control names differ between cameras and kernels, so check --list-ctrls):
v4l2-ctl -d /dev/video0 \
  -c auto_exposure=1 -c exposure_time_absolute=150 \
  -c white_balance_automatic=0 -c white_balance_temperature=4600 \
  -c gain=0
```
Write down the exact values and apply them from a script at the start of every run.

### Recording (example, to test in the pilot)
```bash
ffmpeg -f v4l2 -input_format mjpeg -video_size 1920x1080 -framerate 15 \
       -use_wallclock_as_timestamps 1 -i /dev/video0 \
       -c:v libx264 -preset veryfast -crf 22 -g 30 \
       -f segment -segment_time 3600 -reset_timestamps 0 -strftime 1 \
       station1_%Y%m%d_%H%M%S.mkv
```
- **1-hour segments**: a crash or power cut loses at most an hour, and files are easier to handle.
- Wall-clock timestamps are kept in the MKV files, so per-frame times can be extracted later with `ffprobe`.
- Run each station as a **systemd service** that restarts recording if it stops, and put the PC on a small UPS if possible.
- With one PC, all stations share **one clock**, so no syncing between computers is needed.

### Storage estimate (per camera, 48 h)
| Format | Approximate size |
|---|---|
| 1080p, 15 fps, H.264 (CRF ~22, static background) | **~50–100 GB** |
| 1080p, 15 fps, raw MJPEG (no re-encoding) | ~300–500 GB |

A **4 TB HDD** holds roughly 40+ station-runs at 1080p H.264. Back up the raw videos to university storage or a NAS after each run.

---

## 7. Fixed rig (3D printed, Bambu Lab P2S)

**Principle:** the dish and the camera sit on **one rigid rail**, so the distance is fixed by the parts, not by placing them on the table.

- **Rail:** a 400–450 mm **2020 aluminium extrusion** (about $5 on AliExpress). The P2S bed (256 × 256 mm) is too small to print a 35 cm one-piece rail.
- **Printed parts:**
  - **Dish cradle:** fits the exact dish diameter, with a key or notch so the dish always sits in the same orientation. It holds a printed or laser-printed **calibration scale** in view.
  - **Camera mount:** fits the camera board's screw pattern (32×32 or 38×38 mm), with the optical axis at the dish centre and a **locating pin or end-stop** at the measured distance.
  - **Light arms:** hold the front LEDs at a fixed 30–45° angle.
  - **Light-proof shroud** (optional, recommended): a tunnel between camera and dish, matte black inside. It blocks room light and reflections and acts as the divider between stations.
- **Material:** **PETG** (or ASA/ABS) if the rig goes into a warm incubator at 30–34 °C, because PLA slowly bends under load at those temperatures. Use matte black filament for anything the camera can see.
- **CAD:** a parametric OpenSCAD model (dish diameter, distance, camera hole pattern and light angle as variables) will be made **after the camera is chosen**, using its measured dimensions.

---

## 8. Video analysis pipeline

48 h videos are fine: they are processed as 48 one-hour segments per camera.

### Step 1: Calibration and pre-processing
- **Lens calibration:** film a printed checkerboard once per camera and lens, then correct lens distortion (OpenCV).
- **Scale:** convert px to mm from the calibration scale in the cradle.
- **Crop and mask** to the dish, which shrinks the image and removes false detections outside the dish.

### Step 2: Tracking and identity

| Tool | What you get | Catch | Role |
|---|---|---|---|
| **SLEAP**, multi-animal **top-down ID model**, RGB input | Body points (head, thorax, abdomen tip, optionally antennae), giving heading and **head-to-queen contacts**. The ID model learns *"blue dot = worker 6"* from the colour marks, so identity comes from each frame's appearance, not from following the bee over time. | You hand-label about 200–500 frames (body points + who is who). Needs a GPU. | **Main model.** |
| **TRex** (Walter & Couzin, eLife 2021) | Very fast. With background subtraction it needs **no labelling**. Its visual identification network learns each individual's look. Exports X/Y in cm, ANGLE and SPEED per bee to CSV/NPZ. | By default it turns frames to **greyscale** (`color_channel`), so colour marks may not help it. The docs don't say how identities carry over between separate 1 h files. | **Pilot and quick paths**, and a check on SLEAP's results. |
| YOLO11 (detect/pose) + tracker + colour classifier (custom) | Flexible, fully under our control. TRex can also run a custom YOLO model (`detect_model`). | The most code to write and maintain. | Fallback if the vertical dish or belly views break the other tools. |

**Why SLEAP's ID model fits this project:** each team keeps the same dot colour for the same worker label. Then each frame is labelled independently, so identities stay the same across 1 h segments, whole 48 h runs, and even different experiments. An ID swap can't spread forward in time, because every frame is identified on its own.

**Key TRex settings** (from the docs, check against the version you install):
- `track_max_individuals = 11`
- set `cm_per_pixel` (or `meta_real_width`) from the calibration scale
- `detect_threshold` for background subtraction
- `individual_image_size`
- `output_format = csv`
- `auto_apply` / `visual_identification_model_path` to reuse a trained ID network on the next segment
- batch: `trex -i seg.pv -s track.settings -auto_quit -task track`
- install: `conda create -n track -c trexing trex`

### Step 3: Output dataset
One CSV (or Parquet) file per experiment:
```
experiment_id, station, frame, timestamp, bee_id, x_mm, y_mm, heading_deg, confidence
```

### Step 4: Behaviour measures (examples)
- Speed, distance walked, active/rest bouts, day/night activity.
- Distance of each worker to the queen over time, and time spent near her (retinue).
- Contact events and **contact networks** (who meets whom, how often, for how long).
- Space use per bee (heat maps), and how consistent individuals are across experiments.

### Step 5: Validation (needed for publication)
- Hand-check a few hundred **random frames** per experiment and report **identity accuracy** and **detection rate**.
- Keep the labelled frames as a test set to compare model versions.

### Compute
At 15 fps, 48 h is about **2.6 M frames per camera**. On a mid-range NVIDIA GPU that takes hours to about a day per video. CPU-only processing is impractical. Options: a used RTX 3060 12 GB (about $200–250) in the desktop, or a university GPU server.

---

## 9. Budget

Approximate AliExpress prices, per station unless noted.

| Item | Cost |
|---|---|
| 1080p USB camera module, M12 manual-focus lens | $20–30 |
| Spare M12 lens (4 mm / 6 mm, low distortion) | $3–5 |
| Front LED strips + diffuser + DC supply | $5–10 |
| 2020 extrusion 400–450 mm + T-nuts and screws | $5–8 |
| Filament (PETG, matte black) | ~$3–5 |
| **Per station** | **~$40–60** |
| Paint markers + queen marking discs (shared) | ~$10–15 |
| 4 TB HDD (shared) | ~$80–100 |
| Used GPU for analysis (shared, optional if a university server is available) | ~$150–250 |
| Old desktop | already available |

---

## 10. Open questions for the PI

1. **Dish orientation:** vertical (as drawn, comb-like) or flat with the camera above? (Issue B)
2. **Queen:** caged inside the dish (as drawn) or free?
3. **Lighting regime:** constant light, or a light/dark cycle? This decides paint vs tags, and whether IR is needed.
4. **Environment:** will the rig run inside an incubator? This affects size limits, heat from the LEDs, PETG, humidity and fogging.
5. **Food and water:** how are they given for 48 h without blocking the view?
6. **Behaviours of interest:** only position and paths, or also contacts and interactions with the queen? (TRex vs SLEAP)
7. **Dish size:** exact diameter and height (for example 150 × 20 mm)?

---

## 11. Pilot plan

1. Buy **one** camera and two lenses (4 mm and 6 mm).
2. Print a quick test cradle and camera mount, and mount them on a 2020 rail.
3. Mark a few bees, record **1–2 hours** with front lighting and locked settings.
4. Check: are the colours clearly different? Is there glare or fog? Is the frame rate stable? What are the file sizes?
5. Run TRex (no labelling) on the pilot video for quick paths. Label about 200 frames in SLEAP and train a small top-down ID model. Hand-check identity accuracy for both.
6. Test **all cameras together on the desktop** for several hours (USB bandwidth).
7. Freeze the design: final CAD/STL, written settings, and a standard operating procedure. Then buy the remaining cameras **from the same listing**.

---

## 12. Sources

- TRex paper: Walter & Couzin, *eLife* 2021, [PMC8096434](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8096434/); project page [trex.run](https://trex.run)
- SLEAP: [sleap.ai](https://sleap.ai)
- ELP IMX415 4K USB camera listings (higher-budget reference): [Newegg](https://www.newegg.com/p/3C6-01ZY-01AD8), [5–50 mm varifocal](https://www.desertcart.ni/products/517355985-4k-usb-camera-with-5-50mm-varifocal-lens)
- ELP IMX179 8MP varifocal (alternative considered): [listing](https://dhm-online.com/en/tools/13386-elp-8-megapixel-webcam-with-5-to-50-mm-variofokus-hd-lens.html), [eBay](https://www.ebay.de/itm/324089928103)
