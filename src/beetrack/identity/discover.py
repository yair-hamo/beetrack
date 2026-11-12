"""Discover the paint colours actually present in a video.

No palette to configure: the marks are learned from the footage itself, so
they match your paint, your LEDs, your camera and its white balance.

1. **Learn what bees look like.** All bee pixels from frames spread over the
   recording give the *cuticle model*: bee bodies (black, brown, amber, wings)
   occupy one narrow band of hues around a dominant hue, up to some
   colourfulness (chroma) and lightness.
2. **Collect spots.** Mark candidates are pixels *outside* that model:

   * a clearly different hue (pink, blue, green…: ≥ ``hue_gap`` from the bees'
     hue, with some colour), or
   * the bees' own hue but far more vivid than any body pixel (neon /
     fluorescent orange and yellow), or
   * brighter than almost any bee pixel and nearly colourless (white paint).

   They must also differ from that bee's own body and form a compact spot.
   Anatomy (stripes, bands, wings) shows on every bee and would otherwise
   swamp the few pixels of a mark.
3. **Cluster.** Spot colours (mean Lab, lightness weighted ``l_weight``) are
   grouped with k-means, then groups closer than ``merge_de`` are merged, and
   tiny groups are dropped.
4. **Describe.** Each group gets a plain name (white, pink, blue…), a display
   colour, a tolerance (from its spread) and example crops, so a person can
   confirm which groups are real marks and which bee wears which.

The confirmed groups become the experiment's palette (``PaintColor`` with
``labs`` + ``tol``) and its ``MarkModel``. During analysis,
:class:`~beetrack.identity.color_id.ColorCodeIdentifier` finds spots with the
same :func:`collect_spots` and matches each to the nearest learned centre.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import cv2
import numpy as np

from ..models import BlobPatch, Detection


@dataclass
class Spot:
    lab: np.ndarray        # mean Lab (OpenCV 8-bit scale: L 0-255, a/b offset 128)
    area: float
    frame: int
    bee_xy: tuple[float, float]
    spot_xy: tuple[float, float]
    det_index: int = -1


def _lab_to_bgr(lab) -> tuple[int, int, int]:
    px = np.uint8([[np.clip(np.round(lab), 0, 255)]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_LAB2BGR)[0, 0]
    return int(b), int(g), int(r)


def color_name(lab) -> str:
    """Plain-language name for a Lab colour (OpenCV 8-bit Lab)."""
    L = lab[0] * 100 / 255
    a, b = lab[1] - 128, lab[2] - 128
    chroma = float(np.hypot(a, b))
    if chroma < 12:
        return "white" if L > 72 else ("black" if L < 25 else "grey")
    hue = (np.degrees(np.arctan2(b, a)) + 360) % 360
    bands = [(20, "pink"), (50, "red"), (75, "orange"), (105, "yellow"), (135, "lime"), (175, "green"),
             (240, "cyan"), (300, "blue"), (330, "purple"), (360, "pink")]
    name = next(n for h, n in bands if hue < h)
    if L > 78 and chroma < 30 and name not in ("white",):
        name = f"pale {name}"
    return name


@dataclass
class CuticleModel:
    hue_deg: float      # dominant hue of bee bodies (LCh hue angle)
    l_white: float      # lightness above which a nearly colourless pixel counts as white paint
    chroma_max: float | None = None  # colourfulness of body pixels (upper quartile); None = don't use

    VIVID = 1.6  # a pixel this many times more vivid than the body (and at least +15) is paint, whatever its hue

    @staticmethod
    def learn(lab_pixels: np.ndarray) -> "CuticleModel":
        a, b = lab_pixels[:, 1] - 128, lab_pixels[:, 2] - 128
        chroma = np.hypot(a, b)
        sel = chroma > 6
        if sel.sum() < 50:
            return CuticleModel(65.0, 200.0)
        ang = np.arctan2(b[sel], a[sel])
        hue = float((np.degrees(np.arctan2((np.sin(ang) * chroma[sel]).sum(), (np.cos(ang) * chroma[sel]).sum())) + 360) % 360)
        # Colourfulness of ordinary body pixels in the bees' own hue band. The sampled pixels include the
        # marks themselves (up to a tenth of a bee's area), so take the upper quartile, not the maximum.
        dh = np.abs((np.degrees(ang) - hue + 180) % 360 - 180)
        body = chroma[sel][dh < 40]
        cmax = float(np.percentile(body, 75)) if len(body) >= 50 else None
        return CuticleModel(hue, float(np.percentile(lab_pixels[:, 0], 99.0)), cmax)

    def outside(self, lab: np.ndarray, hue_gap: float, min_chroma: float, min_l: float = 45.0) -> tuple[np.ndarray, np.ndarray]:
        """(coloured, white) masks of pixels that don't look like bee cuticle."""
        a, b = lab[..., 1] - 128, lab[..., 2] - 128
        chroma = np.hypot(a, b)
        hue = (np.degrees(np.arctan2(b, a)) + 360) % 360
        dh = np.abs((hue - self.hue_deg + 180) % 360 - 180)
        off_hue = dh >= hue_gap
        if self.chroma_max:
            off_hue |= chroma >= max(self.VIVID * self.chroma_max, self.chroma_max + 15)  # neon in the bees' own hue
        coloured = (chroma >= min_chroma) & off_hue & (lab[..., 0] >= min_l)  # near-black: hue is noise
        white = (lab[..., 0] >= self.l_white) & (chroma < 18)
        return coloured, white


def collect_spots(frame: np.ndarray, dets: list[Detection], patches: list[BlobPatch], *, frame_index: int,
                  min_spot_px: float, model: CuticleModel, min_contrast: float = 15.0, hue_gap: float = 40.0,
                  min_chroma: float = 10.0, max_spot_fraction: float = 0.3,
                  exclude: np.ndarray | None = None) -> list[Spot]:
    """Mark-like spots on each detected bee. ``exclude`` (full-frame bool) marks pixels never to read
    (ignore areas such as food, and during discovery the queen cell's wax)."""
    out: list[Spot] = []
    # which detection owns each pixel: a bee's search border must never take a neighbour's mark
    owner = np.zeros(frame.shape[:2], np.int32)
    for k, p in enumerate(patches):
        h, w = p.mask.shape
        region = owner[p.y0:p.y0 + h, p.x0:p.x0 + w]
        region[p.mask[: region.shape[0], : region.shape[1]] > 0] = k + 1
    for k, (d, p) in enumerate(zip(dets, patches)):
        h, w = p.mask.shape
        g = 3  # coloured marks at the body's edge fall just outside the dark-pixel outline: look a little further
        y0, x0 = max(0, p.y0 - g), max(0, p.x0 - g)
        crop = frame[y0:p.y0 + h + g, x0:p.x0 + w + g]
        if p.mask.sum() == 0 or crop.size == 0:
            continue
        inside = np.zeros(crop.shape[:2], bool)
        inside[p.y0 - y0:p.y0 - y0 + h, p.x0 - x0:p.x0 - x0 + w] = p.mask[: crop.shape[0] - (p.y0 - y0), : crop.shape[1] - (p.x0 - x0)] > 0
        grown = cv2.dilate(inside.astype(np.uint8), np.ones((2 * g + 1, 2 * g + 1), np.uint8)) > 0
        own = owner[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]]
        grown &= (own == 0) | (own == k + 1)
        lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
        body = np.median(lab[inside], axis=0)
        de = np.sqrt(((lab - body) ** 2).sum(axis=-1))
        coloured, white = model.outside(lab, hue_gap, min_chroma)
        cand = (de >= min_contrast) & ((coloured & grown) | (white & inside))  # white only strictly inside
        if exclude is not None:
            cand &= ~exclude[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]]
        cand = cand.astype(np.uint8)
        n, labels, stats, cents = cv2.connectedComponentsWithStats(cand, connectivity=8)
        area_bee = float(inside.sum())
        for j in range(1, n):
            a = float(stats[j, cv2.CC_STAT_AREA])
            if a < min_spot_px or a > max_spot_fraction * area_bee:
                continue
            sel = labels == j
            vals, des = lab[sel], de[sel]
            core = vals[des >= np.median(des)]  # the most distinct half (edges blur into the body)
            out.append(Spot(core.mean(axis=0), a, frame_index, (d.x, d.y), (x0 + float(cents[j, 0]), y0 + float(cents[j, 1])), k))
    return out


def cluster_spots(spots: list[Spot], *, l_weight: float = 0.35, merge_de: float = 13.0, max_k: int = 14,
                  min_fraction: float = 0.02, min_count: int = 5) -> list[dict]:
    if len(spots) < min_count:
        return []
    X = np.array([s.lab for s in spots], np.float32)
    W = np.array([l_weight, 1.0, 1.0], np.float32)
    Xw = X * W
    k = int(min(max_k, max(1, len(spots) // 6)))
    cv2.setRNGSeed(0)  # same video → same groups
    _, lab_ids, centers = cv2.kmeans(Xw, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.2), 4,
                                     cv2.KMEANS_PP_CENTERS)
    lab_ids = lab_ids.ravel()
    groups = [list(np.flatnonzero(lab_ids == i)) for i in range(k)]
    groups = [g for g in groups if g]
    # merge groups whose centres are closer than merge_de (weighted Lab)
    merged = True
    while merged and len(groups) > 1:
        merged = False
        cen = [Xw[g].mean(axis=0) for g in groups]
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                dist = float(np.linalg.norm(cen[i] - cen[j]))
                if dist < merge_de and (best is None or dist < best[0]):
                    best = (dist, i, j)
        if best:
            _, i, j = best
            groups[i] = groups[i] + groups[j]
            del groups[j]
            merged = True
    keep = [g for g in groups if len(g) >= max(min_count, min_fraction * len(spots))]
    out = []
    for g in sorted(keep, key=len, reverse=True):
        c = X[g].mean(axis=0)
        spread = float(np.sqrt(((Xw[g] - c * W) ** 2).sum(axis=1).mean()))
        out.append({"members": g, "lab": [round(float(v), 1) for v in c], "spread": spread,
                    "tol": float(np.clip(2.5 * spread, 8.0, 24.0))})
    # keep tolerances from overlapping a neighbour (nearest centre wins anyway; this keeps them meaningful)
    for a in out:
        others = [np.linalg.norm((np.array(a["lab"]) - np.array(b["lab"])) * W) for b in out if b is not a]
        if others:
            a["tol"] = float(min(a["tol"], max(6.0, 0.6 * min(others))))
    return out


def example_crops(frames: dict[int, np.ndarray], spots: list[Spot], members: list[int], n: int = 8, size: int = 96,
                  radius_px: int = 22) -> list[str]:
    """JPEG data-URLs of the bee around a few member spots (different frames), with the spot ringed."""
    chosen, seen = [], set()
    for i in sorted(members, key=lambda i: -spots[i].area):
        s = spots[i]
        if s.frame in seen or s.frame not in frames:
            continue
        seen.add(s.frame)
        chosen.append(s)
        if len(chosen) >= n:
            break
    urls = []
    for s in chosen:
        f = frames[s.frame]
        r = radius_px
        cx, cy = int(s.bee_xy[0]), int(s.bee_xy[1])
        x0, y0 = max(0, cx - r), max(0, cy - r)
        crop = f[y0:cy + r, x0:cx + r].copy()
        if crop.size == 0:
            continue
        sx, sy = s.spot_xy[0] - x0, s.spot_xy[1] - y0
        kx, ky = size / max(1, crop.shape[1]), size / max(1, crop.shape[0])
        crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_CUBIC)
        cv2.circle(crop, (int(sx * kx), int(sy * ky)), max(6, int(np.sqrt(s.area) * kx * 0.9)), (255, 255, 255), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            urls.append("data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode())
    return urls


def mark_likeness(lab, edge_fraction: float) -> tuple[bool, str]:
    """Is this group probably a paint mark? (default for the UI tick box) + a reason when not."""
    L, a, b = lab
    chroma = float(np.hypot(a - 128, b - 128))
    if edge_fraction > 0.5:
        return False, "mostly seen at the dish rim: probably glare on the plastic"
    if L > 225 and chroma < 8:
        return False, "very bright and colourless: probably a reflection"
    return True, ""


def discover(rec, detector, *, n_frames: int = 120, px_per_mm: float, min_spot_mm2: float = 0.3,
             hue_gap: float = 40.0, min_chroma: float = 10.0, dish: tuple[float, float, float] | None = None,
             exclude: np.ndarray | None = None) -> dict:
    """Run discovery on a recording with a prepared detector. Returns clusters ready for the UI.

    ``exclude`` (full-frame bool, e.g. :meth:`Geometry.exclusion_mask` with the queen cell) marks pixels
    that are never used: neither to learn what bees look like nor as mark spots. Without it, the wax of
    the queen cell or the food next to a bee shows up as "marks".
    """
    idx = np.linspace(0, max(0, rec.n_frames - 1), num=min(n_frames, max(1, rec.n_frames))).astype(int)
    seen: list[tuple[int, np.ndarray, list, list]] = []
    body_px = []
    for i in idx:
        try:
            f = rec.read(int(i))
        except IndexError:
            continue
        dets, patches = detector.detect(f, int(i))
        seen.append((int(i), f, dets, patches))
        for p in patches[:12]:
            h, w = p.mask.shape
            crop = f[p.y0:p.y0 + h, p.x0:p.x0 + w]
            if crop.shape[:2] == (h, w):
                use = p.mask > 0
                if exclude is not None:
                    use &= ~exclude[p.y0:p.y0 + h, p.x0:p.x0 + w]
                px = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)[use]
                if len(px) == 0:
                    continue
                body_px.append(px[:: max(1, len(px) // 200)])
    model = CuticleModel.learn(np.concatenate(body_px).astype(np.float32)) if body_px else CuticleModel(65.0, 200.0)
    min_px = max(3.0, min_spot_mm2 * px_per_mm**2)
    crop_r = int(max(16, 0.6 * 12.0 * px_per_mm))  # a bit more than half a bee, at any resolution
    frames: dict[int, np.ndarray] = {}
    spots: list[Spot] = []
    n_bees = 0
    for i, f, dets, patches in seen:
        n_bees += len(dets)
        found = collect_spots(f, dets, patches, frame_index=i, min_spot_px=min_px, model=model,
                              hue_gap=hue_gap, min_chroma=min_chroma, exclude=exclude)
        if found:
            frames[i] = f
        spots.extend(found)
    clusters = cluster_spots(spots, min_fraction=0.01, min_count=4)
    names: dict[str, int] = {}
    result = []
    for c in clusters:
        base = color_name(c["lab"])
        names[base] = names.get(base, 0) + 1
        name = base if names[base] == 1 else f"{base} {names[base]}"
        b, g, r = _lab_to_bgr(c["lab"])
        edge = 0.0
        if dish is not None:
            cx, cy, R = dish
            d = [np.hypot(spots[i].bee_xy[0] - cx, spots[i].bee_xy[1] - cy) / R for i in c["members"]]
            edge = float(np.mean(np.array(d) > 0.88))
        likely, why = mark_likeness(c["lab"], edge)
        result.append({
            "likely_mark": likely, "why_not": why, "edge_fraction": round(edge, 2),
            "name": name, "lab": c["lab"], "tol": round(c["tol"], 1), "display": f"#{r:02x}{g:02x}{b:02x}",
            "n_spots": len(c["members"]), "n_frames": len({spots[i].frame for i in c["members"]}),
            "examples": example_crops(frames, spots, c["members"], radius_px=crop_r),
        })
    return {"clusters": result, "n_spots": len(spots), "n_frames": len(seen), "bee_observations": n_bees,
            "cuticle": {"hue_deg": round(model.hue_deg, 1), "l_white": round(model.l_white, 1),
                        "chroma_max": round(model.chroma_max, 1) if model.chroma_max else None},
            "min_spot_mm2": min_spot_mm2, "excluded_px": int(exclude.sum()) if exclude is not None else 0}
