"""Configuration models.

Two kinds of configuration exist, and they are deliberately separate:

* :class:`AnalysisConfig`: *how* to analyse (thresholds, frame rate, tracker
  gates...). Usually shared by every experiment in a study, so results stay
  comparable. Defaults live here and are the single source of truth;
  ``beetrack config-dump`` prints them as YAML.
* :class:`ExperimentSetup`: *what* is in a particular video (where the dish
  and queen cell are, which bee wears which colours). Unique per experiment;
  created in the web UI or with ``beetrack init-setup``.

All lengths in configuration are in **millimetres** or **seconds**, never
pixels or frames, so the same config works for any camera resolution or frame
rate. Conversion happens once, in :mod:`beetrack.calibration`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Analysis configuration
# --------------------------------------------------------------------------- #


class PaintColor(BaseModel):
    """One paint colour in the marking palette.

    ``hue`` uses OpenCV's 0-179 scale. ``white`` colours are matched by low
    saturation + high brightness instead of by hue.
    """

    name: str
    hue: float | None = Field(None, ge=0, le=180, description="OpenCV hue 0-179; None for white")
    white: bool = False
    display: str = Field("#888888", description="Hex colour used in the UI and overlays")
    labs: list[tuple[float, float, float]] | None = Field(
        None, description="Learned from the video: Lab centre(s) of this mark (OpenCV 8-bit Lab). Replaces hue/white")
    tol: float = Field(10.0, gt=0, description="Learned marks: max weighted-Lab distance to a centre")

    @model_validator(mode="after")
    def _check(self) -> "PaintColor":
        if not self.white and self.hue is None and not self.labs:
            raise ValueError(f"colour {self.name!r} needs a hue, white=true, or learned Lab centres")
        return self


DEFAULT_PALETTE: list[PaintColor] = [
    # One dot per bee, so 10 workers need 10 colours. Hues measured from the display colours.
    # Tune them to your real paint with the colour probe (Setup tab).
    PaintColor(name="white", white=True, display="#f5f5f5"),
    PaintColor(name="yellow", hue=26, display="#f2d531"),
    PaintColor(name="lime", hue=38, display="#a6d62a"),
    PaintColor(name="green", hue=67, display="#2fb24c"),
    PaintColor(name="cyan", hue=95, display="#22c3e6"),
    PaintColor(name="blue", hue=109, display="#2f6fe0"),
    PaintColor(name="purple", hue=136, display="#9b4de0"),
    PaintColor(name="pink", hue=162, display="#f055b4"),
    PaintColor(name="red", hue=1, display="#e0352b"),
    # Orange has the same hue as the bees' amber abdomen bands. Only brightness separates them;
    # drop it if the colour probe shows confusion on your footage.
    PaintColor(name="orange", hue=13, display="#f07a1e"),
]


class DetectionConfig(BaseModel):
    """Classical (no-training) bee segmentation on a light, uniform background."""

    method: Literal["morphological", "median"] = Field(
        "morphological",
        description=(
            "morphological: estimate the empty background per frame by a grey-level "
            "closing (robust to bees that rest for a long time, e.g. on the queen cell). "
            "median: temporal median of sampled frames (faster, but a bee that never "
            "moves becomes background)."
        ),
    )
    diff_threshold: int = Field(28, ge=1, le=255, description="How much darker than background a pixel must be (grey levels)")
    bee_length_mm: float = Field(12.0, gt=0, description="Typical worker body length")
    bee_width_mm: float = Field(4.5, gt=0, description="Typical worker body width")
    min_area_fraction: float = Field(0.35, gt=0, description="Smallest blob kept, as a fraction of one bee's area")
    max_bees_per_blob: int = Field(4, ge=1, description="Largest cluster we try to split into individuals")
    arena_margin_mm: float = Field(2.0, ge=0, description="Ignore this band just inside the dish rim (shadows, reflections)")
    median_samples: int = Field(60, ge=5, description="Frames sampled for the median background")
    bee_size: Literal["auto", "from_scale"] = Field(
        "auto",
        description=(
            "auto: measure the size of one bee from the video (robust to a wrong or unknown dish diameter). "
            "from_scale: use bee_length_mm × bee_width_mm and the dish scale"
        ),
    )
    size_samples: int = Field(40, ge=5, description="Frames sampled to measure the bee size")
    static_suppression: float = Field(
        0.0, ge=0, le=1,
        description=(
            "Dark things that stay put (queen-cell wax, food, tape) are learned as background: pixels that are "
            "'bee-dark' in at least this fraction of sampled frames use a temporal-median background instead. "
            "A bee walking over them is still detected; a bee that sits on one spot most of the recording may be "
            "missed there. 0 = off"
        ),
    )
    auto_threshold: bool = Field(
        True,
        description=(
            "When the number of bees is known (colour mode: the registry; unmarked: 'bees in the dish'), try several "
            "sensitivities on sampled frames and pick the one whose bee count per frame matches best "
            "(ties → fewer false positives). Overrides diff_threshold"
        ),
    )
    ignore_queen_cell: bool = Field(
        False,
        description="Drop foreground pixels inside the queen-cell outline. Enable if the cell is dark enough to be detected as a bee",
    )


class ColorIdConfig(BaseModel):
    """Paint-spot detection and colour classification (HSV)."""

    palette: list[PaintColor] = Field(default_factory=lambda: [c.model_copy() for c in DEFAULT_PALETTE])
    min_saturation: int = Field(110, ge=0, le=255, description="Chromatic paint must be at least this saturated")
    min_value: int = Field(
        160, ge=0, le=255,
        description="...and at least this bright. Opaque paint is much brighter than amber cuticle (V≈120), keep this high",
    )
    white_max_saturation: int = Field(60, ge=0, le=255)
    white_min_value: int = Field(200, ge=0, le=255)
    max_hue_distance: float = Field(
        6, gt=0,
        description="Max hue distance to accept a palette match. Neighbouring palette hues are about 12 apart",
    )
    min_spot_area_mm2: float = Field(0.8, gt=0, description="Smallest paint spot considered")
    dominance: float = Field(
        1.5, ge=1,
        description="If two different colours are seen on one bee, the larger spot counts fully only if it is this many times bigger",
    )
    dot_position: Literal["auto", "thorax", "abdomen", "unknown"] = Field(
        "auto",
        description=(
            "Where the mark sits on the body, used to tell head from tail. auto: learned per bee from the frames in "
            "which it walks (the mark is ahead of or behind the body centre). thorax / abdomen: fixed for all bees. "
            "unknown: don't use the mark for direction"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy_dot_on_thorax(cls, data):
        # configs written before v0.3 had dot_on_thorax: true/false
        if isinstance(data, dict) and "dot_on_thorax" in data:
            data = dict(data)
            flag = data.pop("dot_on_thorax")
            data.setdefault("dot_position", "thorax" if flag else "unknown")
        return data


class TrackingConfig(BaseModel):
    max_speed_mm_s: float = Field(40.0, gt=0, description="Fastest plausible walking speed (workers walk about 10–25 mm/s)")
    gate_max_dt_s: float = Field(
        0.4, gt=0,
        description="After a gap, a lost bee is assumed to have moved at most this many seconds' worth of max speed "
                    "(a bee hidden in a cluster doesn't run across the dish). Stops tracks jumping to far-away blobs",
    )
    gate_slack_mm: float = Field(4.0, ge=0, description="Extra distance allowed on top of max speed * dt")
    max_gap_s: float = Field(1.0, ge=0, description="Keep a lost track alive this long before closing it")


class IdentityConfig(BaseModel):
    min_votes: float = Field(3.0, ge=0, description="Minimum colour evidence for a tracklet to be named")
    min_purity: float = Field(0.6, ge=0, le=1, description="Fraction of evidence that must agree on the winner")
    switch_window: int = Field(9, ge=1, description="Observations used to smooth identity inside a tracklet")
    switch_min_votes: int = Field(6, ge=1, description="Min full-code matches on each side to split a tracklet")
    link_max_gap_s: float = Field(3.0, ge=0, description="Gap-linking: max time between a named tracklet's end and an unnamed one's start")
    link_max_dist_mm: float = Field(6.0, ge=0, description="Gap-linking: max distance between those two endpoints")
    closed_group: bool = Field(
        True,
        description=(
            "When the number of bees in the dish is known, use exactly that many identities (marked W…, unmarked U…): "
            "every track is assigned to one of them with a probability, never more bees than are in the dish"
        ),
    )
    min_probability: float = Field(
        0.0, ge=0, le=1,
        description=(
            "Closed group: positions whose identity probability is below this are left out of the named trajectories "
            "(and so of visits and per-bee numbers). 0 keeps everything; the probability is always in the output"
        ),
    )
    keep_unidentified: bool = Field(
        True,
        description="Hybrid: tracks whose mark was never read clearly enough are kept as anonymous tracks (T001…) instead of dropped",
    )


class TrajectoryConfig(BaseModel):
    max_interp_gap_s: float = Field(2.0, ge=0, description="Fill gaps up to this long by linear interpolation")
    max_interp_speed_mm_s: float = Field(40.0, gt=0, description="…but only if crossing the gap needs no more than this speed")
    max_still_gap_s: float = Field(
        30.0, ge=0,
        description="Also fill longer gaps (up to this) if the bee reappears where it vanished, e.g. resting inside a cluster on the cell",
    )
    still_gap_max_move_mm: float = Field(3.0, ge=0, description="'Where it vanished' = within this distance")
    smooth_window_s: float = Field(0.4, ge=0, description="Centred rolling-median window for positions")
    moving_speed_mm_s: float = Field(2.0, ge=0, description="Above this a bee counts as moving (also used for heading)")
    head_offset_fraction: float = Field(0.42, ge=0, le=0.5, description="Head point = centroid + this * body length along heading")


class Zone(BaseModel):
    """A zone around the queen cell, defined as the cell outline grown by ``margin_mm``."""

    name: str
    margin_mm: float = Field(ge=0)


class VisitConfig(BaseModel):
    zones: list[Zone] = Field(
        default_factory=lambda: [Zone(name="contact", margin_mm=3.0), Zone(name="vicinity", margin_mm=10.0)]
    )
    point: Literal["head", "centroid"] = Field("head", description="Which body point must enter the zone")
    min_visit_s: float = Field(1.0, ge=0, description="Drop visits shorter than this")
    merge_gap_s: float = Field(1.5, ge=0, description="Merge two visits separated by less than this")
    bin_s: float = Field(300.0, gt=0, description="Bin width for time-resolved metrics (s)")


class UnmarkedConfig(BaseModel):
    """Tracking without paint marks: anonymous tracks joined only when unambiguous."""

    stitch_max_gap_s: float = Field(2.0, ge=0, description="Join a track that ends and one that starts within this time…")
    stitch_max_dist_mm: float = Field(8.0, ge=0, description="…and this distance")
    stitch_ambiguity_ratio: float = Field(
        1.5, ge=1,
        description="Don't join if a second candidate is nearly as close (its distance < ratio × the best). Never guess",
    )
    min_track_s: float = Field(2.0, ge=0, description="Drop tracks shorter than this (noise, fragments)")


class AnalysisConfig(BaseModel):
    """Everything that controls *how* a video is analysed."""

    analysis_fps: float = Field(15.0, gt=0, description="Frames per second actually analysed (video is subsampled)")
    max_frames: int | None = Field(None, ge=1, description="Debug: stop after this many analysed frames")
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    color: ColorIdConfig = Field(default_factory=ColorIdConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    trajectories: TrajectoryConfig = Field(default_factory=TrajectoryConfig)
    visits: VisitConfig = Field(default_factory=VisitConfig)
    unmarked: UnmarkedConfig = Field(default_factory=UnmarkedConfig)

    # --- I/O helpers ----------------------------------------------------- #
    @classmethod
    def load(cls, path: str | Path | None) -> "AnalysisConfig":
        if path is None:
            return cls()
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(data)

    def dump_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


# --------------------------------------------------------------------------- #
# Experiment setup
# --------------------------------------------------------------------------- #


class DishGeometry(BaseModel):
    center_px: tuple[float, float]
    radius_px: float = Field(gt=0)
    diameter_mm: float = Field(150.0, gt=0, description="Inner diameter of the dish in mm (the real-world scale)")


class EllipseShape(BaseModel):
    """An editable ellipse (image pixels): centre, full length along its axis, full width, axis angle."""

    type: Literal["ellipse"] = "ellipse"
    cx: float
    cy: float
    length_px: float = Field(gt=0)
    width_px: float = Field(gt=0)
    angle_deg: float = 0.0

    def polygon(self, n: int = 48) -> list[tuple[float, float]]:
        a = np.radians(self.angle_deg)
        u, v = np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])
        th = np.linspace(0, 2 * np.pi, n, endpoint=False)
        pts = (np.array([self.cx, self.cy])[None, :] + np.outer(np.cos(th) * self.length_px / 2, u)
               + np.outer(np.sin(th) * self.width_px / 2, v))
        return [(round(float(x), 1), round(float(y), 1)) for x, y in pts]


class Region(BaseModel):
    """An area in the image: an editable ellipse (``shape``) or a free outline (``polygon_px``).

    ``polygon_px`` is what the analysis uses. If ``shape`` is set, the polygon is
    regenerated from it, so the two never disagree, and the UI can re-open the
    area as an editable ellipse.
    """

    shape: EllipseShape | None = None
    polygon_px: list[tuple[float, float]] = Field(default_factory=list, description="Outline in image pixels")

    @model_validator(mode="after")
    def _sync(self) -> "Region":
        if self.shape is not None:
            self.polygon_px = self.shape.polygon()
        if len(self.polygon_px) < 3:
            raise ValueError("an area needs a shape or an outline of at least 3 points")
        return self


class QueenCell(Region):
    """Where the queen cell is in this experiment's video."""

    learn_background: bool = Field(
        True,
        description=(
            "Learn the cell's own appearance (temporal median) so its dark wax isn't detected as bees. "
            "Bees moving on the cell are still detected; a bee sitting still on it for most of the recording may be missed"
        ),
    )


class IgnoreArea(Region):
    """An area where nothing is detected (food, water tube, tape, reflections)."""

    name: str = Field("ignore", max_length=40)


class BeeSpec(BaseModel):
    """One marked worker: its ID and the colour of its mark."""

    bee_id: str = Field(min_length=1, max_length=32)
    color: str = Field(description="Palette colour of the dot")
    label: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_two_spot(cls, data):
        # setups saved by v0.1 had thorax/abdomen; the thorax colour becomes the dot colour
        if isinstance(data, dict) and "color" not in data and "thorax" in data:
            data = {**data, "color": data["thorax"]}
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k not in ("thorax", "abdomen")}
        return data

    @property
    def code(self) -> tuple[str, ...]:
        return (self.color,)

    @property
    def code_str(self) -> str:
        return self.color


DEFAULT_BEES: list[BeeSpec] = [
    BeeSpec(bee_id=f"W{i + 1:02d}", color=c.name) for i, c in enumerate(DEFAULT_PALETTE[:10])
]


class MarkModel(BaseModel):
    """How marks were found when the palette was learned from the video (see identity/discover.py)."""

    cuticle_hue_deg: float = Field(description="Dominant hue of bee bodies (LCh)")
    l_white: float = Field(description="Lightness above which a colourless pixel is white paint")
    chroma_max: float | None = Field(
        None, description="Colourfulness of bee bodies (upper quartile): a much more vivid pixel is paint even in the bees' own hue (neon orange/yellow)")
    hue_gap: float = 40.0
    min_chroma: float = 10.0
    min_contrast: float = 15.0
    l_weight: float = 0.35
    min_spot_mm2: float = Field(0.3, gt=0, description="Smallest mark spot, in mm² at the processing scale")


class ExperimentSetup(BaseModel):
    """Everything that is specific to one recording."""

    marking: Literal["color", "none"] = Field(
        "color",
        description=(
            "color: each bee wears a unique paint dot, so identities are kept for the whole recording. "
            "none: unmarked bees, so the output is anonymous tracks (T001…) that are only certain between contacts"
        ),
    )
    dish: DishGeometry | None = None
    queen_cell: QueenCell | None = None
    ignore_areas: list[IgnoreArea] = Field(default_factory=list, description="Areas where nothing is detected (food, water, tape)")
    bees: list[BeeSpec] = Field(default_factory=lambda: [b.model_copy() for b in DEFAULT_BEES])
    n_bees: int | None = Field(None, ge=1, le=500, description="How many bees are in the dish, marked or not (tunes detection, sanity checks)")
    palette: list[PaintColor] | None = Field(None, description="Marks learned from this video (replaces the configured palette)")
    mark_model: MarkModel | None = None
    id_min_votes: float | None = Field(None, ge=0, description="Name a track only if its mark was read at least this often")
    id_min_purity: float | None = Field(None, ge=0, le=1, description="…and at least this share of readings agree on one bee")
    id_min_probability: float | None = Field(
        None, ge=0, le=1, description="Leave positions out of a bee's path when the identity is less certain than this (see identity.min_probability)")

    def effective_config(self, cfg: "AnalysisConfig") -> "AnalysisConfig":
        """The config with this experiment's own settings applied: learned palette and identity thresholds."""
        upd = {}
        if self.palette:
            upd["color"] = cfg.color.model_copy(update={"palette": list(self.palette)})
        ident = {k: v for k, v in (("min_votes", self.id_min_votes), ("min_purity", self.id_min_purity),
                                   ("min_probability", self.id_min_probability)) if v is not None}
        if ident:
            upd["identity"] = cfg.identity.model_copy(update=ident)
        return cfg.model_copy(update=upd) if upd else cfg

    @property
    def expected_bees(self) -> int | None:
        """Bees in the dish (marked or not). In colour mode the registry may list only the marked ones."""
        if self.n_bees:
            return self.n_bees
        return len(self.bees) if self.marking == "color" else None

    @field_validator("bees")
    @classmethod
    def _unique_ids(cls, bees: list[BeeSpec]) -> list[BeeSpec]:
        ids = [b.bee_id for b in bees]
        if len(ids) != len(set(ids)):
            raise ValueError("bee_id values must be unique")
        return bees

    def check(self, cfg: AnalysisConfig) -> dict[str, list[str]]:
        """Validate the setup against a config.

        Returns ``{"errors": [...], "warnings": [...]}``. Errors block analysis;
        warnings don't (e.g. no queen cell means trajectories only, no visits).
        """
        errors: list[str] = []
        warnings: list[str] = []
        names = {c.name for c in (self.palette or cfg.color.palette)}
        owner: dict[str, str] = {}
        for b in (self.bees if self.marking == "color" else []):
            if b.color not in names:
                errors.append(f"{b.bee_id}: colour {b.color!r} is not in the palette ({', '.join(sorted(names))})")
            if b.color in owner:
                errors.append(f"{b.bee_id} and {owner[b.color]} both have a {b.color} dot; every bee needs its own colour")
            owner.setdefault(b.color, b.bee_id)
        if self.marking == "color" and not self.bees:
            errors.append("no bees registered")
        if self.marking == "color" and self.bees and not self.palette:
            warnings.append(
                "the bee colours are the built-in list, not the marks in this video. Use 'Find the marks in the video' "
                "so each bee gets the colour it really wears; a colour that is not in the dish gives a meaningless name"
            )
        if not self.n_bees:
            warnings.append(
                "'Bees in the dish' is empty: enter how many bees are in the dish (marked or not). It tunes detection "
                "sensitivity (fewer missed bees) and gives exactly that many identities"
            )
        if self.marking == "none" and not self.n_bees:
            warnings.append("unmarked bees: tracks are anonymous, and a bee may continue under a new track ID after touching another bee")
        if self.dish is None:
            errors.append("dish geometry is not set (auto-detect it, or click 3 points on the rim)")
        if self.queen_cell is None:
            warnings.append("queen-cell outline is not set, so only trajectories will be computed (no visits)")
        return {"errors": errors, "warnings": warnings}

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentSetup":
        return cls.model_validate_json(Path(path).read_text())

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2))
