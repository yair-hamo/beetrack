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
    glass             1   2 mm glass, 104 x 97 mm (see GLASS_W / GLASS_L below), slides in from the top
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
from manifold3d import CrossSection, JoinType, Manifold, Mesh

# --------------------------------------------------------------------------- #
# PARAMETERS
# --------------------------------------------------------------------------- #
# cage: the room for the bees
IN_W = 100.0            # inside width
IN_H = 90.0             # inside height (minimum 90)
# (the depth of the bee room is not set here: it is made as small as the queen-cell holders allow, see below)
WALL = 5.0              # left/right/bottom walls (they hold the glass groove)
TOP_T = 5.0             # top wall (holds the queen-cell holes and the glass slot)
BACK_T = 4.0            # back wall (holds the feeder holes)

# glass cover: slides down from the TOP, through a slot in the top wall, into grooves in the left, right and
# bottom walls. Its top edge ends flush with the top of the cage. The queen-cell holders' discs (and the caps)
# then rest across the slot and hold the glass down: glass in first, holders after; to open, holders out first.
GLASS_T = 2.0           # measure your glass / perspex!
GLASS_SLOT = 3.0        # width of the glass route (grooves + top slot); 3 mm like the cages already in use
GLASS_CLR = GLASS_SLOT - GLASS_T   # play, so the glass slides freely
GROOVE = 2.5            # how deep the glass sits in the left, right and bottom walls
LIP = 2.0               # wall in front of the glass on the left, right and bottom (holds it in); open at the top

# comb foundation sheet (printed separately, lies on the inside of the back wall)
FOUND_BASE = 1.0        # the flat sheet
CELL_H = 2.0            # how far the cell walls stand up from the sheet
FOUND_T = FOUND_BASE + CELL_H
CELL = 5.4              # worker cell size, centre to centre (flat to flat)
CELL_WALL = 0.8         # cell wall thickness (2 lines of a 0.4 mm nozzle)
FIT = 0.3               # clearance around parts that go into each other
# the first layer always squashes out a little ("elephant foot"). A small 45-degree bevel on bed-face edges and
# hole mouths would help, but the cages, foundations, caps and rack are ALREADY PRINTED without it: keep 0 so the
# files stay the printed ones. (0.4 is a good value for a future reprint.)
BED_CHAMFER = 0.0
# the foundation is a press fit, so it can't fall forward: the sheet itself has a small gap to the walls, and
# round ribs on its 4 edges stand out past that gap and press into the walls (left, right, floor, roof)
FOUND_CLR = 0.15        # gap between the sheet's edges and the walls
RIB_PRESS = 0.15        # how far each rib presses into the wall. Too tight: 0.05-0.1. Still loose: 0.25.
RIB_D = 1.6             # rib diameter (runs front-to-back over the full 3 mm thickness)
RIB_LEAD = 0.8          # the back end of each rib is tapered over this length, so the sheet starts in easily

# holes
FEED_D = 10.5           # feeders: candy, water, pollen (9 mm was too small for the real feeders)
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
CAP_STEM_D = 12.6                 # as printed. For a tighter reprint: 12.7 with CAP_RIBS = 6 (press-fit ribs)
CAP_RIBS = 0
CAP_RIB_D = 1.2
CAP_PRESS = 0.15                  # how far each rib presses into the hole wall. Too tight: 0.05-0.1. Loose: 0.25.
CAP_RIB_LEAD = 1.0                # the lower end of each rib is tapered, so the cap starts into the hole easily
CAP_FLANGE_D = 18.0               # as printed (22 would cover the whole glass edge, like a holder disc)
CAP_FLANGE_T = 1.6
CAP_PRY_W, CAP_PRY_D = 4.0, 1.0   # small groove under one edge of the flange: lift the cap with a screwdriver tip

# vents (bees can't pass 1.8 mm)
VENT_W, VENT_PITCH = 1.8, 3.6   # slit height, slit-to-slit (1.8 mm bars between slits)

# locating sockets in the back of each cage (2 per cage, Ø 10.3 x 2.2 mm) and the matching pegs on the rack
SOCKET_D, SOCKET_T = 10.3, 2.2    # the sockets in the cage (first made for 10 x 2 mm magnets)
SOCKET_X, SOCKET_Z = 38.0, 80.0   # from the cage centre / from the cage bottom
PEG_D = 10.0                      # peg core on the rack: 0.15 mm gap all round in the socket
PEG_L = 2.0                       # 0.2 mm shorter than the socket is deep, so the cage still touches the rack
PEG_CHAMFER = 0.4                 # bevelled tip, guides the cage onto the pegs
# the pegs are a press fit, so a cage can't slide or fall out of its pocket: small round ribs on each peg stand
# out past the gap and press into the socket wall (same idea as the foundation ribs)
PEG_RIBS = 6                      # ribs per peg
PEG_RIB_D = 1.2
PEG_PRESS = 0.15                  # how far each rib presses into the socket wall. Too tight: 0.05-0.1. Loose: 0.25.
PEG_RIB_LEAD = 0.4                # the front end of each rib is tapered, so the cage starts onto the pegs easily

# rack: 2 x 2 pockets, each with a floor, walls on both sides, a back wall and room above for the queen cells
RACK_WALL = 4.0
RACK_BACK = 5.0
RACK_FLOOR = 6.0        # the bottom slab (the countersunk screws to the stand go through it)
POCKET_CLR = 0.5        # cage <-> pocket walls, each side
HEAD_ROOM = 4.0         # above the queen-cell holders
# the holes in the rack back wall behind the feeder holes are exactly the cage's (FEED_D, same centres)
# air windows in the rack walls: the PRINTED rack has one 88 mm window per wall (RACK_SLOT_W = 88). For a reprint,
# 8 mm slots with 3 mm bars print cleaner (the wall above a long window has to bridge it).
RACK_SLOT_W, RACK_SLOT_BAR = 88.0, 3.0

# stand: the rack drops into it; it stands on a table or bolts onto a 2020 aluminium profile
STAND_T = 6.0           # base frame height (the 2020 groove is 3 deep; the M5 nut pockets go right through)
STAND_FRONT, STAND_BACK = 60.0, 55.0     # how far the stand reaches in front of / behind the rack
RIM_H, RIM_T = 6.0, 4.0
# the stand holds the rack by itself (the 2 screws are optional): a tall cheek on each side of the rack that wraps
# round its back and front corners, braced by a wide triangular wing down to the stand's front and back edges
CHEEK_T = 6.0           # side cheeks + wings, thickness
CHEEK_H = 90.0          # how high the cheeks hold the rack (about 3/4 of the lower row of pockets)
WRAP_BACK = 20.0        # the cheeks wrap this far over the rack's back (clear of the feeder holes)
WRAP_FRONT = 3.0        # ... and this far over the front of the rack's outer walls (4 mm; the cages start at 4.5)
# the stand is a light frame, not a solid plate: beams where the loads go, open bays in between
STRUT = 7.0             # width of the wing struts (each wing is an open triangle: base, upright, diagonal)
FOOT_W = 16.0           # side beams under the wings, front to back (they carry the rubber feet)
BAR_W = 10.0            # front and back cross bars
SPINE_W = 28.0          # centre beam over the 2020 groove (20.4 mm) with the 2 M5 holes
# the rack is a press fit in the stand: vertical round ribs on the stand's inside faces (cheeks, back wraps, front
# wraps) press into the rack's outer walls. Push the rack down into the stand; it goes in firmly and stays.
STAND_PRESS = 0.2       # how far each rib presses into the rack. Too tight: 0.1. Still loose: 0.3.
STAND_RIB_D = 2.0
STAND_RIB_LEAD = 5.0    # the top of each rib is tapered, so the rack starts in easily
BOSS_D = 24.0           # solid round pad round each M5 screw under the rack
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
GLASS_X0 = -IN_W / 2 - GROOVE + 0.5                                 # 0.5 mm play at each side
GLASS_X1 = IN_W / 2 + GROOVE - 0.5
GLASS_W = GLASS_X1 - GLASS_X0                                       # glass to order (width)
GLASS_Z0 = Z_FLOOR - GROOVE + 0.5                                   # 0.5 mm above the bottom of the groove
GLASS_L = CAGE_H - GLASS_Z0                                         # glass to order (height): top flush with the cage

POCKET_W = CAGE_W + 2 * POCKET_CLR
POCKET_H = CAGE_H + QC_ABOVE + HEAD_ROOM
POCKET_D = CAGE_D + POCKET_CLR
RACK_W = 2 * POCKET_W + 3 * RACK_WALL
RACK_H = RACK_FLOOR + 2 * POCKET_H + 2 * RACK_WALL
RACK_D = RACK_BACK + POCKET_D
STAND_W = RACK_W + 2 * (FIT + CHEEK_T)
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


def mouth_y(d, y0, x=0.0, z=0.0, c=None) -> Manifold:
    """45-degree bevel at the mouth of a hole along +y whose open face is at y = y0 (the bed face)."""
    c = BED_CHAMFER if c is None else c
    if c <= 0:
        return Manifold()
    return Manifold.cylinder(c + 0.01, d / 2 + c + 0.01, d / 2 - 0.0, SEG).rotate([-90, 0, 0]).translate([x, y0 - 0.01, z])


def cyl_x(d, x0, x1, y=0.0, z=0.0, seg=SEG) -> Manifold:
    return Manifold.cylinder(x1 - x0, d / 2, d / 2, seg).rotate([0, 90, 0]).translate([x0, y, z])


def union(parts) -> Manifold:
    return Manifold.batch_boolean(list(parts), 0) if len(parts) > 1 else parts[0]   # 0 = Add


def unsupported(m: Manifold, z_levels, res=0.2, margin=12.0):
    """For a part in print orientation: at each height where a flat face points down, the overhanging area is what
    is solid just above but not just below. For every overhanging point, measure how far it is (in x-y) to the
    nearest material underneath it: half a bridge's span, or a ledge's full width. Returns [(distance, z, size)]."""
    from matplotlib.path import Path as MPath
    from scipy.ndimage import distance_transform_edt

    def raster(cs, x0, y0, nx, ny):
        polys = cs.to_polygons()
        if not polys:
            return np.zeros((ny, nx), bool)
        path = MPath.make_compound_path(*[MPath(np.vstack([p, p[:1]]), closed=True) for p in polys])
        gx, gy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * res, y0 + (np.arange(ny) + 0.5) * res)
        return path.contains_points(np.c_[gx.ravel(), gy.ravel()]).reshape(ny, nx)

    out = []
    for z in z_levels:
        below = m.slice(z - 0.1)
        over = m.slice(z + 0.1) - below
        for piece in over.decompose():
            if piece.area() < 0.3:
                continue
            bx0, by0, bx1, by1 = piece.bounds()
            x0, y0 = bx0 - margin, by0 - margin
            nx, ny = int((bx1 - bx0 + 2 * margin) / res) + 1, int((by1 - by0 + 2 * margin) / res) + 1
            face = raster(piece, x0, y0, nx, ny)
            if not face.any():
                continue
            sup = raster(below, x0, y0, nx, ny)
            d = distance_transform_edt(~sup) * res if sup.any() else np.full(sup.shape, 1e9)
            out.append((float(d[face].max()), z, (bx1 - bx0, by1 - by0)))
    return out


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
    # glass route: grooves in the left, right and bottom walls, and straight up through the top wall
    gw = IN_W / 2 + GROOVE
    body -= box(-gw, gw, Y_GLASS, Y_LIP, Z_FLOOR - GROOVE, CAGE_H + 1)
    # front window, open to the top (the lip holds the glass at the sides and the bottom; nothing bridges over
    # the slot, so the cage prints without supports; push the glass up with a thumb on its face)
    body -= box(-IN_W / 2, IN_W / 2, Y_LIP - 0.01, CAGE_D + 1, Z_FLOOR, CAGE_H + 1)
    # feeder holes: back wall, low
    for x in FEED_X:
        body -= cyl_y(FEED_D, -1, Y_FOUND + 0.01, x, Z_FLOOR + FEED_Z)
        body -= mouth_y(FEED_D, 0, x, Z_FLOOR + FEED_Z)
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
        body -= mouth_y(SOCKET_D, 0, x, SOCKET_Z)
    return body


def glass() -> Manifold:
    y0 = Y_GLASS + GLASS_CLR / 2
    return box(GLASS_X0, GLASS_X1, y0, y0 + GLASS_T, GLASS_Z0, GLASS_Z0 + GLASS_L)


def foundation(ribs: bool = True) -> Manifold:
    """Sheet with hexagonal worker cells; 3 holes line up with the feeder holes. Lies flat on the inside of the back
    wall, held by press-fit ribs on its edges."""
    w, h = IN_W - 2 * FOUND_CLR, IN_H - 2 * FOUND_CLR
    x0, z0 = -w / 2, Z_FLOOR + FOUND_CLR
    c = BED_CHAMFER
    sheet = box(x0, x0 + w, Y_FOUND, Y_FOUND + FOUND_T, z0, z0 + h) if c <= 0 else union([box(x0, x0 + w, Y_FOUND + c, Y_FOUND + FOUND_T, z0, z0 + h),
                   Manifold.hull(union([box(x0 + c, x0 + w - c, Y_FOUND, Y_FOUND + 0.01, z0 + c, z0 + h - c),
                                        box(x0, x0 + w, Y_FOUND + c, Y_FOUND + c + 0.01, z0, z0 + h)]))])
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
    if ribs:
        sheet = union([sheet, foundation_ribs()])
    for fx in FEED_X:
        sheet -= cyl_y(FEED_D, Y_FOUND - 1, Y_FOUND + FOUND_T + 1, fx, Z_FLOOR + FEED_Z)
        sheet -= mouth_y(FEED_D, Y_FOUND, fx, Z_FLOOR + FEED_Z)
    return sheet


def foundation_ribs() -> Manifold:
    """Round ribs along y on the 4 edges of the sheet; each stands RIB_PRESS past the wall it presses on."""
    rr = RIB_D / 2
    inset = rr - RIB_PRESS                        # rib centre, this far inside the wall line
    def rib(x, z):
        lead = Manifold.cylinder(RIB_LEAD, rr - 0.3, rr, SEG)
        body = Manifold.cylinder(FOUND_T - RIB_LEAD, rr, rr, SEG).translate([0, 0, RIB_LEAD])
        return union([lead, body]).rotate([-90, 0, 0]).translate([x, Y_FOUND, z])
    zs = [Z_FLOOR + IN_H * k for k in (0.25, 0.5, 0.75)]
    xs = (-40.0, -15.0, 15.0, 40.0)               # clear of the feeder holes at -30 / 0 / 30
    out = [rib(sx * (IN_W / 2 - inset), z) for z in zs for sx in (-1, 1)]
    out += [rib(x, Z_FLOOR + inset) for x in xs] + [rib(x, Z_ROOF - inset) for x in xs]
    return Manifold.compose(out)


def pressed(f: Manifold) -> Manifold:
    """The foundation as it sits in the cage: the rib tips squashed flat against the walls."""
    return f ^ box(-IN_W / 2, IN_W / 2, Y_FOUND - 1, Y_FOUND + FOUND_T + 1, Z_FLOOR, Z_ROOF)


def qc_cap() -> Manifold:
    """Closes an unused queen-cell hole. Sits in the hole at QC_X[0] position."""
    stem = cyl_z(CAP_STEM_D, Z_ROOF, CAGE_H, 0, 0)
    fl = cyl_z(CAP_FLANGE_D, CAGE_H, CAGE_H + CAP_FLANGE_T, 0, 0)
    cap = union([stem, fl, cap_ribs()])
    # pry groove: under the flange, from its rim to the stem
    cap -= box(CAP_STEM_D / 2, CAP_FLANGE_D / 2 + 1, -CAP_PRY_W / 2, CAP_PRY_W / 2, CAGE_H - 0.01, CAGE_H + CAP_PRY_D)
    return cap


def cap_ribs() -> Manifold:
    """Round vertical ribs around the cap stem (cap at the origin); each reaches CAP_PRESS past the hole wall."""
    if CAP_RIBS == 0:
        return Manifold()
    rr = CAP_RIB_D / 2
    rc = QC_D / 2 + CAP_PRESS - rr
    stem_l = CAGE_H - Z_ROOF
    one = union([Manifold.cylinder(CAP_RIB_LEAD, rr - 0.35, rr, 24),
                 Manifold.cylinder(stem_l - CAP_RIB_LEAD + 0.5, rr, rr, 24).translate([0, 0, CAP_RIB_LEAD])])
    one = one.translate([0, 0, Z_ROOF])
    return Manifold.compose([one.translate([rc * math.cos(a), rc * math.sin(a), 0])
                             for a in (2 * math.pi * (k + 0.5) / CAP_RIBS for k in range(CAP_RIBS))])


def pressed_cap() -> Manifold:
    """The cap as it sits in its hole: the rib tips squashed flat against the hole wall."""
    ring = cyl_z(QC_D + 2, Z_ROOF - 1, CAGE_H, 0, 0) - cyl_z(QC_D, Z_ROOF - 2, CAGE_H + 1, 0, 0)
    return qc_cap() - ring


def qc_holder_dummy() -> Manifold:
    """Rough copy of the queen-cell holder in the photo (not printed, only for the fit check)."""
    tube = cyl_z(QC_D - 0.4, CAGE_H - QC_CELL_LEN, CAGE_H, 0, 0)
    fl = cyl_z(QC_FLANGE_D, CAGE_H, CAGE_H + 1.5, 0, 0)
    peg = cyl_z(5, CAGE_H + 1.5, CAGE_H + QC_ABOVE, 0, 0)
    return tube + fl + peg


def peg(ribs: bool = True) -> Manifold:
    """Locating peg pointing forward (+y) from y = 0, with a bevelled tip and press-fit ribs."""
    straight = PEG_L - PEG_CHAMFER
    body = cyl_y(PEG_D, -0.5, straight)          # 0.5 mm into the rack wall, so it joins it
    tip = Manifold.cylinder(PEG_CHAMFER, PEG_D / 2, PEG_D / 2 - PEG_CHAMFER, SEG).rotate([-90, 0, 0]).translate([0, straight, 0])
    out = [body, tip]
    if ribs:
        out.append(peg_ribs())
    return union(out)


def peg_ribs() -> Manifold:
    """Round ribs along y around a peg at the origin; each reaches PEG_PRESS past the socket wall."""
    rr = PEG_RIB_D / 2
    rc = SOCKET_D / 2 + PEG_PRESS - rr            # rib centre radius
    full = PEG_L - PEG_RIB_LEAD
    one = union([Manifold.cylinder(full + 0.5, rr, rr, 24),
                 Manifold.cylinder(PEG_RIB_LEAD, rr, rr - 0.35, 24).translate([0, 0, full + 0.5])])
    one = one.rotate([-90, 0, 0]).translate([0, -0.5, 0])
    ribs = [one.translate([rc * math.cos(a), 0, rc * math.sin(a)])
            for a in (2 * math.pi * k / PEG_RIBS for k in range(PEG_RIBS))]
    return Manifold.compose(ribs)


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


def rack(peg_ribs_on: bool = True) -> Manifold:
    r = box(-RACK_W / 2, RACK_W / 2, 0, RACK_D, 0, RACK_H)
    pegs = []
    for x, z in pocket_origins():
        r -= box(x - POCKET_W / 2, x + POCKET_W / 2, RACK_BACK, RACK_D + 1, z, z + POCKET_H)
        cx, cz = x, z   # cage stands centred in the pocket, on its floor, touching the back wall
        for fx in FEED_X:
            r -= cyl_y(FEED_D, -1, RACK_BACK + 1, cx + fx, cz + Z_FLOOR + FEED_Z)
            r -= mouth_y(FEED_D, 0, cx + fx, cz + Z_FLOOR + FEED_Z)
        for mx in (-SOCKET_X, SOCKET_X):
            pegs.append(peg(peg_ribs_on).translate([cx + mx, RACK_BACK, cz + SOCKET_Z]))
        # windows in the walls beside the cage's vents (air): short slots with bars between them, because the rack
        # prints on its back and the wall above each slot has to bridge it (one 88 mm window would sag)
        for wx in (x - POCKET_W / 2 - RACK_WALL - 1, x + POCKET_W / 2 - 1):
            z = cz + Z_FLOOR + 1
            while z + RACK_SLOT_W <= cz + Z_ROOF - 1 + 0.01:
                r -= box(wx, wx + RACK_WALL + 2, RACK_BACK + Y_BEE0 + 1, RACK_BACK + Y_GLASS - 1, z, z + RACK_SLOT_W)
                z += RACK_SLOT_W + RACK_SLOT_BAR
    # countersunk screws through the bottom slab into the stand
    for x, y in screw_points():
        r -= countersunk(x, y, RACK_FLOOR, RACK_FLOOR + 1)
    # 2 pegs on the back wall of each pocket: they go into the sockets in the back of the cage
    return r + Manifold.compose(pegs)


def stand(ribs: bool = True) -> Manifold:
    """The rack drops into the rim and is held by the cheeks; underneath, a groove sits on a 2020 profile.
    Built as a light frame: beams and open triangles instead of solid plates."""
    zt = 0.0                                   # top of the stand frame = rack bottom
    z0 = zt - STAND_T
    rim_in = (-RACK_W / 2 - FIT, RACK_W / 2 + FIT, -FIT, RACK_D + FIT)
    yb, yf = rim_in[2] - RIM_T, rim_in[3] + RIM_T          # back / front of the rim
    Y1 = STAND_Y0 + STAND_D
    W2 = STAND_W / 2
    # --- base frame -----------------------------------------------------------------------------------------
    beams = [
        box(-W2, -W2 + FOOT_W, STAND_Y0, Y1, z0, zt), box(W2 - FOOT_W, W2, STAND_Y0, Y1, z0, zt),   # side feet
        box(-W2, W2, STAND_Y0, STAND_Y0 + BAR_W, z0, zt), box(-W2, W2, Y1 - BAR_W, Y1, z0, zt),     # cross bars
        box(-SPINE_W / 2, SPINE_W / 2, STAND_Y0, Y1, z0, zt),                  # spine over the rail groove
    ]
    # no plate under the rack: its own 6 mm floor spans between the side feet, the spine and the 2 screw pads
    s = union(beams + [cyl_z(BOSS_D, z0, zt, x, y) for x, y in screw_points()]
              + [box(x - 5, x + 5, yb, yf, z0, zt) for x, y in screw_points()])   # pads tied to the rim
    # rim round the rack, from the table up (it is also the front and back beam under the rack)
    rim = box(rim_in[0] - RIM_T, rim_in[1] + RIM_T, yb, yf, z0, zt + RIM_H)
    rim -= box(*rim_in, zt, zt + RIM_H + 1)
    rim -= box(rim_in[0] + 0.01, rim_in[1] - 0.01, rim_in[2], rim_in[3], z0 - 1, zt + 0.01)
    s = union([s, rim])
    # --- cheeks: solid beside the rack, open triangles (base, upright, diagonal) in front of and behind it ------
    def side_tri(pts):
        return CrossSection([pts])

    def to_world(cs, xa, xb):
        """Extrude a y-z cross-section over x = xa..xb."""
        m = cs.extrude(xb - xa)                                # (u=y, v=z, w=x)
        return m.transform([[0, 0, 1, xa], [1, 0, 0, 0], [0, 1, 0, 0]])

    for sx in (-1, 1):
        xa, xb = sorted((sx * rim_in[1], sx * (rim_in[1] + CHEEK_T)))
        # (the pieces overlap a little instead of just touching, so the mesh stays clean)
        za, ztop = zt - 1.0, zt + CHEEK_H - 4.0
        tri_b = [(STAND_Y0, za), (yb + 1.0, za), (yb + 1.0, ztop)]
        tri_f = [(yf - 1.0, za), (Y1, za), (yf - 1.0, ztop)]
        wing = to_world(CrossSection([[(yb, za), (yf, za), (yf, zt + CHEEK_H), (yb, zt + CHEEK_H)]]), xa, xb)
        for tri in (tri_b, tri_f):
            cs = CrossSection([tri])
            hole = cs.offset(-STRUT, JoinType.Miter, 6.0)
            wing = union([wing, to_world(cs - hole, xa, xb)])
        # beside the rack the cheek is a frame too: a post at the back, a post at the front, a bar on top. The big
        # opening also lets air reach the rack's side windows; its top is an 18 mm bridge.
        wing -= box(xa - 1, xb + 1, rim_in[2] + 7, rim_in[2] + 25, zt + 10, zt + CHEEK_H - 8)
        xw0, xw1 = sorted((sx * rim_in[1], sx * (rim_in[1] - WRAP_BACK)))
        back = box(xw0, xw1, yb + 0.5, rim_in[2], zt - 0.01, zt + CHEEK_H - 0.5)   # not flush with the cheek faces
        xf0, xf1 = sorted((sx * rim_in[1], sx * (rim_in[1] - WRAP_FRONT - FIT)))
        front = box(xf0, xf1, rim_in[3], yf - 0.5, zt - 0.01, zt + CHEEK_H - 0.5)
        s = union([s, wing, back, front])
    if ribs:
        s = union([s, stand_ribs()])
    # --- holes ------------------------------------------------------------------------------------------------
    # groove for a 2020 profile, along y, and 2 M5 holes for T-nuts (one in front of the rack, one behind)
    s -= box(-RAIL_W / 2, RAIL_W / 2, STAND_Y0 - 1, Y1 + 1, z0 - 1, z0 + RAIL_DEPTH)
    for y in (STAND_HOLE_BACK_Y, STAND_HOLE_FRONT_Y):
        s -= cyl_z(M5, z0 - 1, zt + 1, 0, y)
    # holes + nut traps (from underneath) for the 2 optional countersunk screws from the rack
    for x, y in screw_points():
        s -= cyl_z(M5, z0 - 1, zt + 1, x, y)
        s -= Manifold.cylinder(STAND_T - 2.0, M5_NUT / math.sqrt(3), M5_NUT / math.sqrt(3), 6).translate([x, y, z0 - 0.01])
    # 4 recesses for stick-on rubber feet (10 mm), in the corners, so it does not slide on a table
    for x in (-W2 + FOOT_W / 2, W2 - FOOT_W / 2):
        for y in (STAND_Y0 + BAR_W / 2 + 1, Y1 - BAR_W / 2 - 1):
            s -= cyl_z(10.5, z0 - 0.01, z0 + 0.8, x, y)
    return s


def stand_ribs() -> Manifold:
    """Vertical ribs on the stand's inside faces, each reaching STAND_PRESS into the rack's outer walls.
    4 on each cheek (side), 2 on each back wrap and 1 on each front wrap (front-back): 14 in all."""
    rr = STAND_RIB_D / 2
    h = CHEEK_H - 1.0                                  # from the stand top (z = 0) up the cheeks
    def rib(x, y):
        body = Manifold.cylinder(h - STAND_RIB_LEAD, rr, rr, 24)
        lead = Manifold.cylinder(STAND_RIB_LEAD, rr, rr - 0.6, 24).translate([0, 0, h - STAND_RIB_LEAD])
        return union([body, lead]).translate([x, y, 0.0])
    # rib centres: each rib sits on a stand face (FIT outside the rack) and its tip reaches STAND_PRESS into the rack
    xs = RACK_W / 2 - STAND_PRESS + rr                 # sides
    yb = STAND_PRESS - rr                              # back (the rack's back face is y = 0)
    yf = RACK_D - STAND_PRESS + rr                     # front
    out = []
    for sx in (-1, 1):
        out += [rib(sx * xs, y) for y in (2.0, 4.5, 27.5, 30.0)]           # on the cheek posts, beside the opening
        out += [rib(sx * (RACK_W / 2 - x), yb) for x in (6.0, 15.0)]       # on the back wrap (20 mm wide)
        out += [rib(sx * (RACK_W / 2 - 1.5), yf)]                          # on the front wrap (3 mm wide)
    return Manifold.compose(out)


def pressed_stand() -> Manifold:
    """The stand with the rack in place: the rib tips squashed flat against the rack."""
    return stand() - box(-RACK_W / 2, RACK_W / 2, 0, RACK_D, 0, RACK_H)


# --------------------------------------------------------------------------- #
# print orientation and export
# --------------------------------------------------------------------------- #
def on_back(m: Manifold) -> Manifold:
    """Print with the back face (y = 0) on the bed."""
    return m.rotate([90, 0, 0])


def flat_front_up(m: Manifold) -> Manifold:
    """Foundation: back on the bed, cells up."""
    return m.rotate([90, 0, 0])


# these parts are ALREADY PRINTED: their STL files must never change. The check compares each file with the
# fingerprint (SHA-256) of the file that was printed and fails if it differs. Only the stand is still to print.
ALREADY_PRINTED = {
    "cage": "3bf847dfec9a7a50c2cfd2b7a5c813ecd3541c8cc1cadd8961fff981cb4ed479",
    "foundation": "4bfbb8d897c85552aae4b3d16b2e441c379d4f3e396ce2f61fca86b968a01c40",
    "qc_cap": "9917f7497d16a6001086cfc423ea3edb54d1ab641558b64adb07c74ba56f0f67",
    "rack": "def6cc5c27a6e559f92e0a8be988f1c07de6f301302368bd90ddc44d1d29e17e",
}

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
    c, g, f, cap = cage(), glass(), foundation(), pressed_cap()
    squash = union([cyl_y(SOCKET_D + 2 * PEG_PRESS + 0.2, RACK_BACK - 0.01, RACK_BACK + SOCKET_T, x + mx, z + SOCKET_Z)
                    - cyl_y(SOCKET_D, RACK_BACK - 1, RACK_BACK + SOCKET_T + 1, x + mx, z + SOCKET_Z)
                    for x, z in pocket_origins() for mx in (-SOCKET_X, SOCKET_X)])
    parts = {"stand": pressed_stand(), "rack": rack() - squash}   # rib tips squashed into the socket walls, as when fitted
    for i, (x, z) in enumerate(pocket_origins(), 1):
        at = [x, RACK_BACK, z]
        parts[f"cage{i}"] = c.translate(at)
        parts[f"foundation{i}"] = pressed(f).translate(at)   # ribs squashed, as in the cage
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

    MAX_BRIDGE = 21.0   # longest flat bridge PETG prints cleanly (mm); the stand's 20.4 mm rail groove is the longest
    TOL = 0.5   # mm^3: touching faces give ~0; anything bigger is a real collision

    # 1. every printable part is a closed solid and fits the printer
    #    (read back from the STL files that will be printed, not rebuilt)
    import hashlib
    changed = [n for n, h in ALREADY_PRINTED.items() if hashlib.sha256((STL / f"{n}.stl").read_bytes()).hexdigest() != h]
    report(not changed, f"already-printed parts unchanged ({', '.join(ALREADY_PRINTED)}.stl identical to the printed files)"
           + ("" if not changed else ": CHANGED: " + ", ".join(changed)))
    for name in PARTS:
        t = trimesh.load(STL / f"{name}.stl")
        ext = t.bounds[1] - t.bounds[0]
        pieces = len(t.split(only_watertight=False))
        report(t.is_watertight and pieces == 1 and bool(np.all(ext <= BED - 4)),
               f"{name}.stl: one closed solid ({pieces} piece), {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm fits the P2S bed")
        # printable without supports: every flat face pointing down (above the bed) must be a short bridge
        down = (t.face_normals[:, 2] < -0.95) & (t.triangles_center[:, 2] > 0.05)
        levels = sorted(set(np.round(t.triangles_center[down, 2], 2)))
        mf = Manifold(Mesh(vert_properties=np.asarray(t.vertices, np.float32), tri_verts=np.asarray(t.faces, np.uint32)))
        spans = unsupported(mf, levels)
        worst = max(spans, default=(0.0, 0.0, (0, 0)))
        bad = [sp for sp in spans if sp[0] > MAX_BRIDGE / 2]
        ledges = sorted({round(sp[0], 1) for sp in spans if 1.5 < sp[0] <= MAX_BRIDGE / 2}, reverse=True)
        if bad and name in ALREADY_PRINTED:
            lines.append(f"[INFO] {name}.stl is already printed; for a reprint note: " + "; ".join(
                f"{d:.1f} mm from support at height {z:.1f} ({sz[0]:.0f} x {sz[1]:.0f} mm)" for d, z, sz in bad[:3]))
            print(lines[-1])
            continue
        report(not bad, f"{name}.stl prints without supports: no point of any overhang is more than {worst[0]:.1f} mm from "
               f"material below it (limit {MAX_BRIDGE / 2:.1f}: a {MAX_BRIDGE:.0f} mm bridge)"
               + (f"; widest ledges/half-bridges {', '.join(f'{v:.1f}' for v in ledges[:4])} mm" if ledges else "")
               + ("" if not bad else ": too far: " + "; ".join(f"{d:.1f} mm at height {z:.1f} ({sz[0]:.0f} x {sz[1]:.0f} mm)" for d, z, sz in bad[:5])))

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
            probe = cyl_y(FEED_D - 0.05, STAND_Y0 - 5, RACK_BACK + Y_BEE0 + 2, x + fx, z + Z_FLOOR + FEED_Z)
            v = (probe ^ solid).volume()
            if v > TOL:
                blocked.append(f"cage{i} x={fx:+.0f}: {v:.1f} mm3")
    report(not blocked, f"12 feeder holes open from behind the rack into the bees (a {FEED_D - 0.05:.2f} mm tube passes straight through rack, cage and foundation)" + ("" if not blocked else ": " + "; ".join(blocked)))

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
    sweep = union([g.translate([0, 0, dz]) for dz in np.arange(0, GLASS_L + 2, 2.0)])
    v3 = (sweep ^ c).volume()
    report(v3 < TOL, "glass slides straight up and out of the top (once the queen-cell holders / caps are out)")
    caps = union([qc_cap().translate([qx, QC_YW, 0]) for qx in QC_X])
    lift = g.translate([0, 0, 0.5])
    held_h = (lift ^ holders).volume() > TOL
    held_c = (lift ^ caps).volume() > TOL
    report(held_h and held_c, "with holders or caps in place the glass is held down: their discs rest across the slot")
    v4 = (g ^ (c + holders)).volume() + (g ^ caps).volume()
    report(v4 < TOL, f"glass {GLASS_W:.1f} x {GLASS_L:.1f} x {GLASS_T:.1f} mm sits in the grooves, top flush with the cage "
           f"(0.5 mm play at each side and the bottom, {GLASS_CLR:.1f} mm in thickness)")

    # 5. the foundation is a press fit: ribs press into the walls, nothing else touches; it goes in and out
    #    through the front window (glass removed)
    f0 = foundation(ribs=False)
    v_body = (f0 ^ c).volume()
    v_ribs = (f ^ c).volume()
    v_other = ((f ^ c) - foundation_ribs()).volume()
    press = []
    for d, probe in (("left", box(-IN_W / 2 - 1, -IN_W / 2, Y_FOUND, Y_BEE0, Z_FLOOR, Z_ROOF)),
                     ("right", box(IN_W / 2, IN_W / 2 + 1, Y_FOUND, Y_BEE0, Z_FLOOR, Z_ROOF)),
                     ("floor", box(-IN_W / 2, IN_W / 2, Y_FOUND, Y_BEE0, Z_FLOOR - 1, Z_FLOOR)),
                     ("roof", box(-IN_W / 2, IN_W / 2, Y_FOUND, Y_BEE0, Z_ROOF, Z_ROOF + 1))):
        bb = (f ^ probe).bounding_box()
        depth = {"left": -IN_W / 2 - bb[0], "right": bb[3] - IN_W / 2, "floor": Z_FLOOR - bb[2], "roof": bb[5] - Z_ROOF}[d]
        press.append((d, depth))
    press_ok = all(abs(dp - RIB_PRESS) < 0.02 for _, dp in press)
    report(v_body < TOL and v_ribs > TOL and v_other < TOL and press_ok,
           f"foundation is a press fit: sheet {IN_W - 2 * FOUND_CLR:.1f} x {IN_H - 2 * FOUND_CLR:.1f} mm ({FOUND_CLR} mm gap), "
           f"{len(foundation_ribs().decompose())} ribs press {RIB_PRESS} mm into the "
           + ", ".join(f"{d}" for d, _ in press) + "; only the ribs touch the cage")
    fs = union([f.translate([0, dy, 0]) for dy in np.arange(0, CAGE_D + 2, 1.0)])
    band = box(-IN_W / 2 - RIB_PRESS - 0.01, IN_W / 2 + RIB_PRESS + 0.01, -1, CAGE_D + 5,
               Z_FLOOR - RIB_PRESS - 0.01, Z_ROOF + RIB_PRESS + 0.01)
    v5 = ((fs ^ c) - band).volume()
    v5b = (union([f0.translate([0, dy, 0]) for dy in np.arange(0, CAGE_D + 2, 1.0)]) ^ c).volume()
    report(v5 < TOL and v5b < TOL, "foundation slides in/out through the front window; along the way only the rib tips rub the walls")
    # the foundation's feeder holes are exactly the cage's: same diameter, same centres (the ribs centre the sheet).
    # Measured from the real geometry: a cut through the foundation sheet and one through the cage's back wall.
    def holes_at(m, y):
        """{feeder x: (diameter from area, centre x, centre z)} of the round holes in a cut at depth y."""
        out = {}
        for poly in m.rotate([90, 0, 0]).slice(y).to_polygons():     # rotated so y -> height; 2D = (x, -z)
            p = np.asarray(poly)
            x, yy = p[:, 0], p[:, 1]
            x1, y1 = np.roll(x, -1), np.roll(yy, -1)
            cr = x * y1 - x1 * yy
            area = cr.sum() / 2
            cx, cz = ((x + x1) * cr).sum() / (6 * area), -((yy + y1) * cr).sum() / (6 * area)
            for fx in FEED_X:
                if abs(cx - fx) < 2 and abs(cz - (Z_FLOOR + FEED_Z)) < 2 and np.ptp(x) < FEED_D + 3:
                    out[fx] = (2 * math.sqrt(abs(area) / math.pi), cx, cz)
        return out
    hf = holes_at(pressed(f), Y_FOUND + FOUND_BASE / 2)
    hc = holes_at(c, BACK_T / 2)
    same = len(hf) == len(hc) == len(FEED_X) and all(
        abs(hf[x][0] - hc[x][0]) < 0.01 and math.hypot(hf[x][1] - hc[x][1], hf[x][2] - hc[x][2]) < 0.01 for x in FEED_X)
    detail = "; ".join(f"x={x:+.0f}: foundation Ø {hf[x][0]:.2f} / cage Ø {hc[x][0]:.2f}, centres {math.hypot(hf[x][1] - hc[x][1], hf[x][2] - hc[x][2]):.2f} mm apart"
                       for x in FEED_X if x in hf and x in hc)
    report(same, f"foundation feeder holes are exactly the cage's: Ø {FEED_D:.1f} mm, same centres ({detail})")
    # the ribs can squash a little unevenly: push the sheet FOUND_CLR to each side and pass a tube through all 3 holes
    tube = FEED_D - 2 * FOUND_CLR - 0.05
    hole_err = 0.0
    for dx, dz in ((0, 0), (FOUND_CLR, 0), (-FOUND_CLR, 0), (0, FOUND_CLR), (0, -FOUND_CLR)):
        fm = f0.translate([dx, 0, dz])
        for fx in FEED_X:
            probe = cyl_y(tube, -1, Y_BEE0 + 1, fx, Z_FLOOR + FEED_Z)
            hole_err = max(hole_err, (probe ^ (c + fm)).volume())
    report(hole_err < TOL, f"even if the ribs squash unevenly and the sheet sits {FOUND_CLR} mm off to any side, a {tube:.2f} mm tube passes all 3 holes")

    # 6. a cage with 3 holders in place slides straight in and out of every pocket
    loaded = c + holders
    r0 = rack(peg_ribs_on=False)
    blocked = []
    for i, (x, z) in enumerate(pocket_origins(), 1):
        s = union([loaded.translate([x, RACK_BACK + dy, z]) for dy in np.arange(0, POCKET_D + 4, 2.0)])
        v = (s ^ r0).volume()
        if v > TOL:
            blocked.append(f"pocket {i}: {v:.1f} mm3")
    report(not blocked, f"a cage with 3 queen cells slides into each pocket ({POCKET_CLR} mm each side, {HEAD_ROOM:.0f} mm over the holders)" + ("" if not blocked else ": " + "; ".join(blocked)))

    # 6b. the pegs are a press fit in the cage sockets: only the rib tips touch, each PEG_PRESS into the socket wall,
    #     so the cage can't slide or fall out of its pocket; the cage still rests against the rack's back wall
    cages_w = union([c.translate([x, RACK_BACK, z]) for x, z in pocket_origins()])
    v_core = (r0 ^ cages_w).volume()
    v_ribs = (r ^ cages_w).volume()
    pk = peg()
    bb = pk.bounding_box()
    reach = (bb[3] - bb[0]) / 2                     # a rib points along +x / -x
    press = reach - SOCKET_D / 2
    ring_out = union([cyl_y(SOCKET_D + 2 * PEG_PRESS + 0.05, RACK_BACK - 1, RACK_BACK + SOCKET_T + 1, x + mx, z + SOCKET_Z)
                      for x, z in pocket_origins() for mx in (-SOCKET_X, SOCKET_X)])
    v_outside = ((r ^ cages_w) - ring_out).volume()
    report(v_core < TOL and v_ribs > TOL and v_outside < TOL and abs(press - PEG_PRESS) < 0.02 and PEG_L < SOCKET_T,
           f"rack pegs are a press fit: core Ø {PEG_D} ({(SOCKET_D - PEG_D) / 2:.2f} mm gap), {PEG_RIBS} ribs per peg press "
           f"{press:.2f} mm into the Ø {SOCKET_D} socket wall; only the ribs touch; {SOCKET_T - PEG_L:.1f} mm free at the "
           f"bottom so the cage rests on the rack's back wall: the cage can't slide out on its own")

    # 6c. the rack's holes behind the feeders are exactly the cage's: same diameter, same centres
    rows = []
    same_r = True
    for i, (x, z) in enumerate(pocket_origins(), 1):
        hr = holes_at(r.translate([-x, -RACK_BACK, -z]), -RACK_BACK / 2)
        for fx in FEED_X:
            ok_h = fx in hr and fx in hc and abs(hr[fx][0] - hc[fx][0]) < 0.01 and \
                math.hypot(hr[fx][1] - hc[fx][1], hr[fx][2] - hc[fx][2]) < 0.01
            same_r &= ok_h
            if not ok_h:
                rows.append(f"cage{i} x={fx:+.0f}: " + (f"rack Ø {hr[fx][0]:.2f}" if fx in hr else "no hole"))
    report(same_r, f"rack holes behind all 12 feeder holes are exactly the cage's: Ø {FEED_D:.1f} mm, same centres"
           + ("" if same_r else ": " + "; ".join(rows)))

    # 7. caps don't stick out more than a holder does
    # 7a. the caps are a press fit in the queen-cell holes: only the rib tips touch, CAP_PRESS into the hole wall
    cap0 = qc_cap() - cap_ribs()
    one_hole = [(qx, QC_YW) for qx in QC_X]
    v_core = sum((cap0.translate([qx, qy, 0]) ^ c).volume() for qx, qy in one_hole)
    v_rib = sum((qc_cap().translate([qx, qy, 0]) ^ c).volume() for qx, qy in one_hole)
    v_out = sum(((qc_cap().translate([qx, qy, 0]) ^ c) - cyl_z(QC_D + 2 * CAP_PRESS + 0.05, Z_ROOF - 1, CAGE_H + 1, qx, qy)).volume()
                for qx, qy in one_hole)
    bb = cap_ribs().bounding_box()
    reach = max(-bb[0], bb[3], -bb[1], bb[4])
    cap_press = reach - QC_D / 2
    # ribs sit at 30, 90, 150 ... degrees: the bounding box sees the ones at 90/270 exactly
    if CAP_RIBS == 0:
        report(v_core < TOL, f"caps (as printed): plain stem Ø {CAP_STEM_D} in the Ø {QC_D:.0f} hole, "
               f"{(QC_D - CAP_STEM_D) / 2:.2f} mm play all round")
    else:
      report(v_core < TOL and v_rib > TOL and v_out < TOL and abs(cap_press - CAP_PRESS) < 0.02,
           f"caps are a press fit: stem core Ø {CAP_STEM_D} ({(QC_D - CAP_STEM_D) / 2:.2f} mm gap), {CAP_RIBS} ribs press "
           f"{cap_press:.2f} mm into the Ø {QC_D:.0f} hole; only the ribs touch")
    cap_h = CAP_FLANGE_T
    report(cap_h <= QC_ABOVE, f"caps stick out {cap_h:.1f} mm (holders {QC_ABOVE:.0f} mm)")

    # 8. the 4 cages are separate, with a gap between rows for the queen cells
    report(POCKET_H - CAGE_H >= QC_ABOVE + 2, f"gap above each cage {POCKET_H - CAGE_H:.0f} mm, rack wall between cages {RACK_WALL:.0f} mm")

    # 9. stability on a table
    tip = math.degrees(math.atan2(STAND_BACK, RACK_H / 2))
    report(tip > 15, f"stand reaches {STAND_BACK:.0f} mm behind and {STAND_FRONT:.0f} mm in front of the rack: tips over only past ~{tip:.0f} degrees")

    # 9b. the stand holds the rack without the screws: the rack can't tilt or slide in any direction, only lift out
    st, rk = stand(ribs=False), parts["rack"]          # the walls alone (ribs tested below)
    def tilt(m, axis, pivot, deg):
        rot = [deg, 0, 0] if axis == "x" else [0, deg, 0]
        return m.translate([-pivot[0], -pivot[1], -pivot[2]]).rotate(rot).translate(list(pivot))
    moves = {
        "tilt forward 2°": tilt(rk, "x", (0, RACK_D, 0), -2),
        "tilt backward 2°": tilt(rk, "x", (0, 0, 0), 2),
        "tilt left 2°": tilt(rk, "y", (-RACK_W / 2, 0, 0), -2),
        "tilt right 2°": tilt(rk, "y", (RACK_W / 2, 0, 0), 2),
        "slide 1 mm forward": rk.translate([0, 1, 0]), "slide 1 mm back": rk.translate([0, -1, 0]),
        "slide 1 mm left": rk.translate([-1, 0, 0]), "slide 1 mm right": rk.translate([1, 0, 0]),
    }
    free = [n for n, m in moves.items() if (m ^ st).volume() < TOL]
    lifts = (rk.translate([0, 0, 1]) ^ st).volume() < TOL
    report(not free and lifts,
           f"the stand holds the rack without screws: cheeks {CHEEK_H:.0f} mm high wrap its sides and corners, so it can't "
           f"tilt or slide any way (tested: tilt 2° each way, slide 1 mm each way); it still lifts straight out"
           + ("" if not free else ": FREE to " + ", ".join(free)))

    # 9c. ... and it sits in it with force: only the ribs touch the rack, each STAND_PRESS deep
    st_r = stand()
    v_walls = (st ^ rk).volume()
    v_ribs = (st_r ^ rk).volume()
    v_else = ((st_r ^ rk) - stand_ribs()).volume()
    # each rib's contact with the rack, measured on its own: its depth is the thin side of the contact patch
    depths = []
    for piece in (stand_ribs() ^ rk).decompose():
        bb = piece.bounding_box()
        depths.append(min(bb[3] - bb[0], bb[4] - bb[1]))
    n_ribs = len(stand_ribs().decompose())
    press_ok = len(depths) == n_ribs and all(abs(d - STAND_PRESS) < 0.02 for d in depths)
    report(v_walls < TOL and v_ribs > TOL and v_else < TOL and press_ok,
           f"the rack sits in the stand with force: all {len(depths)} of {n_ribs} ribs press into it, "
           f"{min(depths, default=0):.2f}-{max(depths, default=0):.2f} mm deep (8 on its sides, 4 on its back, "
           f"2 on its front); only the ribs touch (walls {FIT} mm clear)")

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
    print(f"foundation        {IN_W - 2 * FOUND_CLR:.1f} x {IN_H - 2 * FOUND_CLR:.1f} x {FOUND_T:.1f} mm + ribs pressing {RIB_PRESS} mm")
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
