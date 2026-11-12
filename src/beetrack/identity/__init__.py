"""Who is who: paint-colour classification and identity assignment.

* :mod:`.palette`: per-pixel paint colour classification (HSV).
* :mod:`.color_id`: per-detection colour code → evidence for each bee.
* :mod:`.resolver`: per-tracklet vote aggregation, identity-switch splitting,
  and conflict-free assignment of bee IDs to tracklets.
"""

from .color_id import ColorCodeIdentifier
from .palette import Palette
from .resolver import IdentityResolver

__all__ = ["ColorCodeIdentifier", "IdentityResolver", "Palette"]
