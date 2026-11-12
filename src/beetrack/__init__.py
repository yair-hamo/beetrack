"""beetrack: colour-ID tracking of honeybee workers and queen-cell visit analysis.

Pipeline overview (see docs/ARCHITECTURE.md)::

    video ─► detection ─► colour identity ─► tracking ─► identity resolution
          ─► trajectories (mm) ─► queen-cell visits ─► metrics / exports

The package is importable without the web server; ``beetrack.server`` is only
needed for the browser UI.
"""

__version__ = "0.3.0"
