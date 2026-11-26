# The playground: recording rig for 4 plates

A closed, light-tight box that films **4 plates at once**, each with **exactly 10 marked workers and a queen
cell**, for up to 48 hours, in colour, under constant light. One industrial camera; the software crops the 4
plates live and analyses them while the experiment runs.

- **What to buy:** [SHOPPING_LIST.md](SHOPPING_LIST.md) (pilot ≈ ₪2,700–4,000).
- **What to print:** [`cad/stl/`](cad/stl/), made by [`cad/playground.py`](cad/playground.py) (parametric:
  measure your glass, tubes and camera, change the numbers, run it again).
- This replaces the older webcam plan in [`docs/HARDWARE.md`](../docs/HARDWARE.md).

```
SIDE VIEW (box lying on the shelf, camera looking horizontally at the standing plates)

 back panel           rack + 4 plates          light panel            camera
 (feeder access)      (glass faces camera)     (diffuser + LEDs)      (12 mm lens)
   ║                       │▌                        ║ ║                  ┌──┐
   ║   tubes ──────────►   │▌ glass                  ║ ║ ◄─ lens looks ── │▓▓│◄── USB3 to PC
   ║                       │▌                        ║ ║    through hole  └──┘
   ║◄─45─►│◄─ 26 ─►│◄────────────── ≈ 42 cm ──────────────►│
   0 mm                  ≈ 73 mm                     ≈ 495 mm          ≈ 560 mm      600 mm
```

## Why the plates stand up

It matches the current setup: the **queen cell hangs down from the top**, as in a hive, and food and water come
in through the **back wall**, far from the camera, so tubes never block the view. The glass is the face
toward the camera and slides out upward. As now, a bee walking on the glass shows its belly; marking both
sides of each bee (already planned) keeps those bees identifiable.

## Is 5 MP enough? Yes, at about 8 px/mm

The 4 plates (228 × 228 mm with the rack) fill the camera's 2048-pixel height, so a **2–3 mm paint dot is about
16–24 pixels across**: three times the old 452-pixel video and more than our analysis needs.

The Samsung A57 videos failed for reasons a phone can't avoid, not resolution:

| Phone video | This rig |
|---|---|
| Auto white balance and exposure keep changing the colours | **Locked** exposure, gain and white balance for the whole run |
| Heavy video compression smears small coloured dots | Light compression (CRF 18), straight from the sensor |
| Noise reduction and sharpening invent and erase detail | No phone image processing |
| Room light: uneven, low colour quality, often flickering | Constant LED light, **CRI ≥ 90**, diffused, no flicker |
| Reflections from the dish | Cross-polarised light removes reflections |
| Hand-held or loosely placed | Fixed distance and position every run |

If the pilot shows you want more detail (for example for leg/antenna tracking), film fewer plates per camera
rather than buying a bigger sensor: higher-resolution models need larger, more expensive lenses.

## Where to put it

In the **climate room** (constant temperature and humidity), so the plates live in the bees' conditions:

- **On a sturdy shelf or lab bench at waist height**, footprint about 40 × 65 cm. Not on top of a cupboard
  (heat collects there; awkward to reach) and not on the floor.
- **Away from vibration**: not on the same shelf as a fridge, incubator or anything with a compressor or fan.
- **Out of the room's air stream**: not under or in front of the air-conditioning outlet.
- **PC next to the box** on a separate shelf (USB cable ≤ 3 m), or a laptop. The PC adds some heat to the
  room; the logger (F2) in the room shows whether the climate control keeps up. If the PC must be outside the
  room later, switch to the GigE version of the camera (Ethernet cable through the wall).
- One temperature/humidity logger **inside the box next to the plates**: the LEDs warm the box a little.
  It should read within ~0.5 °C of the room. If not, add the vent holes below or a small 24 V fan.

## The box

A 2020 aluminium frame, **340 × 340 mm outside, 600 mm deep**, closed with matte black PVC panels:

| Part | What | Notes |
|---|---|---|
| Frame | 4 × 600 mm (depth) + 8 × 300 mm profiles, 24 corner brackets | Square and stiff: the camera distance must never change |
| Back panel | 6 mm, black | Rack bolted on with 4 × M5; **8 holes Ø 14 mm behind the tube ports**, so feeders and water are refilled **from outside without opening the box** |
| Side door | One side panel, lift-off, held by magnets | To take plates in and out |
| Rack | Printed, bolted to the back panel, centred | 4 pockets with magnets: every plate sits in exactly the same place, every run |
| Camera bar | 1 × 300 mm profile across the front, at the rack's centre height (T-nuts: adjustable) | Camera mount slides on it to centre left/right |
| Light | LED board + diffuser panel, both on printed clips, just in front of the camera | See below |
| Vents | A row of Ø 8 mm holes in the top and bottom panels, near the back | Air exchange with the room |

### Light: constant, even, without reflections

- **COB LED strip** (CRI ≥ 90, 4000 K, 24 V), about 1.2 m in 4 rows, stuck on the black **LED board**
  (300 × 300 mm, Ø 60 mm hole for the lens), facing the plates.
- **Opal acrylic diffuser** 40 mm in front of the LED board (same size, same hole): one big, even,
  shadow-free light source around the lens.
- **Cross-polarisation**: a sheet of polariser film on the diffuser, and a film disc in the printed
  `pol_ring` in the diffuser hole, in front of the lens. Turn the ring until the glass reflections vanish
  (about 90° to the panel's film), then fix it. This removes glare from all 4 glasses, and shine on the bees.
- **Constant**: full power from the 24 V adapter, no dimmer, the same in every run. Measure the light at the
  plates once with the lux meter (F3) and write it in the methods.

## The plate

`plate.stl` + `background_insert.stl` + a 2 mm glass, outside **110 × 110 × 25.6 mm**, arena **100 × 100 mm,
15 mm deep** (back to glass).

- **Black body**, printed back-wall-down. Ventilation slots (1.8 mm, bees can't pass) in both side walls.
- **White background insert** (removable, washable): light background = dark bees with bright dots stand out.
  A sheet of beeswax foundation cut to 99 × 99 mm can replace it, like the current setup.
- **Queen-cell ledge** near the top of the insert: fix the queen cell under it with a little wax, hanging down.
- **Glass** (104 × 107 × 2 mm) slides down into grooves in the side and bottom walls; a finger notch at
  the top to pull it out.
- **Two ports Ø 11 mm** in the back wall, low: feeder and water tubes from behind (1.5 mL microtube or
  cut 5 mL syringe; check the fit and change `PORT_D`). `port_plug.stl` closes an unused port.
- **Two magnets** (10 × 2 mm) in the back hold the plate in its rack pocket; a notch on the top edge shows
  which way is up.

### Printing (Bambu Lab P2S, PETG)

| Part | Qty | Colour | Orientation / settings |
|---|---|---|---|
| `plate` | 4 (+1 spare) | black | back wall on the bed; 0.2 mm layers, 4 walls, 25 % infill; no supports |
| `background_insert` | 4 (+1) | white | flat; 0.16 mm layers for a smooth face |
| `rack` | 1 | black | as modelled (skirt on the bed, pockets up); 4 walls, 15 % gyroid; ≈ 11 h |
| `camera_mount` | 1 | black | mounting plate on the bed |
| `pol_ring`, `pol_retainer` | 1 each | black | flat |
| `panel_clip` | 8 | black | shelf on the bed |
| `port_plug` | 4 | black | flange on the bed |

Glue the magnets with a drop of superglue; **check the polarity** so plate and rack attract.

## Software: live crops and live analysis (to build next)

What the PC will do during a run:

1. **Record**: talks to the camera directly (Hikrobot MVS / GenICam), locks exposure, gain and white balance,
   15 fps, and writes a timestamp for every frame.
2. **Crop live into 4 videos**: the 4 plate rectangles are drawn once per rig on a live preview (the rack
   keeps them fixed). Each plate is saved as its own video in 10-minute pieces, plus a small overview video of
   the whole view for checking.
3. **Analyse live**: as soon as a 10-minute piece of a plate is finished, beetrack analyses it, so a run's
   dashboard updates every ~10 minutes: who visited the queen cell and for how long, paths, heat map, an
   annotated frame, and warnings (a bee not seen for a while, a mark not read, temperature drift).
4. **Final pass** at the end: one analysis over the whole run per plate, with identity across all pieces,
   giving the same results files as today (CSV / Parquet, videos).

This needs new code in beetrack (camera recorder, multi-plate cropping, a live dashboard). It will be done as
separate pull requests after the pilot box is built.

## Pilot checklist

1. Print one plate + insert; test the glass slide and the tube ports with the real glass and tubes.
2. Build the box; set the camera ~42 cm from the glass; focus the lens at f/4–5.6 on the plate surface;
   **lock focus and iris**.
3. Lock camera settings: exposure ≤ 8 ms, gain low, white balance once on the colour checker.
4. Turn the polariser ring until reflections are gone.
5. One plate with 10 marked bees, 2 hours: do all 10 colours separate in beetrack's "Find the marks"?
   Glare? Fog on the glass? Temperature in the box vs the room?
6. Then 4 plates for 48 hours.
