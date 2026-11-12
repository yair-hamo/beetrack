"""Web API, exercised in-process with FastAPI's TestClient (no network needed)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from beetrack.config import ExperimentSetup
from beetrack.server.app import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    app = create_app(tmp_path_factory.mktemp("data"))
    with TestClient(app) as c:  # runs lifespan → starts the job worker
        yield c


def test_full_workflow(client, synthetic):
    assert client.get("/api/health").json()["ok"]
    assert client.get("/").status_code == 200

    e = client.post("/api/experiments", json={"name": "Colony A / day 1", "station": "s1"}).json()
    eid = e["id"]
    assert e["status"] == "no video"

    with open(synthetic["video"], "rb") as f:
        r = client.post(f"/api/experiments/{eid}/videos", files={"file": ("seg1.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    assert r.json()["fps"] == pytest.approx(15)

    # dish was auto-detected on upload; queen cell still missing → warning only
    e = client.get(f"/api/experiments/{eid}").json()
    assert e["setup"]["dish"] is not None
    assert not e["check"]["errors"]

    setup = ExperimentSetup.load(synthetic["setup"]).model_dump(mode="json")
    r = client.put(f"/api/experiments/{eid}/setup", json=setup)
    assert r.status_code == 200 and not r.json()["check"]["errors"]

    # bad config is rejected, good config accepted
    assert client.put(f"/api/experiments/{eid}/config", json={"yaml": "analysis_fps: -1"}).status_code == 422
    assert client.put(f"/api/experiments/{eid}/config", json={"yaml": "analysis_fps: 7.5"}).status_code == 200

    job = client.post(f"/api/experiments/{eid}/analyze").json()
    assert client.post(f"/api/experiments/{eid}/analyze").status_code == 409  # already queued
    deadline = time.time() + 240
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(1)
    assert j["status"] == "done", j

    res = client.get(f"/api/experiments/{eid}/results").json()
    assert res["summary"]["analysed_fps"] == pytest.approx(7.5)
    assert len(res["metrics"]) == 10
    assert {z["name"] for z in res["zones"]} == {"contact", "vicinity"}

    tr = client.get(f"/api/experiments/{eid}/results/trajectories", params={"bee": ["W01", "W02"], "step_s": 1}).json()
    assert set(tr) <= {"W01", "W02"} and tr

    hm = client.get(f"/api/experiments/{eid}/results/heatmap", params={"bins": 20}).json()
    assert len(hm["z"]) == 20

    img = client.get(f"/api/experiments/{eid}/frame", params={"t": 10, "trail_s": 5})
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and img.content[:2] == b"\xff\xd8"

    probe = client.get(f"/api/experiments/{eid}/probe", params={"x": 640, "y": 360}).json()
    assert {"h", "s", "v", "hex"} <= set(probe)

    geo = client.get(f"/api/experiments/{eid}/geometry").json()
    assert geo["dish_radius_mm"] == 75 and geo["queen_cell"]

    for name in ("visits.csv", "bee_metrics.csv", "trajectories.csv", "summary.json"):
        d = client.get(f"/api/experiments/{eid}/download/{name}")
        assert d.status_code == 200, name

    # path annotations: CSV with boxes, and MOT text
    ann = client.get(f"/api/experiments/{eid}/download/annotations.csv")
    assert ann.status_code == 200
    header = ann.text.splitlines()[0].split(",")
    assert {"frame", "bee_id", "x_px", "y_px", "bbox_left", "bbox_width", "head_x_px"} <= set(header)
    mot = client.get(f"/api/experiments/{eid}/download/annotations_mot.txt").text.splitlines()
    assert mot and len(mot[0].split(",")) == 10 and int(mot[0].split(",")[0]) >= 1

    # result videos: not there yet → 404; render jobs (with options) → mp4s
    for name in ("annotated.mp4", "paths.mp4", "heatmap.mp4"):
        assert client.get(f"/api/experiments/{eid}/download/{name}").status_code == 404
    jobs = {
        "annotated": client.post(f"/api/experiments/{eid}/render", json={"video": "annotated", "step_s": 0.5, "trail_s": 60}).json(),
        "paths": client.post(f"/api/experiments/{eid}/render", json={"video": "paths", "step_s": 1, "trail_s": -1, "fps": 10}).json(),
        "heatmap": client.post(f"/api/experiments/{eid}/render", json={"video": "heatmap", "step_s": 1, "trail_s": -1,
                                                                        "bees": ["W01", "W02"]}).json(),
    }
    assert all(j["kind"] == "render" for j in jobs.values())
    assert client.post(f"/api/experiments/{eid}/render", json={"video": "paths"}).status_code == 409  # same kind busy
    assert client.post(f"/api/experiments/{eid}/render", json={"video": "nope"}).status_code == 422
    deadline = time.time() + 300
    for kind, rj in jobs.items():
        while time.time() < deadline:
            j = client.get(f"/api/jobs/{rj['id']}").json()
            if j["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(1)
        assert j["status"] == "done", (kind, j)
    vids = client.get(f"/api/experiments/{eid}/results").json()["videos"]
    assert vids["annotated"]["options"]["description"] == "0.5 s/step · 60 s trail · 15 fps"
    assert vids["paths"]["options"]["trail_s"] == -1 and vids["paths"]["options"]["fps"] == 10
    assert vids["heatmap"]["options"]["bees"] == ["W01", "W02"]
    for kind in ("annotated", "paths", "heatmap"):
        assert vids[kind]["exists"] and vids[kind]["size_bytes"] > 5_000, kind
        v = client.get(f"/api/experiments/{eid}/download/{kind}.mp4")
        assert v.status_code == 200 and v.content[4:8] == b"ftyp", kind
    # the render job must not hide the analysis results
    assert client.get(f"/api/experiments/{eid}/results").json()["job_id"] == job["id"]

    assert client.delete(f"/api/experiments/{eid}").status_code == 204
    assert client.get(f"/api/experiments/{eid}").status_code == 404


def test_upload_rejects_non_video(client):
    eid = client.post("/api/experiments", json={"name": "bad upload"}).json()["id"]
    r = client.post(f"/api/experiments/{eid}/videos", files={"file": ("notes.mp4", b"not a video", "video/mp4")})
    assert r.status_code == 400


def test_analyze_requires_setup(client):
    eid = client.post("/api/experiments", json={"name": "empty"}).json()["id"]
    assert client.post(f"/api/experiments/{eid}/analyze").status_code == 409
