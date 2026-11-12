"""Synthetic arena videos with exact ground truth.

Used for the test suite, for demos, and for tuning parameters before real
footage exists. It renders a top-down view of a petri dish on a light
background, with a wax queen cell and colour-marked workers that follow a
simple behaviour model:

* **wander**: correlated random walk (≈ 4–14 mm/s) with turning noise;
* **rest**: stand still for a while;
* **approach → visit**: walk to a point on the queen cell, then stay with
  the head on the cell for 3–25 s, with small jitter.

Bees bounce off the dish wall and push each other apart a little, so
crossings and touching bees happen, as in real recordings. The amber
abdomen stripes have the same hue as orange paint (only darker), to test the
colour classifier honestly.

Outputs (in ``out_dir``): ``synthetic.mp4``, ``setup.json``,
``ground_truth.parquet`` (per-frame positions) and ``ground_truth_visits.csv``
(visits computed with the same definition the pipeline uses).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .config import DEFAULT_BEES, AnalysisConfig, BeeSpec, DishGeometry, ExperimentSetup, QueenCell


# Daylight-fluorescent ("neon") paints: far more vivid than ordinary paint. Orange and yellow share
# the hue of a bee's own amber bands and are separable only by how vivid they are.
NEON = {"neon pink": "#ff2fa0", "neon green": "#3dff2e", "neon orange": "#ff6a00", "neon yellow": "#eaff00",
        "neon blue": "#1f8bff", "neon red": "#ff1a2b"}


def _hex_bgr(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


@dataclass
class _Bee:
    spec: BeeSpec
    x: float  # mm, dish frame (y up)
    y: float
    heading: float  # rad, mm frame
    speed: float = 6.0
    state: str = "wander"
    timer: float = 0.0
    target: tuple[float, float] | None = None


class SyntheticArena:
    def __init__(self, *, width: int = 1280, height: int = 720, fps: float = 15.0, dish_diameter_mm: float = 150.0,
                 bees: list[BeeSpec] | None = None, seed: int = 0, bee_length_mm: float = 12.0,
                 colours: dict[str, str] | None = None, mark_at: str = "thorax"):
        """``colours``: paint name → hex, to paint with something other than the standard palette
        (e.g. :data:`NEON`); bees are then W01… in that order unless ``bees`` is given.
        ``mark_at``: ``"thorax"`` (ahead of the body centre) or ``"abdomen"`` (behind it)."""
        self.w, self.h, self.fps = width, height, fps
        self.rng = np.random.default_rng(seed)
        self.dish_d = dish_diameter_mm
        self.r_px = 0.46 * min(width, height)
        self.cx, self.cy = width / 2, height / 2
        self.ppm = 2 * self.r_px / dish_diameter_mm
        self.L = bee_length_mm
        if mark_at not in ("thorax", "abdomen"):
            raise ValueError("mark_at must be 'thorax' or 'abdomen'")
        self.mark_offset = 0.12 if mark_at == "thorax" else -0.30  # × body length, along the heading
        self.colours = colours
        if colours:
            self.palette = {n: _hex_bgr(h) for n, h in colours.items()}
            self.bees_spec = bees or [BeeSpec(bee_id=f"W{i + 1:02d}", color=n) for i, n in enumerate(colours)]
        else:
            self.palette = {c.name: _hex_bgr(c.display) for c in AnalysisConfig().color.palette}
            self.bees_spec = bees or [b.model_copy() for b in DEFAULT_BEES]
        # queen cell: an elongated cup hanging from the upper part of the dish
        self.cell_center = (0.0, 38.0)  # mm
        self.cell_len, self.cell_wid = 24.0, 10.0
        t = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        bulge = 1 + 0.12 * np.cos(t)  # slightly wider at the bottom, like a real cell
        cx_mm = self.cell_center[0] + (self.cell_wid / 2) * np.cos(t) * bulge
        cy_mm = self.cell_center[1] + (self.cell_len / 2) * np.sin(t)
        self.cell_mm = np.column_stack([cx_mm, cy_mm])
        self.cell_px = np.column_stack(self._px(cx_mm, cy_mm)).astype(np.float32)
        self._background = self._render_background()

    # ---- geometry helpers ------------------------------------------------- #
    def _px(self, x_mm, y_mm):
        return self.cx + np.asarray(x_mm) * self.ppm, self.cy - np.asarray(y_mm) * self.ppm

    def setup(self) -> ExperimentSetup:
        return ExperimentSetup(
            dish=DishGeometry(center_px=(self.cx, self.cy), radius_px=self.r_px, diameter_mm=self.dish_d),
            queen_cell=QueenCell(polygon_px=[(float(x), float(y)) for x, y in self.cell_px]),
            bees=self.bees_spec,
        )

    def _cell_dist(self, x_mm: float, y_mm: float) -> float:
        xp, yp = self._px(x_mm, y_mm)
        d = cv2.pointPolygonTest(self.cell_px.reshape(-1, 1, 2), (float(xp), float(yp)), True)
        return max(0.0, -d) / self.ppm

    # ---- rendering --------------------------------------------------------- #
    def _render_background(self) -> np.ndarray:
        img = np.full((self.h, self.w, 3), 178, np.uint8)
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        rr = np.hypot(xx - self.cx, yy - self.cy) / self.r_px
        inside = rr <= 1
        vign = (222 - 10 * rr**2).clip(0, 255)
        for c, tint in enumerate((1.0, 1.0, 0.985)):
            ch = img[..., c].astype(np.float32)
            ch[inside] = vign[inside] * tint
            img[..., c] = ch.clip(0, 255).astype(np.uint8)
        cv2.circle(img, (int(self.cx), int(self.cy)), int(self.r_px), (150, 150, 150), 3, cv2.LINE_AA)
        # light wax queen cell with a slightly darker rim and texture
        pts = np.round(self.cell_px).astype(np.int32)
        cv2.fillPoly(img, [pts], (150, 196, 214), cv2.LINE_AA)
        cv2.polylines(img, [pts], True, (120, 165, 190), 2, cv2.LINE_AA)
        return img

    def _draw_bee(self, img: np.ndarray, b: _Bee) -> None:
        ppm, L = self.ppm, self.L
        x, y = self._px(b.x, b.y)
        th = -b.heading  # image frame angle
        u = np.array([np.cos(th), np.sin(th)])
        deg = np.degrees(th)

        def P(off_mm):
            p = np.array([x, y]) + u * off_mm * ppm
            return int(round(p[0])), int(round(p[1]))

        def axes(a_mm, b_mm):
            return max(1, int(round(a_mm * ppm / 2))), max(1, int(round(b_mm * ppm / 2)))

        body = (32, 44, 58)
        # abdomen with amber stripes
        cv2.ellipse(img, P(-0.22 * L), axes(0.55 * L, 0.37 * L), deg, 0, 360, body, -1, cv2.LINE_AA)
        for k, off in enumerate((-0.12, -0.24, -0.36)):
            cv2.ellipse(img, P(off * L), axes(0.06 * L, 0.33 * L - k * 0.03 * L), deg, 0, 360, (40, 78, 118), -1, cv2.LINE_AA)
        cv2.ellipse(img, P(0.12 * L), axes(0.30 * L, 0.36 * L), deg, 0, 360, (26, 34, 44), -1, cv2.LINE_AA)  # thorax
        cv2.ellipse(img, P(0.38 * L), axes(0.17 * L, 0.26 * L), deg, 0, 360, (20, 24, 30), -1, cv2.LINE_AA)  # head
        # faint wings
        over = img.copy()
        for side in (-1, 1):
            n = np.array([-u[1], u[0]]) * side
            c = np.array([x, y]) + (-0.12 * L * u + 0.16 * L * n) * ppm
            cv2.ellipse(over, (int(c[0]), int(c[1])), axes(0.5 * L, 0.18 * L), deg + side * 12, 0, 360, (190, 190, 190), -1, cv2.LINE_AA)
        cv2.addWeighted(over, 0.22, img, 0.78, 0, img)
        # paint spots
        # one paint dot, on the thorax or the abdomen
        cv2.circle(img, P(self.mark_offset * L), int(round(1.3 * ppm)), self.palette[b.spec.color], -1, cv2.LINE_AA)

    # ---- behaviour --------------------------------------------------------- #
    def _cell_target(self) -> tuple[float, float, float]:
        """A standing point next to the cell, and the heading that faces it."""
        i = self.rng.integers(len(self.cell_mm))
        p = self.cell_mm[i]
        c = np.array(self.cell_center)
        out = (p - c) / (np.linalg.norm(p - c) + 1e-9)
        stand = p + out * (0.42 * self.L - 0.3)  # head just touching the cell
        return float(stand[0]), float(stand[1]), float(np.arctan2(-out[1], -out[0]))

    def _step(self, b: _Bee, dt: float, others: list[_Bee]) -> None:
        rng = self.rng
        b.timer -= dt
        if b.state == "wander":
            b.heading += rng.normal(0, 1.1) * np.sqrt(dt)
            b.speed = float(np.clip(b.speed + rng.normal(0, 3) * np.sqrt(dt), 3, 14))
            if b.timer <= 0:
                r = rng.random()
                if r < 0.35:
                    b.state, b.timer = "rest", rng.uniform(3, 15)
                elif r < 0.75:
                    tx, ty, _ = self._cell_target()
                    b.state, b.target, b.timer = "approach", (tx, ty), 30
                else:
                    b.timer = rng.uniform(4, 12)
        elif b.state == "rest":
            b.speed = 0.0
            if b.timer <= 0:
                b.state, b.timer, b.speed = "wander", rng.uniform(4, 12), 6.0
        elif b.state == "approach":
            tx, ty = b.target
            want = np.arctan2(ty - b.y, tx - b.x)
            b.heading += np.angle(np.exp(1j * (want - b.heading))) * min(1.0, 4 * dt)
            b.speed = 9.0
            if np.hypot(tx - b.x, ty - b.y) < 1.0 or b.timer <= 0:
                b.state, b.timer = "visit", rng.uniform(3, 25)
                d = np.array(self.cell_center) - np.array([b.x, b.y])
                b.heading = float(np.arctan2(d[1], d[0]))
        elif b.state == "visit":
            b.speed = 0.0
            b.heading += rng.normal(0, 0.05)
            if b.timer <= 0:
                b.state, b.timer, b.speed = "wander", rng.uniform(5, 15), 7.0
                b.heading += np.pi  # turn away from the cell

        if b.speed > 0:
            nx = b.x + np.cos(b.heading) * b.speed * dt
            ny = b.y + np.sin(b.heading) * b.speed * dt
            # dish wall
            rmax = self.dish_d / 2 - 0.5 * self.L - 1
            if np.hypot(nx, ny) > rmax:
                b.heading = np.arctan2(-ny, -nx) + rng.normal(0, 0.6)
                nx, ny = b.x, b.y
            # don't walk into the cell body
            if self._cell_dist(nx, ny) < 0.25 * self.L and b.state != "approach":
                b.heading += np.pi / 2
                nx, ny = b.x, b.y
            b.x, b.y = nx, ny
        # gentle mutual repulsion (bees may still touch)
        for o in others:
            if o is b:
                continue
            d = np.hypot(b.x - o.x, b.y - o.y)
            if 1e-6 < d < 0.55 * self.L and b.state not in ("visit",):
                push = (0.55 * self.L - d) * 0.3
                b.x += (b.x - o.x) / d * push
                b.y += (b.y - o.y) / d * push

    # ---- main --------------------------------------------------------------- #
    def generate(self, out_dir: str | Path, duration_s: float = 60.0, noise: float = 3.0) -> dict[str, Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        rng = self.rng
        bees = []
        for spec in self.bees_spec:
            while True:
                r, a = rng.uniform(0, self.dish_d / 2 - 15), rng.uniform(0, 2 * np.pi)
                x, y = r * np.cos(a), r * np.sin(a)
                if self._cell_dist(x, y) > 10 and all(np.hypot(x - o.x, y - o.y) > self.L for o in bees):
                    break
            bees.append(_Bee(spec, x, y, rng.uniform(-np.pi, np.pi), timer=rng.uniform(1, 8)))

        video = out / "synthetic.mp4"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (self.w, self.h))
        n = int(round(duration_s * self.fps))
        dt = 1 / self.fps
        gt = []
        for f in range(n):
            for b in bees:
                self._step(b, dt, bees)
            img = self._background.copy()
            for b in sorted(bees, key=lambda q: q.state != "visit"):
                self._draw_bee(img, b)
            if noise > 0:
                img = np.clip(img.astype(np.int16) + rng.normal(0, noise, img.shape).astype(np.int16), 0, 255).astype(np.uint8)
            writer.write(img)
            for b in bees:
                hx = b.x + 0.42 * self.L * np.cos(b.heading)
                hy = b.y + 0.42 * self.L * np.sin(b.heading)
                gt.append({"frame": f, "time_s": f / self.fps, "bee_id": b.spec.bee_id, "x_mm": b.x, "y_mm": b.y,
                           "head_x_mm": hx, "head_y_mm": hy, "heading_deg": np.degrees(b.heading), "state": b.state})
        writer.release()

        setup_path = out / "setup.json"
        self.setup().save(setup_path)
        gt_df = pd.DataFrame(gt)
        gt_df["observed"] = True
        gt_df["speed_mm_s"] = 0.0
        gt_path = out / "ground_truth.parquet"
        gt_df.to_parquet(gt_path, index=False)

        from .behavior import VisitDetector
        from .calibration import Geometry

        geom = Geometry.from_setup(self.setup(), self.w, self.h)
        visits = VisitDetector(AnalysisConfig().visits, geom).detect(gt_df, self.fps)
        visits_path = out / "ground_truth_visits.csv"
        visits.to_csv(visits_path, index=False)
        return {"video": video, "setup": setup_path, "ground_truth": gt_path, "visits": visits_path}
