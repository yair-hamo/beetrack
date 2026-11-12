"""Read the mark on one detected bee and score it against the registry.

Each marked bee has **one mark of a unique colour** (on the back, the belly,
or both). For each detection we:

1. take the BGR pixels inside the bee mask (slightly grown, because paint
   at the edge of a dark body can fall just outside the dark-pixel mask);
2. classify paint pixels with :class:`~beetrack.identity.palette.Palette`;
3. collect paint *spots* (connected regions ≥ ``min_spot_area_mm2``) and add
   up the area per colour (a dot split in two by glare still counts as one);
4. score:

   * one colour seen → **1.0** for the bee with that colour;
   * two colours seen (touching bees, or a false spot) → if the larger is
     ≥ ``dominance`` × the smaller it still counts **1.0**; otherwise the
     evidence is shared in proportion to area;
   * nothing readable (dot hidden by a wing, a neighbour, or the bee upside
     down) → no evidence.

Scores are *evidence*, not probabilities: the resolver adds them up over a
whole tracklet, so one bad frame doesn't matter. The dot position is also
kept: on the thorax it lies in front of the body centre, which tells head
from tail (see :mod:`beetrack.trajectories`).
"""

from __future__ import annotations

import cv2
import numpy as np

from ..calibration import Geometry
from ..config import BeeSpec, ColorIdConfig
from ..models import BlobPatch, Detection
from .palette import Palette


class ColorCodeIdentifier:
    """Reads marks on detected bees.

    Two ways of finding mark pixels:

    * **learned** (a ``MarkModel`` from colour discovery): exactly the spot finding
      used during discovery (pixels outside the learned bee-cuticle colours), then
      each spot is matched to the nearest learned mark centre within its tolerance;
    * **configured** palette: fixed HSV thresholds (the original method).
    """

    def __init__(self, cfg: ColorIdConfig, bees: list[BeeSpec], geom: Geometry, mark_model=None):
        self.cfg = cfg
        self.palette = Palette(cfg)
        self.bees = bees
        self.mark_model = mark_model
        self.px_per_mm = geom.px_per_mm
        self._learned = [(c.name, np.asarray(c.labs, np.float32), c.tol) for c in cfg.palette if c.labs]
        # never read marks in the ignore areas (food, water…); bees on the queen cell keep their marks readable
        self._exclude = geom.exclusion_mask(include_cell=False)
        self.min_spot_px = cfg.min_spot_area_mm2 * geom.px_per_mm**2
        self._pad = max(2, int(round(geom.mm(0.6))))
        self._dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * self._pad + 1, 2 * self._pad + 1))
        self._by_color = {b.color: b.bee_id for b in bees}

    def observe(self, frame: np.ndarray, patch: BlobPatch) -> list[tuple[str, float, float, float]]:
        """Paint seen on one bee, one entry per colour: ``(colour, x_px, y_px, area_px)``, largest first (max 2)."""
        p = self._pad
        h, w = patch.mask.shape
        y0, x0 = max(0, patch.y0 - p), max(0, patch.x0 - p)
        y1, x1 = min(frame.shape[0], patch.y0 + h + p), min(frame.shape[1], patch.x0 + w + p)
        crop = frame[y0:y1, x0:x1]
        mask = np.zeros(crop.shape[:2], np.uint8)
        my, mx = patch.y0 - y0, patch.x0 - x0
        mask[my:my + h, mx:mx + w] = patch.mask
        grown = cv2.dilate(mask, self._dilate)

        labels = self.palette.classify(crop)
        labels[grown == 0] = -1
        # The light background next to the body looks like white paint, so
        # white is only accepted strictly inside the body outline.
        if self.palette.white_index is not None:
            labels[(labels == self.palette.white_index) & (mask == 0)] = -1
        spots: list[tuple[float, str, float, float]] = []
        for idx in np.unique(labels):
            if idx < 0:
                continue
            m = (labels == idx).astype(np.uint8)
            n, _, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=8)
            for j in range(1, n):
                a = float(stats[j, cv2.CC_STAT_AREA])
                if a >= self.min_spot_px:
                    spots.append((a, self.palette.names[idx], x0 + float(cents[j, 0]), y0 + float(cents[j, 1])))
        # merge spots of the same colour (area-weighted centre)
        per: dict[str, list[float]] = {}
        for a, name, x, y in spots:
            acc = per.setdefault(name, [0.0, 0.0, 0.0])
            acc[0] += a
            acc[1] += a * x
            acc[2] += a * y
        merged = sorted(((a, n, sx / a, sy / a) for n, (a, sx, sy) in per.items()), reverse=True)
        return [(n, x, y, a) for a, n, x, y in merged[:2]]

    def score(self, spots: list[tuple[str, float, float, float]]) -> dict[str, float]:
        known = [(n, a) for n, _, _, a in spots if n in self._by_color]
        if not known:
            return {}
        if len(known) == 1 or known[0][1] >= self.cfg.dominance * known[1][1]:
            return {self._by_color[known[0][0]]: 1.0}
        total = known[0][1] + known[1][1]
        return {self._by_color[n]: a / total for n, a in known[:2]}

    def _match(self, lab: np.ndarray) -> str | None:
        w = np.array([self.mark_model.l_weight, 1.0, 1.0], np.float32)
        best, best_d = None, np.inf
        for name, centres, tol in self._learned:
            dist = float(np.min(np.linalg.norm((centres - lab) * w, axis=1)))
            if dist <= tol and dist < best_d:
                best, best_d = name, dist
        return best

    def identify(self, frame: np.ndarray, dets: list[Detection], patches: list[BlobPatch]) -> None:
        """Fill ``spots``, ``colors`` and ``color_scores`` in place."""
        if self.mark_model is not None and self._learned:
            from .discover import CuticleModel, collect_spots

            mm = self.mark_model
            found = collect_spots(frame, dets, patches, frame_index=dets[0].frame if dets else 0,
                                  min_spot_px=max(3.0, mm.min_spot_mm2 * self.px_per_mm**2),
                                  model=CuticleModel(mm.cuticle_hue_deg, mm.l_white, mm.chroma_max), min_contrast=mm.min_contrast,
                                  hue_gap=mm.hue_gap, min_chroma=mm.min_chroma, exclude=self._exclude)
            per: dict[int, dict[str, list[float]]] = {}
            for s in found:
                name = self._match(s.lab)
                if name is None:
                    continue
                acc = per.setdefault(s.det_index, {}).setdefault(name, [0.0, 0.0, 0.0])
                acc[0] += s.area
                acc[1] += s.area * s.spot_xy[0]
                acc[2] += s.area * s.spot_xy[1]
            for k, d in enumerate(dets):
                spots = sorted(((a, n, sx / a, sy / a) for n, (a, sx, sy) in per.get(k, {}).items()), reverse=True)[:2]
                spots = [(n, x, y, a) for a, n, x, y in spots]
                d.spots = tuple((n, x, y) for n, x, y, _ in spots)
                d.colors = tuple(n for n, _, _, _ in spots)
                d.color_scores = self.score(spots)
            return
        for d, p in zip(dets, patches):
            spots = self.observe(frame, p)
            d.spots = tuple((n, x, y) for n, x, y, _ in spots)
            d.colors = tuple(n for n, _, _, _ in spots)
            d.color_scores = self.score(spots)
