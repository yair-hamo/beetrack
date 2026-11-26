"""Parametric 3D-printable parts of the beetrack recording rig ("playground").

    python hardware/cad/playground.py            # writes every part to hardware/cad/stl/
    python hardware/cad/playground.py plate rack # only these parts

Needs: pip install manifold3d trimesh numpy

All sizes are millimetres. Change the numbers in PARAMETERS after measuring your
real parts (glass, tubes, camera, lens) and run the script again. Every part
fits the Bambu Lab P2S bed (256 x 256 mm). Print in PETG: black for everything
the camera sees, white for the background inserts.

The plates STAND UP, like the current vertical dish: the glass faces the camera
(horizontal view), the queen cell hangs from the top, and food and water come in
through the back wall (the side far from the camera).

Coordinate system of each part as printed: x = left→right, y = top→bottom of the
standing plate (y = 0 is the top edge, where the glass slides in), z = towards
the camera (z = 0 is the back wall, the print bed side).
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
# plate (one bee arena: 10 workers + queen cell)
IN_W, IN_D = 100.0, 100.0       # inside size of the arena (width x height when standing)
IN_H = 15.0                     # depth of the arena: from the white background to the glass
WALL = 5.0                      # side wall thickness (holds the glass groove)
BASE = 4.0                      # black back wall (behind the white background insert)
INSERT_T = 2.0                  # white background insert thickness
GLASS_T = 2.0                   # glass thickness (measure yours!)
GLASS_CLR = 0.6                 # extra room in the groove so the glass slides freely
GROOVE = 2.5                    # how deep the glass sits in the side/back walls
LIP = 2.0                       # wall material above the glass
PORT_D = 11.0                   # ports in the back wall for feeder / water tubes (fits a 1.5 mL microtube or a cut 5 mL syringe)
PORT_Y = IN_D - 14.0            # ports near the bottom of the plate
PORT_X = (-25.0, 25.0)          # two ports, left and right of centre
QC_LEDGE_W, QC_LEDGE_D, QC_LEDGE_T, QC_Y = 16.0, 9.0, 3.0, 8.0   # ledge near the top: the queen cell is waxed under it, hanging down
VENT_W, VENT_H, VENT_PITCH = 1.8, 7.0, 4.5   # ventilation slots in the left/right walls (bees can't pass 1.8 mm)
FIT = 0.3                       # clearance for parts that fit into each other
MAGNET_D, MAGNET_T = 10.0, 2.0  # neodymium discs holding each plate in the rack (2 per plate + 2 in the rack pocket)

# rack (holds 4 standing plates in a 2 x 2 grid in fixed positions)
GAP = 8.0                       # between plates
TRAY_MARGIN = 6.0
TRAY_T = 4.0                    # rack plate thickness
POCKET = 2.0                    # how deep plates sit in the rack
SKIRT_H = 45.0                  # room behind the rack for the feeder / water tubes
SKIRT_T = 3.0

# camera mount (Hikrobot CS-series USB3 body: 29 x 29 x 30 mm)
CAM_BODY = 29.0
EXTRUSION = 20.0                # 2020 aluminium profile
M5, M3 = 5.5, 3.4

# light / polariser
POL_HOLE = 60.0                 # hole in the diffuser panel for the lens to look through
POL_APERTURE = 48.0
PANEL_T = 3.0                   # opal acrylic diffuser thickness

OUT = Path(__file__).parent / "stl"
SEG = 96


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def box(x, y, z, at=(0, 0, 0)):
    return Manifold.cube([x, y, z]).translate(list(at))


def cyl(d, h, at=(0, 0, 0), seg=SEG):
    return Manifold.cylinder(h, d / 2, d / 2, seg).translate(list(at))


def union(parts):
    out = parts[0]
    for p in parts[1:]:
        out = out + p
    return out


def save(m: Manifold, name: str) -> Path:
    mesh = m.to_mesh()
    t = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.stl"
    t.export(path)
    ext = t.bounds[1] - t.bounds[0]
    assert ext[0] <= 256 and ext[1] <= 256, f"{name} does not fit the printer bed: {ext}"
    print(f"{name:22s} {ext[0]:6.1f} x {ext[1]:6.1f} x {ext[2]:6.1f} mm  watertight={t.is_watertight}  volume={t.volume / 1000:6.1f} cm3")
    return path


# derived plate sizes
OUT_W, OUT_D = IN_W + 2 * WALL, IN_D + 2 * WALL
Z_FLOOR = BASE + INSERT_T                      # top of the white floor
Z_GLASS = Z_FLOOR + IN_H                       # underside of the glass
Z_TOP = Z_GLASS + GLASS_T + GLASS_CLR + LIP    # top of side/back walls
GLASS_W = IN_W + 2 * GROOVE - 1.0              # glass size to order
GLASS_L = IN_D + WALL + GROOVE - 0.5


# --------------------------------------------------------------------------- #
# parts
# --------------------------------------------------------------------------- #
def plate() -> Manifold:
    """Black arena body (printed back wall down). Glass slides in from the top edge along grooves in the side and bottom walls."""
    body = box(OUT_W, OUT_D, Z_TOP)
    body -= box(IN_W, IN_D, Z_TOP, (WALL, WALL, BASE))                          # the room
    # glass groove: left, right and back walls; open at the front
    g = GLASS_T + GLASS_CLR
    body -= box(IN_W + 2 * GROOVE, IN_D + WALL + GROOVE, g, (WALL - GROOVE, -1, Z_GLASS))
    # the front wall stops under the glass, so the glass slides over it
    body -= box(OUT_W, WALL + 1, Z_TOP, (0, -1, Z_GLASS))
    # finger notch to pull the glass
    body -= cyl(18, 10, (OUT_W / 2, -4, Z_GLASS - 3))
    # ports in the back wall (tubes come in from behind, far from the camera)
    for px in PORT_X:
        body -= cyl(PORT_D, BASE + 2, (OUT_W / 2 + px, WALL + PORT_Y, -1))
    # ventilation slots, left and right walls, between floor and glass
    n = int((IN_D - 20) // VENT_PITCH)
    y0 = WALL + (IN_D - (n - 1) * VENT_PITCH) / 2
    for i in range(n):
        y = y0 + i * VENT_PITCH - VENT_W / 2
        for x in (-1, OUT_W - WALL - 1):
            body -= box(WALL + 2, VENT_W, VENT_H, (x, y, Z_FLOOR + 2.5))
    # magnets in the outside of the back wall (hold the plate in the rack)
    for mx in (-30, 30):
        body -= cyl(MAGNET_D + 0.3, MAGNET_T + 0.2, (OUT_W / 2 + mx, OUT_D / 2, -0.01))
    # orientation mark on the back outer wall (a notch), so plates go in the same way round
    body -= box(10, 1.2, 4, (OUT_W / 2 - 5, OUT_D - 1.2, Z_TOP - 4))
    return body


def background_insert() -> Manifold:
    """White removable background (contrast for dark bees), with the queen-cell ledge and the port holes.
    A sheet of beeswax foundation cut to the same size can replace it."""
    w, d = IN_W - 2 * FIT, IN_D - 2 * FIT
    ins = box(w, d, INSERT_T)
    for px in PORT_X:
        ins -= cyl(PORT_D, INSERT_T + 2, (w / 2 + px, PORT_Y - FIT, -1))
    # queen-cell ledge near the top: the cell is fixed under it with a little wax and hangs down
    ins += box(QC_LEDGE_W, QC_LEDGE_T, QC_LEDGE_D, (w / 2 - QC_LEDGE_W / 2, QC_Y, INSERT_T))
    # a lift slot at the front edge (fingernail / tweezers)
    ins -= box(12, 3, INSERT_T + 1, (w / 2 - 6, -1, 0.8))
    return ins


def rack() -> Manifold:
    """Stands at the back of the box and holds 4 plates (2 x 2) in fixed pockets with magnets; open behind for the tubes."""
    pw, pd = OUT_W + 2 * FIT, OUT_D + 2 * FIT
    size_x = 2 * pw + GAP + 2 * TRAY_MARGIN
    size_y = 2 * pd + GAP + 2 * TRAY_MARGIN
    t = box(size_x, size_y, TRAY_T + POCKET, (0, 0, SKIRT_H))
    t += box(size_x, size_y, SKIRT_H)                                      # skirt
    t -= box(size_x - 2 * SKIRT_T, size_y - 2 * SKIRT_T, SKIRT_H + 0.01, (SKIRT_T, SKIRT_T, -0.01))
    t -= box(size_x * 0.6, SKIRT_T + 2, SKIRT_H - 8, (size_x * 0.2, -1, -0.01))           # hand access, front
    t -= box(size_x * 0.6, SKIRT_T + 2, SKIRT_H - 8, (size_x * 0.2, size_y - SKIRT_T - 1, -0.01))  # and back
    for ix in range(2):
        for iy in range(2):
            x0 = TRAY_MARGIN + ix * (pw + GAP)
            y0 = TRAY_MARGIN + iy * (pd + GAP)
            t -= box(pw, pd, POCKET + 1, (x0, y0, SKIRT_H + TRAY_T))            # pocket
            for px in PORT_X:                                                  # tube holes
                t -= cyl(PORT_D + 4, TRAY_T + 2, (x0 + pw / 2 + px, y0 + FIT + WALL + PORT_Y, SKIRT_H - 1))
            for mx in (-30, 30):                                               # magnets facing the plate's magnets
                t -= cyl(MAGNET_D + 0.3, MAGNET_T + 0.2, (x0 + pw / 2 + mx, y0 + pd / 2, SKIRT_H + TRAY_T - MAGNET_T - 0.2 + 0.01))
    # mounting tabs at the back edge (M5 into the 2020 frame)
    for (tx, ty) in ((0, 0), (size_x - 14, 0), (0, size_y - 14), (size_x - 14, size_y - 14)):
        tab = box(14, 14, 5, (tx, ty, 0)) - cyl(M5, 7, (tx + 7, ty + 7, -1))
        t += tab
    # scale bar on the front margin: 10 mm ticks over 100 mm (for checking the px/mm)
    for i in range(11):
        h = 3.0 if i % 5 == 0 else 1.8
        t -= box(0.8, h, 0.6, (size_x / 2 - 50 + i * 10 - 0.4, 0.6, SKIRT_H + TRAY_T + POCKET - 0.6))
    return t


def camera_mount() -> Manifold:
    """Bolts to a 2020 crossbar (2 x M5) at the front of the box; a square collar clamps the camera body, lens towards the plates."""
    plate_l, plate_w, plate_t = 60.0, EXTRUSION, 5.0
    m = box(plate_l, plate_w, plate_t, (-plate_l / 2, -plate_w / 2, 0))
    for x in (-20, 20):
        m -= cyl(M5, plate_t + 2, (x, 0, -1))
    c_in = CAM_BODY + 0.4
    c_out = c_in + 2 * 4.0
    col_h = 22.0
    collar = box(c_out, c_out, col_h, (-c_out / 2, -c_out / 2, -col_h))
    collar -= box(c_in, c_in, col_h + 2, (-c_in / 2, -c_in / 2, -col_h - 1))
    # clamp slit + screw boss
    collar -= box(1.5, c_out / 2 + 1, col_h + 2, (-0.75, -c_out / 2 - 1, -col_h - 1))
    boss = box(12, 8, 12, (-6, -c_out / 2 - 7, -col_h + 4))
    boss -= box(1.5, 10, 14, (-0.75, -c_out / 2 - 8, -col_h + 3))
    boss -= Manifold.cylinder(14, M3 / 2, M3 / 2, 48).rotate([0, 90, 0]).translate([-7, -c_out / 2 - 3, -col_h + 10])
    m = m + collar + boss
    # cable side opening at the top of the collar (USB connector is at the back of the camera)
    m -= box(14, c_out, 8, (-7, -c_out / 2 - 1, -1))
    return m


def pol_ring() -> Manifold:
    """Sits in the diffuser hole in front of the lens and holds a disc of polariser film; turn it to cancel the glare."""
    flange_d, body_d = POL_HOLE + 14, POL_HOLE - 0.6
    r = cyl(flange_d, 2.0) + cyl(body_d, 2.0 + PANEL_T, (0, 0, 0))
    r -= cyl(POL_APERTURE, 20, (0, 0, -1))
    r -= cyl(POL_APERTURE + 4, 0.6, (0, 0, 2.0 + PANEL_T - 0.6))            # seat for the film disc (Ø52)
    r += box(6, 14, 2.0, (-3, flange_d / 2 - 2, 0))                          # handle to turn it
    return r


def pol_retainer() -> Manifold:
    """Snap ring pressing the polariser film disc into the pol_ring seat."""
    r = cyl(POL_APERTURE + 4 - 0.3, 1.2) - cyl(POL_APERTURE - 1, 3, (0, 0, -1))
    return r


def panel_clip() -> Manifold:
    """Bolts onto a 2020 profile (M5 T-nut) and carries a corner of the diffuser or LED panel."""
    c = box(30, 30, 6)                                                          # shelf
    c += box(30, 5, 26, (0, 25, 0))                                            # back plate against the profile
    c += box(5, 30, 26, (25, 0, 0))
    c -= Manifold.cylinder(8, M5 / 2, M5 / 2, 48).rotate([90, 0, 0]).translate([15, 32, 16])
    c -= Manifold.cylinder(8, M5 / 2, M5 / 2, 48).rotate([0, 90, 0]).translate([23, 15, 16])
    # lip that keeps the panel corner from sliding
    c += box(30, 2, 3 + PANEL_T, (0, 23, 6)) + box(2, 30, 3 + PANEL_T, (23, 0, 6))
    return c


def port_plug() -> Manifold:
    """Closes a back-wall port that is not used (push in from behind)."""
    p = cyl(PORT_D - 0.25, BASE + INSERT_T) + cyl(PORT_D + 5, 2.0, (0, 0, -2.0))
    return p


PARTS = {
    "plate": plate, "background_insert": background_insert, "rack": rack, "camera_mount": camera_mount,
    "pol_ring": pol_ring, "pol_retainer": pol_retainer, "panel_clip": panel_clip, "port_plug": port_plug,
}


def main(names):
    print(f"plate outside {OUT_W:.0f} x {OUT_D:.0f} x {Z_TOP:.1f} mm, room {IN_W:.0f} x {IN_D:.0f} x {IN_H:.0f} mm")
    print(f"glass to order: {GLASS_W:.1f} x {GLASS_L:.1f} x {GLASS_T:.1f} mm (one per plate, plus spares)")
    for n in names or PARTS:
        save(PARTS[n](), n)


if __name__ == "__main__":
    main(sys.argv[1:])
