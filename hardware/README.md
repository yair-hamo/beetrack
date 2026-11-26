# Bee cages and rack

Four white cages, each holding **exactly 10 marked workers** and up to **3 queen cells**, standing in one rack
so a single camera can film all four at once. This folder covers what is being built now: **the cages, the
rack and its stand**. The camera and light come later (see the end of this page).

- **What to print:** [`cages/stl/`](cages/stl/), made by [`cages/cages.py`](cages/cages.py).
- **Fit check:** [`cages/check/`](cages/check/): every part assembled together and tested (see below).
- **What to buy:** [SHOPPING_LIST.md](SHOPPING_LIST.md).

![Fit check: front view, side section, horizontal section](cages/check/assembly.png)

## One cage

| | Size |
|---|---|
| Outside | **110 × 100 × 27 mm** (width × height × depth) |
| Room for the bees | 100 × 90 mm, **15 mm deep** from the cell tops to the glass (18 mm from the back wall) |
| Glass to order | **106.5 × 94 × 2 mm**, 4 + spares (not printed) |
| Glass route | **3 mm** wide, like the cages already in use: 2 mm glass + 1 mm play |

- **White PETG body**, printed back-wall-down, no supports.
- **3 feeder holes, Ø 9 mm**, in the back wall, low (centres 10 mm above the floor, at −30 / 0 / +30 mm):
  candy, water, pollen. They stay open.
- **3 queen-cell holes, Ø 13 mm**, in the top wall, above the same three positions. The queen-cell
  holder (the blue cup with a disc and a small peg) drops in from above; its disc rests on the top and sticks
  out about 8 mm.
- **Glass cover slides in and out sideways**, from the **right**: through a slot in the right wall, along
  grooves in the top, bottom and left walls. The front is open on the right, so you push the glass out with a
  thumb on its face. It comes out at any time, with the queen cells in place. Inside the rack, the pocket wall
  stops it from sliding out.
- **Comb foundation** (`foundation.stl`, printed separately): a 99.4 × 89.4 mm sheet, 1 mm thick, with
  worker-sized hexagonal cells (5.4 mm) whose walls stand **2 mm** above it (0.8 mm thick), 3 mm in total.
  Change `CELL_H` / `CELL_WALL` for deeper or bolder cells. It lies against the inside of the back wall and
  goes in and out through the front when the glass is off. Its 3 holes line up with the feeder holes, so
  feeder tubes go through it. It has 0.3 mm of play on each side; a tube still passes even when the sheet is
  pushed to one side. The sheet is whole: the queen cells hang just in front of it.
- **Queen-cell caps** (`qc_cap.stl`): close any queen-cell hole you don't use. 3 per cage.
- **Vents**: 23 horizontal slits per side, 1.8 mm high (bees can't pass), with 1.8 mm bars between them, over
  the whole height of both side walls. The rack walls beside them are open too.
- **2 magnets** (10 × 2 mm) in the back of the cage hold it against the rack.

### How shallow it can be: the queen cells decide

The cage is made **as shallow as the queen-cell holders allow**, so bees can't turn over inside:

- Each queen cell hangs **1 mm in front of the foundation cells** (the sheet stays whole) and **1 mm behind
  the glass**. With the 13 mm holes that gives **15 mm from the cell tops to the glass** (18 mm from the back
  wall).
- The glass slides out sideways, so the holders' 22 mm discs (wider than the bee room) don't block it.
- The discs still fit on the top of the cage, 3.5 mm from its back edge, clear of the rack.

**Measure your holders** (tube and disc) and the length of a hanging queen cell, then set `QC_D`,
`QC_FLANGE_D` and `QC_CELL_LEN` in `cages.py` and run it again. The depth follows automatically
(`QC_COMB_GAP` and `QC_GLASS_GAP` set the 1 mm gaps).

## The rack and the stand

- **Rack** (`rack.stl`, 234 × 238 × 32.5 mm): 2 × 2 **separate pockets**, each with a floor, a wall on each side,
  a back wall and **12 mm of space above the cage** for the queen-cell holders (4 mm to spare). A cage with its
  queen cells in place slides straight in from the front and is held by 2 magnets at the back.
  - Ø 14 mm holes in the back wall line up with every cage's feeder holes, so **feeders are pushed in and
    refilled from behind**, without touching the cage.
  - Windows in the walls beside each cage's vents, over their whole height, let air through.
  - The fronts of the cages are flush with the front of the rack, all 4 glasses in one plane.
- **Stand** (`stand.stl`, 243 × 148 mm): the rack drops into a rim and is fixed with **2 countersunk
  M5 × 12 screws** down through the floors of the lower pockets. Their heads sit flush, so the cages slide over
  them. The nuts go into hexagonal pockets under the stand.
  - **On a table:** the stand reaches 55 mm behind and 60 mm in front of the rack, so it won't tip unless
    tilted past about 25°. Four shallow recesses underneath take 10 mm stick-on rubber feet.
  - **On a rail (for the camera, later):** underneath is a groove that fits a **2020 aluminium profile**
    running towards the camera, with **2 M5 holes for T-nuts**. Bolt the stand and the camera to the same
    profile, and the camera distance is fixed and repeatable. Reference: the front face of the glass is
    **37 mm behind the stand's front M5 hole**, so measure the camera distance from that hole.

Order of work with a cage: put in the foundation, then the glass (from the right) and the queen cells (from
above), in either order; add the bees with the glass part-way open; slide the cage into its pocket; push the
feeders in from behind. To take the glass out, slide the
cage out of the rack first.

## The fit check

```bash
pip install manifold3d trimesh numpy scipy matplotlib
python hardware/cages/cages.py check
```

This writes every STL, builds the **whole assembly** of printed parts (stand, rack, 4 cages, each with its
foundation, 3 caps and magnets; only the feeder holes left open; the glass is left out because it isn't
printed, but the check still tests it), and tests it:

- every part is one closed solid (nothing loose or floating) and fits the P2S bed (256 × 256 × 256 mm);
- **no two of the 38 parts overlap**;
- all 12 feeder holes are open in a straight line from behind the rack, through the rack, the cage and the
  foundation, into the bees;
- the queen-cell holders fit their holes, miss the foundation and the glass, and **the glass slides out sideways with
  all 3 in place**;
- the glass fits its grooves; the foundation goes in and out through the front;
- a cage with 3 queen cells slides into every pocket;
- the stand is stable.

Results: [`check/check_report.txt`](cages/check/check_report.txt), the picture above, and the whole assembly as
[`check/assembly.stl`](cages/check/assembly.stl) (opens in GitHub's 3D viewer and in Bambu Studio) and
[`check/assembly.glb`](cages/check/assembly.glb) (in colour). If you change any number in `cages.py`, run the
check again; it ends with `ALL CHECKS PASSED` or names what doesn't fit.

## Printing (Bambu Lab P2S, PETG)

| Part | Qty | Colour | How |
|---|---|---|---|
| `cage` | 4 (+1 spare) | white | back wall on the bed (as exported); 0.2 mm layers, 4 walls, 20 % infill; no supports |
| `foundation` | 4 (+1) | white or natural | flat, cells up (as exported); 0.12 mm layers so the cell walls come out clean |
| `qc_cap` | 12 | white | flange on the bed |
| `rack` | 1 | white or black | back wall on the bed (as exported); 4 walls, 15 % gyroid; no supports |
| `stand` | 1 | any | as exported (rim up) |

PETG, not PLA: PLA softens in a warm bee room. Glue the magnets with a drop of superglue and **check the
polarity** so cage and rack attract.

**Test before printing all of them:** print one cage, one foundation and one cap. Check the glass slides
freely, the holder and the feeder tubes fit their holes, and the cap is snug. Then measure and correct
`GLASS_T`, `QC_FLANGE_D`, `FEED_D` or `CAP_STEM_D` in `cages.py` if needed, and run the check again.

## Later: camera and light (not being built now)

The plan stays as before: one colour industrial camera (Hikrobot MV-CS050-10UC, 5 MP) with a 12 mm lens about
42 cm in front of the glass. That gives about 8 px/mm, so a 2–3 mm paint dot is 16–24 pixels wide. Add
constant LED light (CRI ≥ 90) with cross-polarisation against glass reflections, and software that crops the
4 cages live into 4 videos and analyses them while the run goes on. The camera will mount on the same 2020
profile as the stand. The camera and light parts will be designed when that stage starts.
