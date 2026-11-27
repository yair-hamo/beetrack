"""Small test pieces: print these first and try every fit on YOUR printer before printing the real parts.

Each piece is cut out of the real part (same geometry, same print orientation), so if a test piece fits, the
real part fits too. Together they cover every fit that matters:

  test_cage       a 36 mm wide slice of the cage's left side: one feeder hole, one queen-cell hole, one socket,
                  the glass groove and slot, the left wall with vents, floor and roof
  test_foundation the matching slice of the foundation: 7 of its press-fit ribs and one feeder hole
  test_rack       the matching slice of the rack's bottom-left pocket: one peg, one feeder hole, floor, side
                  wall and ceiling
  qc_cap          print 1 real cap (from stl/)

    python hardware/cages/test_pieces.py      -> stl/test/*.stl, plus a check that the pieces fit each other
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
import cages as C  # noqa: E402

OUT = C.STL / "test"
X0, X1 = -C.CAGE_W / 2 - 1, -20.0       # the slice, in cage coordinates: left wall up to x = -20


def cut(m, x0, x1, y0, y1, z0, z1):
    return m ^ C.box(x0, x1, y0, y1, z0, z1)


def pieces():
    big = 1000
    cage = cut(C.cage(), X0, X1, -big, big, -big, big)
    found = cut(C.foundation(), X0, X1, -big, big, -big, big)
    return cage, found, rack_slice(C.rack())


def rack_slice(rack):
    """Bottom-left pocket, from its outer wall to x = -20, moved so the cage that sits in it is at the origin."""
    px, pz = C.pocket_origins()[0]
    big = 1000
    r = cut(rack, px + X0 - C.RACK_WALL - C.POCKET_CLR, px + X1, -big, big, -big, pz + C.POCKET_H + C.RACK_WALL)
    return r.translate([-px, -C.RACK_BACK, -pz])


def check(cage, found, rack) -> bool:
    TOL = 0.5
    ok = True

    def report(passed, text):
        nonlocal ok
        ok &= bool(passed)
        print(f"[{'OK ' if passed else 'FAIL'}] {text}")

    # each piece one closed solid
    for n, m in (("test_cage", cage), ("test_foundation", found), ("test_rack", rack)):
        t = C.to_trimesh(m)
        report(t.is_watertight and len(m.decompose()) == 1, f"{n}: one closed solid")
    # the same fits as the real parts: only the ribs touch (squashed state has no overlap)
    report((C.pressed(found) ^ cage).volume() < TOL and (found ^ cage).volume() > TOL,
           "test_foundation presses into test_cage on its ribs only (left wall, floor, roof)")
    r0 = rack_slice(C.rack(peg_ribs_on=False))           # the same slice with plain pegs (no ribs)
    report((r0 ^ cage).volume() < TOL and (rack ^ cage).volume() > TOL,
           "test_cage pushes onto the test_rack peg; only the peg ribs touch the socket")
    tube = C.cyl_y(C.FEED_D - 0.05, -C.RACK_BACK - 5, C.Y_BEE0 + 2, -30, C.Z_FLOOR + C.FEED_Z)
    report((tube ^ (cage + C.pressed(found) + rack)).volume() < TOL,
           f"a {C.FEED_D - 0.05:.2f} mm tube passes straight through test_rack, test_cage and test_foundation")
    report((C.pressed_cap().translate([-30, C.QC_YW, 0]) ^ cage).volume() < TOL
           and (C.qc_cap().translate([-30, C.QC_YW, 0]) ^ cage).volume() > TOL,
           "a qc_cap presses into the test_cage queen-cell hole on its ribs only")
    return ok


def main():
    cage, found, rack = pieces()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, m, orient in (("test_cage", cage, C.on_back), ("test_foundation", found, C.flat_front_up),
                            ("test_rack", rack, C.on_back)):
        t = C.to_trimesh(C.place_on_bed(orient(m)))
        t.export(OUT / f"{name}.stl")
        e = t.bounds[1] - t.bounds[0]
        print(f"{name:16s} {e[0]:6.1f} x {e[1]:6.1f} x {e[2]:5.1f} mm")
    ok = check(cage, found, rack)
    print("ALL TEST PIECES FIT" if ok else "SOME TEST-PIECE CHECKS FAILED")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
