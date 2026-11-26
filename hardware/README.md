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
| Outside | **110 × 99 × 30.4 mm** (width × height × depth) |
| Room for the bees | 100 × 90 mm, **20 mm deep** (from the comb foundation to the glass) |
| Glass to order | **104 × 99 × 2 mm**, 4 + spares |

- **White PETG body**, printed back-wall-down, no supports.
- **3 feeder holes, Ø 9 mm**, in the back wall, low (centres 10 mm above the floor, at −30 / 0 / +30 mm):
  candy, water, pollen. They stay open.
- **3 queen-cell holes, Ø 13 mm**, in the top wall, above the same three positions. The queen-cell
  holder (the blue cup with a disc and a small peg) drops in from above; its disc rests on the top and sticks
  out about 8 mm.
- **Glass cover** slides down through a slot in the top wall into grooves in both side walls and the bottom
  wall. It sticks out 3 mm above the top to grab it, and a finger notch in the front edge helps push it up.
  It comes out **with the queen cells in place**: the holes sit just far enough back that the holders' discs
  don't cover the glass slot.
- **Comb foundation** (`foundation.stl`, printed separately): a 99.4 × 89.4 × 1.8 mm sheet with worker-sized
  hexagonal cells (5.4 mm). It lies against the inside of the back wall and goes in and out through the front
  when the glass is off. Its 3 holes line up with the feeder holes, so feeder tubes go through it. It has
  0.3 mm of play on each side; a tube still passes even when the sheet is pushed to one side.
- **Queen-cell caps** (`qc_cap.stl`): close any queen-cell hole you don't use. 3 per cage.
- **Vents**: horizontal slits, 1.8 mm high (bees can't pass), in both side walls.
- **2 magnets** (10 × 2 mm) in the back of the cage hold it against the rack.

### Why the queen cells hang 2 mm from the comb

The holder's disc is about **22 mm** wide and the bee room is only 20 mm deep. The disc has to stay behind
the glass slot, or the glass can't come out. So the holes sit 8.5 mm in front of the foundation: the
cups hang about 2 mm from the comb and 5 mm from the glass, a bit like a queen cell on a real comb.

**Measure your holder's disc.** If it's smaller, the holes move forward automatically: change `QC_FLANGE_D`
in `cages.py` and run it again. If it's bigger than about 25 mm it no longer fits with 20 mm of bee room;
the check will fail and say so.

## The rack and the stand

- **Rack** (`rack.stl`, 234 × 236 × 36 mm): 2 × 2 **separate pockets**, each with a floor, a wall on each side,
  a back wall and **12 mm of space above the cage** for the queen-cell holders (4 mm to spare). A cage with its
  queen cells in place slides straight in from the front and is held by 2 magnets at the back.
  - Ø 14 mm holes in the back wall line up with every cage's feeder holes, so **feeders are pushed in and
    refilled from behind**, without touching the cage.
  - Windows in the walls beside each cage's vents let air through.
  - The fronts of the cages are flush with the front of the rack, all 4 glasses in one plane.
- **Stand** (`stand.stl`, 243 × 151 mm): the rack drops into a rim and is fixed with **2 countersunk
  M5 × 12 screws** down through the floors of the lower pockets. Their heads sit flush, so the cages slide over
  them. The nuts go into hexagonal pockets under the stand.
  - **On a table:** the stand reaches 55 mm behind and 60 mm in front of the rack, so it won't tip unless
    tilted past about 25°. Four shallow recesses underneath take 10 mm stick-on rubber feet.
  - **On a rail (for the camera, later):** underneath is a groove that fits a **2020 aluminium profile**
    running towards the camera, with **2 M5 holes for T-nuts**. Bolt the stand and the camera to the same
    profile, and the camera distance is fixed and repeatable. Reference: the front face of the glass is
    **36.8 mm behind the stand's front M5 hole**, so measure the camera distance from that hole.

Order of work with a cage: put in the foundation, then the queen cells (from above), then the glass, then
the bees; slide the cage into its pocket; push the feeders in from behind. To take the glass out, slide the
cage out of the rack first.

## The fit check

```bash
pip install manifold3d trimesh numpy scipy matplotlib
python hardware/cages/cages.py check
```

This writes every STL, builds the **whole assembly** (stand, rack, 4 cages, each with its glass, foundation,
3 caps and magnets; only the feeder holes left open), and tests it:

- every part is a closed solid and fits the P2S bed (256 × 256 × 256 mm);
- **no two of the 42 parts overlap**;
- all 12 feeder holes are open in a straight line from behind the rack, through the rack, the cage and the
  foundation, into the bees;
- the queen-cell holders fit their holes, miss the foundation and the glass, and **the glass slides out with
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
