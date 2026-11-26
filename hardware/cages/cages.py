"""Bee cages for the recording rig: 4 white cages, a rack that holds them, and a stand.

    python hardware/cages/cages.py           # write every printable part to hardware/cages/stl/
    python hardware/cages/cages.py check     # also build the full assembly and test that everything fits

Needs: pip install manifold3d trimesh numpy scipy matplotlib

All sizes are millimetres. Measure your real glass, queen-cell holders and tubes, change the numbers under
PARAMETERS, and run the script again. Every part fits the Bambu Lab P2S bed (256 x 256 x 256 mm).

What one cage needs (print / buy):
    cage.stl          1   white PETG   the cage: 3 feeder holes (back, low) + 3 queen-cell holes (top)
    foundation.stl    1   white/natural the comb foundation sheet that lies against the inside of the back wall
    qc_cap.stl        3   white PETG   caps that close the queen-cell holes that are not used
    glass             1   2 mm glass, 106.5 x 94 mm (see GLASS_W / GLASS_L below), slides in from the right
And for the rack of 4 cages: rack.stl (1), stand.stl (1), 2 x M5x12 countersunk + nuts.

World coordinates (used for the assembly): x = left -> right, y = back -> front (towards the camera),
z = up. The cage stands up: the glass is its front face, the queen cells hang from the top wall, the
feeders come in through the back wall.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold

# --------------------------------------------------------------------------- #
# PARAMETERS
# --------------------------------------------------------------------------- #
# cage: the room for the bees
IN_W = 100.0            # inside width
IN_H = 90.0             # inside height (minimum 90)
# (the depth of the bee room is not set here: it is made as small as the queen-cell holders allow, see below)
WALL = 5.0              # left/right/bottom walls (they hold the glass groove)
TOP_T = 5.0             # top wall (holds the queen-cell holes and the top glass groove)
BACK_T = 4.0            # back wall (holds the feeder holes)

# glass cover: slides in SIDEWAYS, through a slot in the right wall, along grooves in the top, bottom and left
# walls. So the queen-cell holders on top never block it, and the cage can be as shallow as the holders allow.
GLASS_T = 2.0           # measure your glass / perspex!
GLASS_SLOT = 3.0        # width of the glass route (grooves + side slot); 3 mm like the cages already in use
GLASS_CLR = GLASS_SLOT - GLASS_T   # play, so the glass slides freely
GROOVE = 2.5            # how deep the glass sits in the top, bottom and left walls
LIP = 2.0               # wall in front of the glass on the top, bottom and left (holds it in); open on the right

# comb foundation sheet (printed separately, lies on the inside of the back wall)
FOUND_BASE = 1.0        # the flat sheet
CELL_H = 2.0            # how far the cell walls stand up from the sheet
FOUND_T = FOUND_BASE + CELL_H
CELL = 5.4              # worker cell size, centre to centre (flat to flat)
CELL_WALL = 0.8         # cell wall thickness (2 lines of a 0.4 mm nozzle)
FIT = 0.3               # clearance around parts that go into each other

# holes
FEED_D = 9.0            # feeders: candy, water, pollen
FEED_X = (-30.0, 0.0, 30.0)
FEED_Z = 10.0           # centre height of the feeder holes above the inside floor
QC_D = 13.0             # queen-cell holder holes in the top wall
QC_X = (-30.0, 0.0, 30.0)

# queen-cell holder (the blue plastic cup with a disc on top). MEASURE YOURS: the disc decides where the holes go.
QC_FLANGE_D = 22.0      # disc that rests on the top wall
QC_ABOVE = 8.0          # how far the holder sticks out above the top wall
QC_CELL_LEN = 30.0      # how far the cup + cell hang down into the cage
QC_COMB_GAP = 1.0       # hole edge -> tops of the foundation cells (the foundation stays whole)
QC_GLASS_GAP = 1.0      # hole edge -> glass route

# cap for an unused queen-cell hole
CAP_STEM_D = 12.6
CAP_FLANGE_D = 18.0
CAP_FLANGE_T = 1.6
CAP_PRY_W, CAP_PRY_D = 4.0, 1.0   # small groove under one edge of the flange: lift the cap with a screwdriver tip

# vents (bees can't pass 1.8 mm)
VENT_W, VENT_PITCH = 1.8, 3.6   # slit height, slit-to-slit (1.8 mm bars between slits)

# locating sockets in the back of each cage (2 per cage, Ø 10.3 x 2.2 mm) and the matching pegs on the rack
SOCKET_D, SOCKET_T = 10.3, 2.2    # the sockets in the cage (first made for 10 x 2 mm magnets)
SOCKET_X, SOCKET_Z = 38.0, 80.0   # from the cage centre / from the cage bottom
PEG_D = 10.0                      # peg on the rack: 0.15 mm play all round in the socket (10.1-10.2 = tighter)
PEG_L = 2.0                       # 0.2 mm shorter than the socket is deep, so the cage still touches the rack
PEG_CHAMFER = 0.6                 # bevelled tip, guides the cage onto the pegs

# rack: 2 x 2 pockets, each with a floor, walls on both sides, a back wall and room above for the queen cells
RACK_WALL = 4.0
RACK_BACK = 5.0
RACK_FLOOR = 6.0        # the bottom slab (the countersunk screws to the stand go through it)
POCKET_CLR = 0.5        # cage <-> pocket walls, each side
HEAD_ROOM = 4.0         # above the queen-cell holders
RACK_HOLE_D = 14.0      # holes in the rack back wall behind the feeder holes

# stand: the rack drops into it; it stands on a table or bolts onto a 2020 aluminium profile
STAND_T = 8.0
STAND_FRONT, STAND_BACK = 60.0, 55.0     # how far the stand reaches in front of / behind the rack
RIM_H, RIM_T = 6.0, 4.0
RAIL_W, RAIL_DEPTH = 20.4, 3.0           # groove underneath for a 2020 profile
M5, M5_HEAD = 5.5, 10.4                  # M5 hole; countersunk head diameter
M5_NUT = 8.4                             # M5 hex nut across flats + clearance

BED = 256.0
SEG = 96
HERE = Path(__file__).parent
STL = HERE / "stl"
CHECK = HERE / "check"

# --------------------------------------------------------------------------- #
# derived sizes
# --------------------------------------------------------------------------- #
G = GLASS_T + GLASS_CLR
Y_FOUND = BACK_T                         # inside face of the back wall
Y_BEE0 = Y_FOUND + FOUND_T               # front face of the foundation (tops of the cells)
# The queen-cell holes decide the depth: each hole sits QC_COMB_GAP in front of the foundation cells (and far
# enough forward that the holder's disc doesn't stick out behind the cage), and the glass comes QC_GLASS_GAP
# in front of the hole. Everything else follows.
QC_YW = max(Y_BEE0 + QC_COMB_GAP + QC_D / 2, QC_FLANGE_D / 2 + 0.5)    # hole centre, world y
Y_GLASS = QC_YW + QC_D / 2 + QC_GLASS_GAP                            # back of the glass groove
BEE_D = Y_GLASS - Y_BEE0                 # bee room: cell tops -> glass
QC_Y = QC_YW - Y_BEE0                    # hole centre, from the cell tops
Y_LIP = Y_GLASS + G                      # back of the front lip
CAGE_D = Y_LIP + LIP                     # cage depth (back -> front)
CAGE_W = IN_W + 2 * WALL
Z_FLOOR = WALL
Z_ROOF = WALL + IN_H
CAGE_H = Z_ROOF + TOP_T
GLASS_X0 = -IN_W / 2 - GROOVE + 0.5                                 # left end, in the left groove
GLASS_X1 = CAGE_W / 2 - 0.5                                         # right end, flush with the right wall
GLASS_W = GLASS_X1 - GLASS_X0                                       # glass to order (width)
GLASS_Z0 = Z_FLOOR - GROOVE + 0.5
GLASS_L = IN_H + 2 * GROOVE - 1.0                                   # glass to order (height)

POCKET_W = CAGE_W + 2 * POCKET_CLR
POCKET_H = CAGE_H + QC_ABOVE + HEAD_ROOM
POCKET_D = CAGE_D + POCKET_CLR
RACK_W = 2 * POCKET_W + 3 * RACK_WALL
RACK_H = RACK_FLOOR + 2 * POCKET_H + 2 * RACK_WALL
RACK_D = RACK_BACK + POCKET_D
STAND_W = RACK_W + 2 * (FIT + RIM_T)
STAND_Y0 = -STAND_BACK
STAND_D = STAND_BACK + RACK_D + STAND_FRONT
STAND_HOLE_BACK_Y = STAND_Y0 + STAND_BACK / 2           # the 2 M5 holes for T-nuts in a 2020 profile
STAND_HOLE_FRONT_Y = RACK_D + RIM_T + STAND_FRONT / 2
GLASS_FRONT_Y = RACK_BACK + Y_GLASS + GLASS_CLR / 2 + GLASS_T

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def box(x0, x1, y0, y1, z0, z1) -> Manifold:
    """Axis-aligned box from min/max corners."""
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def cyl_z(d, z0, z1, x=0.0, y=0.0, seg=SEG) -> Manifold:
    return Manifold.cylinder(z1 - z0, d / 2, d / 2, seg).translate([x, y, z0])


def cyl_y(d, y0, y1, x=0.0, z=0.0, seg=SEG) -> Manifold:
    # cylinder along +y: build along z, rotate -90 about x  (z -> y)
    return Manifold.cylinder(y1 - y0, d / 2, d / 2, seg).rotate([-90, 0, 0]).translate([x, y0, z])


def cyl_x(d, x0, x1, y=0.0, z=0.0, seg=SEG) -> Manifold:
    return Manifold.cylinder(x1 - x0, d / 2, d / 2, seg).rotate([0, 90, 0]).translate([x0, y, z])


def union(parts) -> Manifold:
    return Manifold.batch_boolean(list(parts), 0) if len(parts) > 1 else parts[0]   # 0 = Add


def to_trimesh(m: Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))


# --------------------------------------------------------------------------- #
# parts, in world position for one cage standing at the origin
# (cage: x centred, back face at y = 0, bottom at z = 0)
# --------------------------------------------------------------------------- #
def cage() -> Manifold:
    hw = CAGE_W / 2
    body = box(-hw, hw, 0, CAGE_D, 0, CAGE_H)
    # the room: foundation + bees
    body -= box(-IN_W / 2, IN_W / 2, Y_FOUND, Y_GLASS + 0.01, Z_FLOOR, Z_ROOF)
    # glass route: grooves in the left, top and bottom walls, and straight out through the right wall
    body -= box(-IN_W / 2 - GROOVE, hw + 1, Y_GLASS, Y_LIP, Z_FLOOR - GROOVE, Z_ROOF + GROOVE)
    # front window, open to the right (the lip holds the glass on the left, top and bottom; on the right the
    # glass edge is free, to push it out with a thumb)
    body -= box(-IN_W / 2, hw + 1, Y_LIP - 0.01, CAGE_D + 1, Z_FLOOR, Z_ROOF)
    # feeder holes: back wall, low
    for x in FEED_X:
        body -= cyl_y(FEED_D, -1, Y_FOUND + 0.01, x, Z_FLOOR + FEED_Z)
    # queen-cell holes: top wall
    for x in QC_X:
        body -= cyl_z(QC_D, Z_ROOF - 0.01, CAGE_H + 1, x, QC_YW)
    # vents: horizontal slits through both side walls, in the bee room
    vy0, vy1 = Y_BEE0 + 2, Y_GLASS - 2
    z = Z_FLOOR + 3
    while z + VENT_W <= Z_ROOF - 3:
        body -= box(-hw - 1, -IN_W / 2 + 0.01, vy0, vy1, z, z + VENT_W)
        body -= box(IN_W / 2 - 0.01, hw + 1, vy0, vy1, z, z + VENT_W)
        z += VENT_PITCH
    # 2 locating sockets in the outside of the back wall (the rack's pegs go in)
    for x in (-SOCKET_X, SOCKET_X):
        body -= cyl_y(SOCKET_D, -1, SOCKET_T, x, SOCKET_Z)
    return body


def glass() -> Manifold:
    y0 = Y_GLASS + GLASS_CLR / 2
    return box(GLASS_X0, GLASS_X1, y0, y0 + GLASS_T, GLASS_Z0, GLASS_Z0 + GLASS_L)


def foundation() -> Manifold:
    """Sheet with hexagonal worker cells; 3 holes line up with the feeder holes. Lies flat on the inside of the back wall."""
    w, h = IN_W - 2 * FIT, IN_H - 2 * FIT
    x0, z0 = -w / 2, Z_FLOOR + FIT
    sheet = box(x0, x0 + w, Y_FOUND, Y_FOUND + FOUND_T, z0, z0 + h)
    # cells: hexagonal pockets in the front face, kept 1.5 mm from the edges and 1.8 mm from the holes
    r = (CELL - CELL_WALL) / math.sqrt(3)        # circumradius of a cell pocket
    hexes = []
    dx, dz = CELL * math.sqrt(3) / 2, CELL
    edge = 1.5 + r
    i = 0
    x = x0 + edge
    while x <= x0 + w - edge:
        z = z0 + edge + (CELL / 2 if i % 2 else 0)
        while z <= z0 + h - edge:
            if all(math.hypot(x - fx, z - (Z_FLOOR + FEED_Z)) > FEED_D / 2 + 1.8 + r for fx in FEED_X):
                # hexagon with flats facing up/down (vertex towards x), as a prism along y
                hp = Manifold.cylinder(FOUND_T, r, r, 6).rotate([-90, 0, 0])
                hexes.append(hp.translate([x, Y_FOUND + FOUND_BASE, z]))
            z += dz
        x += dx
        i += 1
    sheet -= Manifold.compose(hexes)
    for fx in FEED_X:
        sheet -= cyl_y(FEED_D, Y_FOUND - 1, Y_FOUND + FOUND_T + 1, fx, Z_FLOOR + FEED_Z)
    return sheet


def qc_cap() -> Manifold:
    """Closes an unused queen-cell hole. Sits in the hole at QC_X[0] position."""
    stem = cyl_z(CAP_STEM_D, Z_ROOF, CAGE_H, 0, 0)
    fl = cyl_z(CAP_FLANGE_D, CAGE_H, CAGE_H + CAP_FLANGE_T, 0, 0)
    cap = stem + fl
    # pry groove: under the flange, from its rim to the stem
    cap -= box(CAP_STEM_D / 2, CAP_FLANGE_D / 2 + 1, -CAP_PRY_W / 2, CAP_PRY_W / 2, CAGE_H - 0.01, CAGE_H + CAP_PRY_D)
    return cap


def qc_holder_dummy() -> Manifold:
    """Rough copy of the queen-cell holder in the photo (not printed, only for the fit check)."""
    tube = cyl_z(QC_D - 0.4, CAGE_H - QC_CELL_LEN, CAGE_H, 0, 0)
    fl = cyl_z(QC_FLANGE_D, CAGE_H, CAGE_H + 1.5, 0, 0)
    peg = cyl_z(5, CAGE_H + 1.5, CAGE_H + QC_ABOVE, 0, 0)
    return tube + fl + peg


def peg() -> Manifold:
    """Locating peg pointing forward (+y) from y = 0, with a bevelled tip."""
    straight = PEG_L - PEG_CHAMFER
    body = cyl_y(PEG_D, -0.5, straight)          # 0.5 mm into the rack wall, so it joins it
    tip = Manifold.cylinder(PEG_CHAMFER, PEG_D / 2, PEG_D / 2 - PEG_CHAMFER, SEG).rotate([-90, 0, 0]).translate([0, straight, 0])
    return body + tip


# --------------------------------------------------------------------------- #
# rack and stand (world: rack centred in x, back face at y = 0, bottom at z = 0)
# --------------------------------------------------------------------------- #
def pocket_origins():
    """(x centre, z bottom) of the 4 pockets: bottom-left, bottom-right, top-left, top-right."""
    out = []
    for row in range(2):
        for col in range(2):
            x = -RACK_W / 2 + RACK_WALL + col * (POCKET_W + RACK_WALL) + POCKET_W / 2
            z = RACK_FLOOR + row * (POCKET_H + RACK_WALL)
            out.append((x, z))
    return out


def screw_points():
    """Where the rack is screwed to the stand: middle of each bottom pocket floor."""
    return [(x, RACK_BACK + POCKET_D / 2) for x, z in pocket_origins()[:2]]


def countersunk(x, y, z_top, length):
    """Countersunk M5 hole downwards from z_top (90 degree head)."""
    head = Manifold.cylinder((M5_HEAD - M5) / 2, M5 / 2, M5_HEAD / 2, SEG).translate([x, y, z_top - (M5_HEAD - M5) / 2])
    return head + cyl_z(M5_HEAD, z_top - 0.01, z_top + 5, x, y) + cyl_z(M5, z_top - length, z_top, x, y)


def rack() -> Manifold:
    r = box(-RACK_W / 2, RACK_W / 2, 0, RACK_D, 0, RACK_H)
    pegs = []
    for x, z in pocket_origins():
        r -= box(x - POCKET_W / 2, x + POCKET_W / 2, RACK_BACK, RACK_D + 1, z, z + POCKET_H)
        cx, cz = x, z   # cage stands centred in the pocket, on its floor, touching the back wall
        for fx in FEED_X:
            r -= cyl_y(RACK_HOLE_D, -1, RACK_BACK + 1, cx + fx, cz + Z_FLOOR + FEED_Z)
        for mx in (-SOCKET_X, SOCKET_X):
            pegs.append(peg().translate([cx + mx, RACK_BACK, cz + SOCKET_Z]))
        # windows in the walls beside the cage's vents (air)
        for wx in (x - POCKET_W / 2 - RACK_WALL - 1, x + POCKET_W / 2 - 1):
            r -= box(wx, wx + RACK_WALL + 2, RACK_BACK + Y_BEE0 + 1, RACK_BACK + Y_GLASS - 1, cz + Z_FLOOR + 1, cz + Z_ROOF - 1)
    # countersunk screws through the bottom slab into the stand
    for x, y in screw_points():
        r -= countersunk(x, y, RACK_FLOOR, RACK_FLOOR + 1)
    # 2 pegs on the back wall of each pocket: they go into the sockets in the back of the cage
    return r + Manifold.compose(pegs)


def stand() -> Manifold:
    """The rack drops into the rim; underneath, a groove sits on a 2020 profile running towards the camera."""
    zt = 0.0                                   # top of the stand plate = rack bottom
    s = box(-STAND_W / 2, STAND_W / 2, STAND_Y0, STAND_Y0 + STAND_D, zt - STAND_T, zt)
    rim_in = (-RACK_W / 2 - FIT, RACK_W / 2 + FIT, -FIT, RACK_D + FIT)
    rim = box(rim_in[0] - RIM_T, rim_in[1] + RIM_T, rim_in[2] - RIM_T, rim_in[3] + RIM_T, zt - 0.01, zt + RIM_H)
    rim -= box(*rim_in, zt - 1, zt + RIM_H + 1)
    s += rim
    # groove for a 2020 profile, along y, and 2 M5 holes for T-nuts (one in front of the rack, one behind)
    s -= box(-RAIL_W / 2, RAIL_W / 2, STAND_Y0 - 1, STAND_Y0 + STAND_D + 1, zt - STAND_T - 1, zt - STAND_T + RAIL_DEPTH)
    for y in (STAND_HOLE_BACK_Y, STAND_HOLE_FRONT_Y):
        s -= cyl_z(M5, zt - STAND_T - 1, zt + 1, 0, y)
    # holes + nut traps (from underneath) for the 2 countersunk screws from the rack
    for x, y in screw_points():
        s -= cyl_z(M5, zt - STAND_T - 1, zt + 1, x, y)
        s -= Manifold.cylinder(6.0, M5_NUT / math.sqrt(3), M5_NUT / math.sqrt(3), 6).translate([x, y, zt - STAND_T - 0.01])
    # 4 recesses for stick-on rubber feet (10 mm), so it does not slide on a table
    for x in (-STAND_W / 2 + 15, STAND_W / 2 - 15):
        for y in (STAND_Y0 + 15, STAND_Y0 + STAND_D - 15):
            s -= cyl_z(10.5, zt - STAND_T - 0.01, zt - STAND_T + 0.8, x, y)
    return s


# --------------------------------------------------------------------------- #
# print orientation and export
# --------------------------------------------------------------------------- #
def on_back(m: Manifold) -> Manifold:
    """Print with the back face (y = 0) on the bed."""
    return m.rotate([90, 0, 0])


def flat_front_up(m: Manifold) -> Manifold:
    """Foundation: back on the bed, cells up."""
    return m.rotate([90, 0, 0])


PARTS = {
    # name: (builder, print orientation, how many to print, colour, note)
    "cage": (cage, on_back, "4 (+1 spare)", "white", "back wall on the bed, no supports"),
    "foundation": (foundation, flat_front_up, "4 (+1)", "white / natural", "flat, cells up, 0.12 mm layers"),
    "qc_cap": (qc_cap, lambda m: m.rotate([180, 0, 0]), "12", "white", "flat top on the bed, stem up: no supports"),
    "rack": (rack, on_back, "1", "white or black", "back wall on the bed, no supports"),
    "stand": (stand, lambda m: m, "1", "any", "as modelled (rim up)"),
}


def place_on_bed(m: Manifold) -> Manifold:
    lo, hi = np.array(m.bounding_box()[:3]), np.array(m.bounding_box()[3:])
    c = (lo + hi) / 2
    return m.translate([-c[0], -c[1], -lo[2]])


def export_parts(names=None) -> dict[str, trimesh.Trimesh]:
    STL.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, (build, orient, qty, colour, note) in PARTS.items():
        if names and name not in names:
            continue
        t = to_trimesh(place_on_bed(orient(build())))
        t.export(STL / f"{name}.stl")
        ext = t.bounds[1] - t.bounds[0]
        print(f"{name:12s} {ext[0]:6.1f} x {ext[1]:6.1f} x {ext[2]:6.1f} mm  print {qty:12s} {colour:16s} watertight={t.is_watertight}")
        out[name] = t
    return out


# --------------------------------------------------------------------------- #
# the fit check: build everything together and test it
# --------------------------------------------------------------------------- #
def assembly():
    """Every printed part in place: stand, rack (with pegs), 4 cages each with foundation and 3 caps (no glass).
    Feeder holes stay open. Returns {name: Manifold} in world coordinates."""
    parts = {"stand": stand(), "rack": rack()}
    c, g, f, cap = cage(), glass(), foundation(), qc_cap()
    for i, (x, z) in enumerate(pocket_origins(), 1):
        at = [x, RACK_BACK, z]
        parts[f"cage{i}"] = c.translate(at)
        parts[f"foundation{i}"] = f.translate(at)
        for j, qx in enumerate(QC_X, 1):
            parts[f"cap{i}.{j}"] = cap.translate([x + qx, RACK_BACK + QC_YW, z])
    return parts


def check() -> bool:
    ok = True
    lines = []

    def report(passed: bool, text: str):
        nonlocal ok
        ok &= passed
        lines.append(f"[{'OK ' if passed else 'FAIL'}] {text}")
        print(lines[-1])

    TOL = 0.5   # mm^3: touching faces give ~0; anything bigger is a real collision

    # 1. every printable part is a closed solid and fits the printer
    for name, (build, orient, *_rest) in PARTS.items():
        m = place_on_bed(orient(build()))
        t = to_trimesh(m)
        ext = t.bounds[1] - t.bounds[0]
        pieces = len(m.decompose())
        report(t.is_watertight and pieces == 1 and bool(np.all(ext <= BED - 4)),
               f"{name}: one closed solid ({pieces} piece), {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm fits the P2S bed")

    parts = assembly()

    # 2. no two parts overlap
    names = list(parts)
    bbs = {n: parts[n].bounding_box() for n in names}
    clashes = []
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            A, B = bbs[names[a]], bbs[names[b]]
            if any(A[i] > B[i + 3] or B[i] > A[i + 3] for i in range(3)):
                continue
            v = (parts[names[a]] ^ parts[names[b]]).volume()
            if v > TOL:
                clashes.append(f"{names[a]} / {names[b]}: {v:.1f} mm3")
    report(not clashes, f"all {len(names)} parts together, no part overlaps another" + ("" if not clashes else ": " + "; ".join(clashes[:8])))

    solid = union([p for n, p in parts.items()])

    # 3. feeder holes are open all the way from behind the rack, through rack + cage + foundation, into the bee room
    blocked = []
    for i, (x, z) in enumerate(pocket_origins(), 1):
        for fx in FEED_X:
            probe = cyl_y(FEED_D - 0.6, STAND_Y0 - 5, RACK_BACK + Y_BEE0 + 2, x + fx, z + Z_FLOOR + FEED_Z)
            v = (probe ^ solid).volume()
            if v > TOL:
                blocked.append(f"cage{i} x={fx:+.0f}: {v:.1f} mm3")
    report(not blocked, f"12 feeder holes open from behind the rack into the bees (a {FEED_D - 0.6:.1f} mm tube passes)" + ("" if not blocked else ": " + "; ".join(blocked)))

    # 4. a queen-cell holder fits in every top hole: not in the glass path, not against the rack ceiling
    c, g, f, holder, r = cage(), glass(), foundation(), qc_holder_dummy(), rack()
    holders = union([holder.translate([qx, QC_YW, 0]) for qx in QC_X])
    v1 = (holders ^ c).volume()
    report(v1 < TOL, f"3 queen-cell holders (flange {QC_FLANGE_D:.0f} mm, {QC_ABOVE:.0f} mm above the top) sit in the top holes without hitting the cage")
    v2 = (holders ^ f).volume()
    report(v2 < TOL and QC_Y - QC_D / 2 > 0,
           f"queen cells hang {QC_Y - QC_D / 2:.1f} mm in front of the foundation cells (foundation whole) "
           f"and {Y_GLASS - QC_YW - QC_D / 2:.1f} mm from the glass: bee room {BEE_D:.1f} mm deep")
    disc_back = QC_YW - QC_FLANGE_D / 2
    report(disc_back >= 0, f"holder discs stay on the cage top ({disc_back:.1f} mm from the back edge), clear of the rack")
    sweep = union([g.translate([dx, 0, 0]) for dx in np.arange(0, GLASS_W + 2, 2.0)])
    v3 = (sweep ^ (c + holders)).volume()
    report(v3 < TOL, "glass slides out sideways (to the right) with all 3 queen cells in place")
    v4 = (g ^ c).volume()
    report(v4 < TOL, f"glass {GLASS_W:.1f} x {GLASS_L:.1f} x {GLASS_T:.1f} mm sits in the grooves "
           f"(0.5 mm play at the ends, {GLASS_CLR:.1f} mm in thickness)")

    # 5. the foundation goes in and out through the front window (glass removed)
    fs = union([f.translate([0, dy, 0]) for dy in np.arange(0, CAGE_D + 2, 1.0)])
    v5 = (fs ^ c).volume()
    report(v5 < TOL, f"foundation {IN_W - 2 * FIT:.1f} x {IN_H - 2 * FIT:.1f} mm slides in/out through the front window")
    # the sheet has FIT play on every side: push it to each side and pass a tube through all 3 holes
    tube = FEED_D - 2 * FIT - 0.05
    hole_err = 0.0
    for dx, dz in ((0, 0), (FIT, 0), (-FIT, 0), (0, FIT), (0, -FIT)):
        fm = f.translate([dx, 0, dz])
        for fx in FEED_X:
            probe = cyl_y(tube, -1, Y_BEE0 + 1, fx, Z_FLOOR + FEED_Z)
            hole_err = max(hole_err, (probe ^ (c + fm)).volume())
    report(hole_err < TOL, f"foundation holes line up with the cage feeder holes: a {tube:.2f} mm tube passes even with the sheet pushed {FIT} mm to any side")

    # 6. a cage with 3 holders in place slides straight in and out of every pocket
    loaded = c + holders
    blocked = []
    for i, (x, z) in enumerate(pocket_origins(), 1):
        s = union([loaded.translate([x, RACK_BACK + dy, z]) for dy in np.arange(0, POCKET_D + 4, 2.0)])
        v = (s ^ r).volume()
        if v > TOL:
            blocked.append(f"pocket {i}: {v:.1f} mm3")
    report(not blocked, f"a cage with 3 queen cells slides into each pocket ({POCKET_CLR} mm each side, {HEAD_ROOM:.0f} mm over the holders)" + ("" if not blocked else ": " + "; ".join(blocked)))

    # 6b. pegs sit in the cage sockets: centred, with play, and the cage still rests against the rack wall
    play = (SOCKET_D - PEG_D) / 2
    report(0 < play <= 0.3 and PEG_L < SOCKET_T,
           f"rack pegs Ø {PEG_D} x {PEG_L} mm sit in the cage sockets Ø {SOCKET_D} x {SOCKET_T} mm "
           f"({play:.2f} mm play all round, {SOCKET_T - PEG_L:.1f} mm free at the bottom)")

    # 7. caps don't stick out more than a holder does
    cap_h = CAP_FLANGE_T
    report(cap_h <= QC_ABOVE, f"caps stick out {cap_h:.1f} mm (holders {QC_ABOVE:.0f} mm)")

    # 8. the 4 cages are separate, with a gap between rows for the queen cells
    report(POCKET_H - CAGE_H >= QC_ABOVE + 2, f"gap above each cage {POCKET_H - CAGE_H:.0f} mm, rack wall between cages {RACK_WALL:.0f} mm")

    # 9. stability on a table
    tip = math.degrees(math.atan2(STAND_BACK, RACK_H / 2))
    report(tip > 15, f"stand reaches {STAND_BACK:.0f} mm behind and {STAND_FRONT:.0f} mm in front of the rack: tips over only past ~{tip:.0f} degrees")

    write_check_files(parts, lines)
    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    return ok


COLOURS = {"stand": (120, 120, 120), "rack": (70, 70, 70), "cage": (245, 245, 245), "glass": (150, 210, 255),
           "foundation": (225, 190, 100), "cap": (90, 140, 230)}


def colour_of(name):
    for k, v in COLOURS.items():
        if name.startswith(k):
            return v
    return (200, 200, 200)


def write_check_files(parts, lines):
    CHECK.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    for n, m in parts.items():
        t = to_trimesh(m)
        t.visual.face_colors = [*colour_of(n), 140 if n.startswith("glass") else 255]
        scene.add_geometry(t, node_name=n, geom_name=n)
    scene.export(CHECK / "assembly.glb")
    to_trimesh(union(list(parts.values()))).export(CHECK / "assembly.stl")
    (CHECK / "check_report.txt").write_text("Fit check (python hardware/cages/cages.py check)\n\n" + "\n".join(lines) + "\n")
    render(parts)


def render(parts):
    """Three flat drawings of the assembly: front (what the camera sees), side section, top."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath

    def draw(ax, polys, colour, alpha=1.0, swap=None):
        verts, codes = [], []
        for p in polys:
            p = np.asarray(p)
            if len(p) < 3:
                continue
            if swap:
                p = swap(p)
            verts += list(p) + [p[0]]
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(p) - 1) + [MPath.CLOSEPOLY]
        if verts:
            ax.add_patch(PathPatch(MPath(verts, codes), fc=colour, ec="k", lw=0.3, alpha=alpha))

    def col(n):
        return np.array(colour_of(n)) / 255

    fig, axes = plt.subplots(1, 3, figsize=(20, 8), gridspec_kw={"width_ratios": [1.15, 0.8, 1.15]})
    # 1. front view, looking from the camera: cut every 0.5 mm from back to front and paint over
    #    (the front-most part wins), glass drawn last, see-through
    ax = axes[0]
    y_lo, y_hi = 0.0, RACK_D + RIM_T + 1
    for y in np.arange(y_lo, y_hi, 0.5):
        for n, m in parts.items():
            if n.startswith("glass"):
                continue
            bb = m.bounding_box()
            if not (bb[1] <= y <= bb[4]):
                continue
            polys = m.rotate([-90, 0, 0]).slice(-y).to_polygons()         # rotated: (x, z, -y)
            draw(ax, polys, col(n), 1.0)
    for n, m in parts.items():
        if n.startswith("glass"):
            draw(ax, m.rotate([-90, 0, 0]).project().to_polygons(), col(n), 0.25)
    ax.set_title("Front view (what the camera sees)")
    ax.set_xlabel("x (mm)"); ax.set_ylabel("z (mm)")

    # 2. side section through the left column, through a queen-cell hole and a feeder hole
    ax = axes[1]
    x_cut = pocket_origins()[0][0] + QC_X[0]
    for n, m in parts.items():
        polys = m.rotate([0, -90, 0]).slice(x_cut).to_polygons()         # (x', y') = (-z, y)
        draw(ax, polys, col(n), 0.9, swap=lambda p: np.c_[p[:, 1], -p[:, 0]])
    ax.set_title(f"Side section at x = {x_cut:.0f} mm\n(queen-cell caps, feeder holes)")
    ax.set_xlabel("y (mm):  back  ->  front (camera)"); ax.set_ylabel("z (mm)")

    # 3. horizontal section through the feeder holes of the bottom row
    ax = axes[2]
    z_cut = pocket_origins()[0][1] + Z_FLOOR + FEED_Z
    for n, m in parts.items():
        draw(ax, m.slice(z_cut).to_polygons(), col(n), 0.9)
    ax.set_title(f"Horizontal section at z = {z_cut:.0f} mm (bottom row, through the 6 feeder holes)\n"
                 "camera is at the top of this picture")
    ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)")

    for ax in axes:
        ax.autoscale_view()
        ax.set_aspect("equal")
        ax.grid(alpha=0.25)
    fig.suptitle("Fit check: stand + rack + 4 cages, each with comb foundation and 3 queen-cell caps (glass not shown) "
                 "(feeder holes left open)", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(CHECK / "assembly.png", dpi=110)
    plt.close(fig)


def summary():
    print(f"cage outside      {CAGE_W:.1f} x {CAGE_H:.1f} x {CAGE_D:.1f} mm (w x h x depth); inside {IN_W:.0f} x {IN_H:.0f}, "
          f"bees {BEE_D:.1f} mm deep (cell tops -> glass), {Y_GLASS - Y_FOUND:.1f} mm back wall -> glass")
    print(f"glass to order    {GLASS_W:.1f} x {GLASS_L:.1f} x {GLASS_T:.1f} mm  (x 4, + spares)")
    print(f"foundation        {IN_W - 2 * FIT:.1f} x {IN_H - 2 * FIT:.1f} x {FOUND_T:.1f} mm")
    print(f"rack              {RACK_W:.1f} x {RACK_H:.1f} x {RACK_D:.1f} mm; stand {STAND_W:.1f} x {STAND_D:.1f} mm")
    print(f"glass front face  {GLASS_FRONT_Y - STAND_HOLE_FRONT_Y:+.1f} mm from the stand's front M5 hole along the camera axis "
          f"(measure the camera distance from that hole)")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    summary()
    export_parts([a for a in args if a != "check"] or None)
    if "check" in args:
        print()
        sys.exit(0 if check() else 1)
