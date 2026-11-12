"""Shared fixtures.

* ``synthetic``: an easy synthetic recording (≈45 s, 1280×720, 15 fps, 10 marked bees) with exact ground truth.
* ``result``: its default analysis.
* ``crowded`` / ``crowded_result``: a harder recording in which bees pile up on the queen cell, so some
  track pieces can only be named by motion. Used to test that identity probabilities mean something.
"""

from __future__ import annotations

import pytest

from beetrack.synthetic import SyntheticArena


@pytest.fixture(scope="session")
def synthetic(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    arena = SyntheticArena(seed=3)
    paths = arena.generate(out, duration_s=45)
    paths["arena"] = arena
    return paths


@pytest.fixture(scope="session")
def result(synthetic, tmp_path_factory):
    """The default analysis of the synthetic recording (10 marked bees), shared by many tests."""
    from beetrack.config import AnalysisConfig, ExperimentSetup
    from beetrack.pipeline import AnalysisPipeline

    setup = ExperimentSetup.load(synthetic["setup"])
    return AnalysisPipeline(AnalysisConfig(), setup).run([synthetic["video"]], tmp_path_factory.mktemp("results"))


@pytest.fixture(scope="session")
def crowded(tmp_path_factory):
    out = tmp_path_factory.mktemp("crowded")
    return SyntheticArena(seed=1).generate(out, duration_s=60)


@pytest.fixture(scope="session")
def crowded_result(crowded, tmp_path_factory):
    from beetrack.config import AnalysisConfig, ExperimentSetup
    from beetrack.pipeline import AnalysisPipeline

    setup = ExperimentSetup.load(crowded["setup"])
    return AnalysisPipeline(AnalysisConfig(), setup).run([crowded["video"]], tmp_path_factory.mktemp("crowded_results"))
