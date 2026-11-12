"""Detectors turn a frame into a list of :class:`~beetrack.models.Detection`.

Implementations
---------------
* :class:`BackgroundDetector`: classical segmentation of dark bees on a light
  background. Needs no training data; it's the default.
* :mod:`beetrack.detection.sleap_import`: imports predictions made by a trained
  SLEAP model (pose + identity), as an alternative to the classical path.

To add a detector (e.g. YOLO), implement the :class:`Detector` protocol.
"""

from .base import Detector
from .background import BackgroundDetector

__all__ = ["Detector", "BackgroundDetector"]
