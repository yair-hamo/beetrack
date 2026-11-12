"""Web server: FastAPI backend + static single-page UI.

Modules
-------
* :mod:`.db`: SQLite models (experiments, videos, jobs) via SQLAlchemy.
* :mod:`.store`: on-disk layout of experiment folders.
* :mod:`.worker`: background job runner; each analysis runs in a child process.
* :mod:`.overlay`: renders video frames with geometry and tracks drawn on.
* :mod:`.api`: REST endpoints (``/api/...``); see ``docs/API.md``.
* :mod:`.app`: application factory used by ``beetrack serve``.
"""
