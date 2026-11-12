"""Browser tests for the web app: every page and every experiment tab.

A real server runs on a free local port and headless Chromium drives it like
a user would: create an experiment, upload a video, set up the dish, queen cell
and bees on the canvas, run the analysis, read the results, explore the video,
delete. Any JavaScript error in the browser console fails the run.

Run only these:   pytest tests/test_ui.py
Skip them:        pytest -m "not ui"
Watch them:       pytest tests/test_ui.py --headed --slowmo 300

The tests in this file run **in order** and share one browser page, because
each step builds on the previous one (as a user's session would).
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

import uvicorn  # noqa: E402

from beetrack.config import DEFAULT_PALETTE, ExperimentSetup  # noqa: E402
from beetrack.server.app import create_app  # noqa: E402
from beetrack.synthetic import SyntheticArena  # noqa: E402

pytestmark = pytest.mark.ui

W, H = 960, 540
DEFAULT_COLOURS = [c.name for c in DEFAULT_PALETTE[:10]]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def video(tmp_path_factory):
    out = tmp_path_factory.mktemp("ui_video")
    arena = SyntheticArena(width=W, height=H, seed=5)
    paths = arena.generate(out, duration_s=20)
    return {"path": paths["video"], "setup": ExperimentSetup.load(paths["setup"]), "arena": arena}


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    app = create_app(tmp_path_factory.mktemp("ui_data"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    assert srv.started, "server did not start"
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(10)


@pytest.fixture(scope="module")
def ctx(browser, server):
    """One page for the whole file, plus a collector for browser-side errors."""
    context = browser.new_context(viewport={"width": 1400, "height": 1000}, base_url=server)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.set_default_timeout(15_000)
    state = {"page": page, "errors": errors, "base": server}
    yield state
    context.close()


def _real_errors(errors: list[str]) -> list[str]:
    """Browser errors that indicate a bug.

    Ignored: web fonts (from Google, may be unreachable offline), and the browser's own
    "Failed to load resource … 400/422" lines for the validation errors these tests
    trigger on purpose (bad upload, invalid config). 5xx responses and JS exceptions always count.
    """
    ignore = ("fonts.g", "ERR_INTERNET_DISCONNECTED", "ERR_NAME_NOT_RESOLVED",
              "status of 400 (Bad Request)", "status of 422 (Unprocessable Entity)")
    return [e for e in errors if not any(k in e for k in ignore)]


def _api(ctx, path, method="GET", body=None):
    r = ctx["page"].request.fetch(ctx["base"] + "/api" + path, method=method,
                                  data=json.dumps(body) if body is not None else None,
                                  headers={"Content-Type": "application/json"} if body is not None else None)
    assert r.ok, f"{method} {path}: {r.status} {r.text()}"
    return r.json() if r.status != 204 else None


def _canvas_click(page, x_px: float, y_px: float, dbl: bool = False):
    """Click the setup canvas at *video* pixel coordinates."""
    box = page.locator(".stage canvas").bounding_box()
    x = box["x"] + x_px * box["width"] / W
    y = box["y"] + y_px * box["height"] / H
    (page.mouse.dblclick if dbl else page.mouse.click)(x, y)


def _screen(page, x_px: float, y_px: float) -> tuple[float, float]:
    box = page.locator(".stage canvas").bounding_box()
    return box["x"] + x_px * box["width"] / W, box["y"] + y_px * box["height"] / H


def _canvas_drag(page, a, b, steps: int = 8):
    """Press at video pixel ``a``, drag to ``b``, release."""
    page.mouse.move(*_screen(page, *a))
    page.mouse.down()
    page.mouse.move(*_screen(page, *b), steps=steps)
    page.mouse.up()


def _cell(ctx, eid=None):
    return _api(ctx, f"/experiments/{eid or ctx['exp_id']}")["setup"]["queen_cell"]


def _save_setup(page):
    page.get_by_role("button", name="Save setup").click()
    _toast(page, "Setup saved")
    expect(page.locator(".dirty-badge")).to_be_hidden()


def _set_range(page, selector: str, value: float):
    page.locator(selector).evaluate(
        "(el, v) => { el.value = v; el.dispatchEvent(new Event('input')); el.dispatchEvent(new Event('change')); }", value)


def _bee_colours(page) -> list[str]:
    return page.locator("tr.bee-row select").evaluate_all("els => els.map(e => e.value)")


def _toast(page, text: str | re.Pattern):
    expect(page.locator(".toast").filter(has_text=text).first).to_be_visible()


# --------------------------------------------------------------------------- #
# shell & static pages
# --------------------------------------------------------------------------- #
def test_shell_loads_with_navigation(ctx):
    page = ctx["page"]
    page.goto("/")
    expect(page.locator(".brand")).to_contain_text("beetrack")
    for label in ("Experiments", "New experiment", "Analysis queue", "How it works"):
        expect(page.locator("nav a", has_text=label)).to_be_visible()
    expect(page.locator("#version")).to_have_text(re.compile(r"^v\d+\.\d+\.\d+$"))
    assert page.evaluate("typeof Plotly") == "object", "vendored Plotly should load without internet"


def test_empty_experiment_list(ctx):
    page = ctx["page"]
    page.goto("/#/")
    expect(page.get_by_text("No experiments yet")).to_be_visible()
    expect(page.locator("nav a.active")).to_have_text(re.compile("Experiments"))


def test_help_page(ctx):
    page = ctx["page"]
    page.goto("/#/help")
    expect(page.get_by_role("heading", name="How it works")).to_be_visible()
    expect(page.locator(".pipeline-steps > div")).to_have_count(6)
    expect(page.get_by_text("2 · Read dot")).to_be_visible()


def test_theme_toggle(ctx):
    page = ctx["page"]
    page.goto("/#/")
    before = page.evaluate("document.documentElement.dataset.theme || ''")
    page.locator("#themeToggle").click()
    after = page.evaluate("document.documentElement.dataset.theme")
    assert after in ("light", "dark") and after != before
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.locator("#themeToggle").click()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != bg


# --------------------------------------------------------------------------- #
# new experiment
# --------------------------------------------------------------------------- #
def test_new_experiment_requires_a_name(ctx):
    page = ctx["page"]
    page.goto("/#/new")
    page.get_by_role("button", name="Create experiment").click()
    # browser-native "required" validation keeps us on the form
    expect(page).to_have_url(re.compile("#/new$"))


def test_create_experiment(ctx):
    page = ctx["page"]
    page.goto("/#/new")
    page.get_by_label("Name").fill("UI test colony")
    page.get_by_label("Station").fill("s1")
    page.get_by_label("Notes").fill("created by the browser test")
    page.get_by_role("button", name="Create experiment").click()
    expect(page).to_have_url(re.compile(r"#/exp/\d+/overview$"))
    ctx["exp_id"] = int(re.search(r"#/exp/(\d+)/", page.url).group(1))
    expect(page.locator("h1")).to_have_text("UI test colony")
    expect(page.locator(".page-head .pill")).to_have_text("no video")


# --------------------------------------------------------------------------- #
# overview tab
# --------------------------------------------------------------------------- #
def test_overview_checklist_before_upload(ctx):
    page = ctx["page"]
    expect(page.locator(".alert.info", has_text="Upload the recording")).to_be_visible()
    expect(page.locator(".dropzone")).to_be_visible()


def test_overview_upload_video(ctx, video):
    page = ctx["page"]
    page.locator('input[type="file"]').set_input_files(str(video["path"]))
    _toast(page, "Upload finished")
    row = page.locator(".card", has_text="Video segments").locator("tbody tr")
    expect(row).to_have_count(1)
    expect(row.first).to_contain_text("synthetic.mp4")
    expect(row.first).to_contain_text(f"{W}×{H}")
    expect(row.first).to_contain_text("15.00 fps")
    # dish auto-detected on upload → no dish error, only the queen-cell warning
    expect(page.locator(".alert.error")).to_have_count(0)
    expect(page.locator(".alert.warn", has_text="queen-cell")).to_be_visible()


def test_overview_rejects_non_video(ctx, tmp_path):
    page = ctx["page"]
    bad = tmp_path / "notes.mp4"
    bad.write_bytes(b"this is not a video")
    page.locator('input[type="file"]').set_input_files(str(bad))
    _toast(page, "not a readable video")
    expect(page.locator(".card", has_text="Video segments").locator("tbody tr")).to_have_count(1)


def test_overview_edit_details_persist(ctx):
    page = ctx["page"]
    card = page.locator(".card", has_text="Details")
    card.get_by_label("Name").fill("UI test colony (renamed)")
    card.get_by_role("button", name="Save details").click()
    _toast(page, "Saved")
    page.reload()
    expect(page.locator("h1")).to_have_text("UI test colony (renamed)")


# --------------------------------------------------------------------------- #
# setup tab
# --------------------------------------------------------------------------- #
def _open_setup(ctx):
    page = ctx["page"]
    page.goto(f"/#/exp/{ctx['exp_id']}/setup")
    page.reload()  # same-URL navigation doesn't re-render a single-page app; force a fresh page
    expect(page.locator("tr.bee-row").first).to_be_visible()
    img = page.locator(".stage img")
    expect(img).to_be_visible()
    page.wait_for_function("() => { const i = document.querySelector('.stage img'); return i && i.complete && i.naturalWidth > 0; }")
    return page


def test_setup_frame_and_dish_overlay(ctx):
    page = _open_setup(ctx)
    assert page.locator(".stage img").evaluate("i => i.naturalWidth") == W
    # the canvas draws the auto-detected dish: some non-transparent pixels on the overlay
    painted = page.locator(".stage canvas").evaluate(
        "c => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;"
        " for (let i = 3; i < d.length; i += 4) if (d[i]) n++; return n; }")
    assert painted > 100


def test_setup_bee_dropdowns_show_each_bees_own_colour(ctx):
    """Regression: every dropdown used to show 'white' regardless of the bee's colour."""
    page = _open_setup(ctx)
    expect(page.locator("tr.bee-row")).to_have_count(10)
    assert _bee_colours(page) == DEFAULT_COLOURS
    # each row's swatch matches its dropdown
    swatches = page.locator("tr.bee-row .code").evaluate_all("els => els.map(e => e.title)")
    assert swatches == DEFAULT_COLOURS


def _rgb(hexs: str) -> str:
    return "rgb({}, {}, {})".format(*(int(hexs[i:i + 2], 16) for i in (1, 3, 5)))


def test_setup_each_bee_is_shown_in_its_dot_colour(ctx):
    """The swatch next to each bee is its paint colour, and there is no unrelated 'ID colour' any more."""
    page = _open_setup(ctx)
    shown = page.locator("tr.bee-row .code .swatch").evaluate_all("els => els.map(e => getComputedStyle(e).backgroundColor)")
    assert shown == [_rgb(c.display) for c in DEFAULT_PALETTE[:10]]
    page.locator("tr.bee-row select").first.select_option("blue")  # live update when the colour changes
    blue = next(c.display for c in DEFAULT_PALETTE if c.name == "blue")
    assert page.locator("tr.bee-row .code .swatch").first.evaluate("e => getComputedStyle(e).backgroundColor") == _rgb(blue)


def test_version_mismatch_shows_a_banner(ctx):
    page = ctx["page"]
    expect(page.locator(".version-banner")).to_have_count(0)

    def old_server(route):
        route.fulfill(json={"ok": True, "version": "0.0.1", "data_dir": "/tmp"})

    page.route("**/api/health", old_server)
    try:
        page.reload()
        expect(page.locator(".version-banner")).to_contain_text("server v0.0.1")
    finally:
        page.unroute("**/api/health")
    page.reload()
    expect(page.locator(".version-banner")).to_have_count(0)


def test_setup_defaults_button_restores_distinct_colours(ctx):
    page = _open_setup(ctx)
    page.locator("tr.bee-row select").nth(3).select_option("white")
    page.get_by_role("button", name="Defaults").click()
    assert _bee_colours(page) == DEFAULT_COLOURS


def test_setup_legacy_two_spot_bees_show_thorax_colour(ctx):
    """Setups saved by v0.1 (thorax/abdomen) must still display correctly."""
    page = ctx["page"]

    def legacy(route):
        resp = route.fetch()
        data = resp.json()
        data["setup"]["bees"] = [{"bee_id": "OLD1", "thorax": "blue", "abdomen": "red", "label": ""},
                                 {"bee_id": "OLD2", "thorax": "pink", "abdomen": None, "label": ""}]
        route.fulfill(response=resp, json=data)

    pattern = re.compile(rf".*/api/experiments/{ctx['exp_id']}$")
    page.route(pattern, legacy)
    try:
        _open_setup(ctx)
        assert _bee_colours(page) == ["blue", "pink"]
    finally:
        page.unroute(pattern)


def test_setup_duplicate_colour_is_reported_and_fixable(ctx):
    page = _open_setup(ctx)
    page.locator("tr.bee-row select").nth(1).select_option("white")  # W02 = W01's colour
    page.get_by_role("button", name="Save setup").click()
    expect(page.locator(".alert.error", has_text="both have a white dot")).to_be_visible()
    page.locator("tr.bee-row select").nth(1).select_option(DEFAULT_COLOURS[1])
    page.get_by_role("button", name="Save setup").click()
    expect(page.locator(".alert.error")).to_have_count(0)
    assert [b["color"] for b in _api(ctx, f"/experiments/{ctx['exp_id']}")["setup"]["bees"]] == DEFAULT_COLOURS


def test_setup_remove_and_add_bee_reuses_free_colour(ctx):
    page = _open_setup(ctx)
    page.locator("tr.bee-row").nth(4).get_by_role("button", name="✕").click()
    expect(page.locator("tr.bee-row")).to_have_count(9)
    page.get_by_role("button", name="＋ Add").click()
    expect(page.locator("tr.bee-row")).to_have_count(10)
    assert _bee_colours(page)[-1] == DEFAULT_COLOURS[4]
    page.get_by_role("button", name="＋ Add").click()  # all 10 colours used → refused with a message
    _toast(page, "Every palette colour is already used")
    expect(page.locator("tr.bee-row")).to_have_count(10)


def test_setup_dish_from_three_points(ctx, video):
    page = _open_setup(ctx)
    a = video["arena"]
    page.get_by_role("button", name="◯ Dish: 3 points").click()
    for ang in (0.3, 2.2, 4.1):
        import math
        _canvas_click(page, a.cx + a.r_px * math.cos(ang), a.cy + a.r_px * math.sin(ang))
    _toast(page, "Dish set from 3 points")
    dish = _api(ctx, f"/experiments/{ctx['exp_id']}")["setup"]["dish"]
    assert abs(dish["radius_px"] - a.r_px) < 4 and abs(dish["center_px"][0] - a.cx) < 4


def test_setup_auto_detect_dish(ctx, video):
    page = _open_setup(ctx)
    page.get_by_role("button", name="✦ Auto-detect dish").click()
    _toast(page, "Dish detected")


# ---- queen-cell shape editor ------------------------------------------------ #
def test_setup_ellipse_draw_by_dragging(ctx):
    page = _open_setup(ctx)
    page.get_by_role("button", name="⬭ Queen cell: ellipse").click()
    expect(page.locator(".hint-bar")).to_contain_text("Drag from one end")
    _canvas_drag(page, (480, 120), (480, 200))          # a vertical cell, 80 px long
    expect(page.locator(".dirty-badge")).to_be_visible()
    expect(page.locator(".cell-info")).to_contain_text("ellipse")
    expect(page.locator(".cell-info")).to_contain_text("mm")
    _save_setup(page)
    s = _cell(ctx)["shape"]
    assert s["type"] == "ellipse"
    assert abs(s["cx"] - 480) < 2 and abs(s["cy"] - 160) < 2 and abs(s["length_px"] - 80) < 3
    assert abs(s["angle_deg"] - 90) < 3
    assert len(_cell(ctx)["polygon_px"]) == 48  # outline regenerated by the server


def test_setup_ellipse_move(ctx):
    page = _open_setup(ctx)
    before = _cell(ctx)["shape"]
    _canvas_drag(page, (before["cx"], before["cy"]), (before["cx"] + 30, before["cy"] + 15))
    _save_setup(page)
    s = _cell(ctx)["shape"]
    assert abs(s["cx"] - before["cx"] - 30) < 2 and abs(s["cy"] - before["cy"] - 15) < 2
    assert abs(s["length_px"] - before["length_px"]) < 1  # moving doesn't resize


def test_setup_ellipse_resize_and_rotate_by_end_handle(ctx):
    page = _open_setup(ctx)
    s0 = _cell(ctx)["shape"]
    end2 = (s0["cx"], s0["cy"] + s0["length_px"] / 2)  # vertical ellipse: end2 is the lower end
    _canvas_drag(page, end2, (end2[0], end2[1] + 20))  # 20 px longer
    _save_setup(page)
    s1 = _cell(ctx)["shape"]
    assert abs(s1["length_px"] - s0["length_px"] - 20) < 3
    end2 = (s1["cx"], s1["cy"] + s1["length_px"] / 2)
    _canvas_drag(page, end2, (end2[0] + s1["length_px"] / 2, end2[1] - s1["length_px"] / 2))  # swing to ~45°
    _save_setup(page)
    s2 = _cell(ctx)["shape"]
    assert 30 < s2["angle_deg"] < 60, s2


def test_setup_ellipse_width_handle(ctx):
    page = _open_setup(ctx)
    import math
    s = _cell(ctx)["shape"]
    a = math.radians(s["angle_deg"])
    v = (-math.sin(a), math.cos(a))
    side = (s["cx"] + v[0] * s["width_px"] / 2, s["cy"] + v[1] * s["width_px"] / 2)
    _canvas_drag(page, side, (side[0] + v[0] * 10, side[1] + v[1] * 10))  # 10 px further out
    _save_setup(page)
    assert abs(_cell(ctx)["shape"]["width_px"] - s["width_px"] - 20) < 3  # both sides grow


def test_setup_ellipse_keyboard_nudge_and_escape(ctx):
    page = _open_setup(ctx)
    s0 = _cell(ctx)["shape"]
    page.locator(".stage canvas").focus()
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    page.keyboard.press("Shift+ArrowDown")
    _save_setup(page)
    s1 = _cell(ctx)["shape"]
    assert abs(s1["cx"] - s0["cx"] - 3) < 0.2 and abs(s1["cy"] - s0["cy"] - 10) < 0.2
    page.get_by_role("button", name="⬭ Queen cell: ellipse").click()
    expect(page.get_by_role("button", name="⬭ Queen cell: ellipse")).to_have_class(re.compile("active"))
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="⬭ Queen cell: ellipse")).not_to_have_class(re.compile("active"))


def test_setup_ellipse_survives_reload_and_stays_editable(ctx):
    page = _open_setup(ctx)
    expect(page.locator(".cell-info")).to_contain_text("ellipse")
    s0 = _cell(ctx)["shape"]
    _canvas_drag(page, (s0["cx"], s0["cy"]), (s0["cx"] - 10, s0["cy"]))
    _save_setup(page)
    assert abs(_cell(ctx)["shape"]["cx"] - s0["cx"] + 10) < 2


def test_setup_unsaved_changes_badge(ctx):
    page = _open_setup(ctx)
    expect(page.locator(".dirty-badge")).to_be_hidden()
    page.get_by_role("button", name="Clear cell").click()
    expect(page.locator(".dirty-badge")).to_be_visible()
    expect(page.locator(".cell-info")).to_contain_text("No queen cell yet")
    page.reload()  # not saved → the cell is still there
    expect(page.locator(".cell-info")).to_contain_text("ellipse")


def test_setup_draw_queen_cell(ctx, video):
    page = _open_setup(ctx)
    poly = video["setup"].queen_cell.polygon_px
    page.get_by_role("button", name="⬠ Queen cell: outline").click()
    expect(page.locator(".hint-bar")).to_contain_text("queen cell outline")
    pts = poly[::4]
    for x, y in pts:
        _canvas_click(page, x, y)
    _canvas_click(page, *pts[0])  # click the first point again → closes the polygon
    expect(page.locator(".hint-bar")).to_contain_text("Queen cell set")
    page.get_by_role("button", name="Save setup").click()
    _toast(page, "Setup saved")
    expect(page.locator(".alert.ok", has_text="Setup is complete")).to_be_visible()
    expect(page.locator(".alert.warn", has_text="queen-cell")).to_have_count(0)
    saved = _api(ctx, f"/experiments/{ctx['exp_id']}")["setup"]["queen_cell"]["polygon_px"]
    assert len(saved) == len(pts)


def test_setup_copy_cell_to_another_experiment_and_drag_a_corner(ctx, video):
    page = ctx["page"]
    eid = _api(ctx, "/experiments", "POST", {"name": "Copy target"})["id"]
    r = page.request.post(f"{ctx['base']}/api/experiments/{eid}/videos",
                          multipart={"file": {"name": "seg.mp4", "mimeType": "video/mp4", "buffer": video["path"].read_bytes()}})
    assert r.ok, r.text()
    page.goto(f"/#/exp/{eid}/setup")
    page.reload()
    expect(page.locator(".cell-info")).to_contain_text("No queen cell yet")
    sel = page.locator("select.copy-cell")
    expect(sel.locator(f"option[value='{ctx['exp_id']}']")).to_have_count(1)
    sel.select_option(str(ctx["exp_id"]))
    _toast(page, re.compile("Queen cell and .* copied from"))
    _save_setup(page)
    src, dst = _cell(ctx), _cell(ctx, eid)
    assert dst["polygon_px"] == src["polygon_px"]  # same video size → identical
    # outline cells: drag one corner
    x, y = dst["polygon_px"][0]
    _canvas_drag(page, (x, y), (x + 12, y - 6))
    _save_setup(page)
    moved = _cell(ctx, eid)["polygon_px"]
    assert abs(moved[0][0] - x - 12) < 2 and abs(moved[0][1] - y + 6) < 2
    assert moved[1:] == dst["polygon_px"][1:]  # only that corner changed
    _api(ctx, f"/experiments/{eid}", "DELETE")


def test_setup_ignore_area_draw_rename_delete(ctx, video):
    page = _open_setup(ctx)
    a = video["arena"]
    # draw a small ignore area near the rim, where no bee path matters for the later tests
    x, y = a.cx - a.r_px * 0.8, a.cy + a.r_px * 0.35
    page.get_by_role("button", name="▨ Ignore area: ellipse").click()
    _canvas_drag(page, (x - 20, y), (x + 20, y))
    expect(page.locator(".cell-info")).to_contain_text("Ignore area")
    name = page.get_by_label("ignore area 1 name")
    name.fill("food")
    name.dispatch_event("change")
    _save_setup(page)
    areas = _api(ctx, f"/experiments/{ctx['exp_id']}")["setup"]["ignore_areas"]
    assert len(areas) == 1 and areas[0]["name"] == "food" and areas[0]["shape"]["type"] == "ellipse"
    # a second one, then delete it with the keyboard
    page.get_by_role("button", name="▨ Ignore area: ellipse").click()
    _canvas_drag(page, (x - 20, y - 60), (x + 20, y - 60))
    expect(page.get_by_label("ignore area 2 name")).to_be_visible()
    page.locator(".stage canvas").focus()
    page.keyboard.press("Delete")
    expect(page.get_by_label("ignore area 2 name")).to_have_count(0)
    _save_setup(page)
    assert len(_api(ctx, f"/experiments/{ctx['exp_id']}")["setup"]["ignore_areas"]) == 1
    # the cell is still selectable and editable after working with areas
    s = _cell(ctx)["polygon_px"]
    assert len(s) >= 3


def test_setup_find_marks_in_the_video(ctx, video):
    """Colour discovery on a separate experiment: find marks → tick → assign → use → saved palette."""
    page = ctx["page"]
    eid = _api(ctx, "/experiments", "POST", {"name": "Discovery"})["id"]
    r = page.request.post(f"{ctx['base']}/api/experiments/{eid}/videos",
                          multipart={"file": {"name": "seg.mp4", "mimeType": "video/mp4", "buffer": video["path"].read_bytes()}})
    assert r.ok, r.text()
    page.goto(f"/#/exp/{eid}/setup")
    page.reload()
    expect(page.locator(".palette-note")).to_contain_text("standard palette")
    page.get_by_role("button", name="✦ Find the marks in the video").click()
    cards = page.locator(".mark-card")
    expect(cards.first).to_be_visible(timeout=60_000)
    assert cards.count() >= 6
    expect(cards.first.locator(".mark-examples img").first).to_be_visible()
    page.get_by_label("number of bees").fill("10")
    page.get_by_label("number of bees").dispatch_event("change")
    page.get_by_role("button", name="Use these marks").click()
    expect(page.locator(".discover-box .alert.ok")).to_contain_text("bees from")
    expect(page.locator(".palette-note")).to_contain_text("learned from this video")
    n_rows = page.locator("tr.bee-row").count()
    assert n_rows >= 6
    _save_setup(page)
    st = _api(ctx, f"/experiments/{eid}")["setup"]
    assert st["palette"] and all(c["labs"] for c in st["palette"]) and st["mark_model"]["cuticle_hue_deg"] > 0
    assert len(st["bees"]) == n_rows and st["n_bees"] == 10 and not _api(ctx, f"/experiments/{eid}")["check"]["errors"]
    # dropdowns offer the learned colours
    opts = page.locator("tr.bee-row select").first.locator("option").all_text_contents()
    assert set(opts) == {c["name"] for c in st["palette"]}
    # identity threshold inputs are saved with the setup
    page.get_by_label("minimum mark readings").fill("4")
    page.get_by_label("minimum mark readings").dispatch_event("change")
    _save_setup(page)
    assert _api(ctx, f"/experiments/{eid}")["setup"]["id_min_votes"] == 4
    # back to the standard palette
    page.get_by_role("link", name="Back to the standard palette").click()
    _save_setup(page)
    assert _api(ctx, f"/experiments/{eid}")["setup"]["palette"] is None
    _api(ctx, f"/experiments/{eid}", "DELETE")


def test_setup_colour_probe(ctx, video):
    page = _open_setup(ctx)
    page.get_by_role("button", name="⊙ Colour probe").click()
    _canvas_click(page, video["arena"].cx, video["arena"].cy + 100)
    expect(page.locator(".probe")).to_contain_text(re.compile(r"H \d+ +S \d+ +V \d+"))


def test_setup_frame_slider(ctx):
    page = _open_setup(ctx)
    _set_range(page, ".player input[type=range]", 12)
    expect(page.locator(".player .mono")).to_have_text("0:00:12")
    page.wait_for_function("() => document.querySelector('.stage img').src.includes('t=12')")


# --------------------------------------------------------------------------- #
# analysis tab
# --------------------------------------------------------------------------- #
def test_analysis_config_editor(ctx):
    page = ctx["page"]
    page.goto(f"/#/exp/{ctx['exp_id']}/analysis")
    ta = page.locator("textarea")
    page.get_by_role("button", name="Load defaults").click()
    expect(ta).to_have_value(re.compile("analysis_fps: 15.0"))
    ta.fill("analysis_fps: -1")
    page.get_by_role("button", name="Save", exact=True).click()
    _toast(page, "invalid config")
    ta.fill("")
    page.get_by_role("button", name="Save", exact=True).click()
    _toast(page, "Configuration saved")


def test_analysis_run_to_completion(ctx):
    page = ctx["page"]
    page.goto(f"/#/exp/{ctx['exp_id']}/analysis")
    run = page.get_by_role("button", name="▶ Analyse recording")
    expect(run).to_be_enabled()
    run.click()
    _toast(page, "Analysis queued")
    expect(page.locator(".progress").first).to_be_visible()
    expect(page.locator(".alert.ok", has_text="Finished")).to_be_visible(timeout=180_000)
    page.reload()
    expect(page.locator(".card", has_text="History").locator("tbody tr").first).to_contain_text("done")
    expect(page.locator(".page-head .pill")).to_have_text("done")


# --------------------------------------------------------------------------- #
# results tab
# --------------------------------------------------------------------------- #
def test_results_kpis_and_charts(ctx):
    page = ctx["page"]
    page.goto(f"/#/exp/{ctx['exp_id']}/results")
    expect(page.locator(".kpi")).to_have_count(6)
    expect(page.locator(".kpi .label", has_text="Visits").first).to_be_visible()
    page.wait_for_function("() => document.querySelectorAll('.js-plotly-plot').length >= 4")
    expect(page.locator(".chart-fallback")).to_have_count(0)


def test_results_charts_use_dot_colours(ctx):
    page = ctx["page"]
    bees = _api(ctx, f"/experiments/{ctx['exp_id']}")["setup"]["bees"]
    pal = {c.name: c.display for c in DEFAULT_PALETTE}
    expected = ["#b9bcc2" if b["color"] == "white" else pal[b["color"]] for b in bees]
    bar = page.locator(".card", has_text="Visits per bee").locator(".js-plotly-plot")
    assert bar.evaluate("gd => gd.data[0].marker.color") == expected


def test_results_bees_at_cell_chart(ctx):
    page = ctx["page"]
    expect(page.get_by_role("heading", name="Bees at the cell over time")).to_be_visible()
    chart = page.locator(".card", has_text="Bees at the cell over time").locator(".js-plotly-plot")
    peak = chart.evaluate("gd => Math.max(...gd.data[0].y)")
    assert 1 <= peak <= 10


def test_results_detection_balance_card(ctx):
    page = ctx["page"]
    card = page.locator(".balance-card")
    expect(card).to_be_visible()
    expect(card).to_contain_text("bees per frame for 10 in the dish")
    expect(card.locator(".js-plotly-plot")).to_be_visible()


def test_results_show_identity_certainty(ctx):
    page = ctx["page"]
    head = page.locator(".card", has_text="Per-bee summary").locator("th", has_text="ID certainty")
    expect(head).to_be_visible()
    cell = page.locator(".card", has_text="Per-bee summary").locator("tbody tr").first.locator("td").last
    expect(cell).to_have_text(re.compile(r"^\d+%$"))
    expect(page.locator(".card", has_text="All visits").locator("th", has_text="ID certainty")).to_be_visible()
    expect(page.locator(".setup-changed")).to_have_count(0)


def test_results_zone_switch(ctx):
    page = ctx["page"]
    contact = page.locator("button[data-zone=contact]")
    vicinity = page.locator("button[data-zone=vicinity]")
    expect(contact).to_have_class(re.compile("active"))
    vicinity.click()
    expect(vicinity).to_have_class(re.compile("active"))
    expect(page.locator(".kpi .hint", has_text="vicinity zone")).to_be_visible()
    contact.click()
    expect(page.locator(".kpi .hint", has_text="contact zone")).to_be_visible()


def test_results_tables(ctx):
    page = ctx["page"]
    metrics = page.locator(".card", has_text="Per-bee summary").locator("tbody tr")
    expect(metrics).to_have_count(10)
    # sortable: click "Visits" twice, the table re-renders without errors
    head = page.locator(".card", has_text="Per-bee summary").locator("th", has_text="Visits").first
    head.click()
    head.click()
    expect(metrics).to_have_count(10)
    visits = page.locator(".card", has_text="All visits").locator("tbody tr")
    assert visits.count() > 0, "the synthetic bees visit the cell, so visits are expected"


def test_results_downloads(ctx):
    page = ctx["page"]
    links = page.locator(".card", has_text="Per-bee summary").locator("a.btn[href*='/download/']")
    assert links.count() == 8
    for href in links.evaluate_all("els => els.map(e => e.getAttribute('href'))"):
        r = page.request.get(ctx["base"] + href)
        assert r.ok and len(r.body()) > 0, href


def _render_in_ui(page, ctx, kind: str):
    card = page.locator(".video-card")
    card.locator(f"button[data-video={kind}]").click()
    expect(card.locator(f"button[data-video={kind}]")).to_have_class(re.compile("active"))
    card.locator("button.render-video").click()
    expect(card.locator("video")).to_be_visible(timeout=180_000)
    page.wait_for_function("() => { const v = document.querySelector('.video-card video'); return v && v.readyState >= 1 && v.duration > 0; }",
                           timeout=30_000)
    href = card.get_by_role("link", name=re.compile(f"Download {kind} video")).get_attribute("href")
    r = page.request.get(ctx["base"] + href)
    assert r.ok and r.body()[4:8] == b"ftyp"
    return card


def test_results_video_options_and_estimate(ctx):
    page = ctx["page"]
    card = page.locator(".video-card")
    expect(card.locator("button[data-video]")).to_have_count(3)
    est = card.locator(".video-estimate")
    before = est.text_content()
    card.get_by_label("step").select_option("2")
    expect(est).not_to_have_text(before)
    expect(est).to_contain_text("faster than real time")
    card.get_by_label("step").select_option("0")
    expect(est).to_contain_text("about real time")


def test_results_render_annotated_video_with_step_and_trail(ctx):
    page = ctx["page"]
    card = page.locator(".video-card")
    card.get_by_label("step").select_option("0.5")
    card.get_by_label("trail").select_option("60")
    card = _render_in_ui(page, ctx, "annotated")
    expect(card.locator(".video-made-with")).to_contain_text("60 s trail")


def test_results_render_paths_video_entire_path(ctx):
    page = ctx["page"]
    card = page.locator(".video-card")
    card.locator("button[data-video=paths]").click()
    card.get_by_label("step").select_option("1")
    card.get_by_label("trail").select_option("-1")
    card.get_by_label("playback fps").select_option("10")
    card = _render_in_ui(page, ctx, "paths")
    expect(card.locator(".video-made-with")).to_contain_text("entire path")
    expect(card.locator(".video-made-with")).to_contain_text("10 fps")


def test_results_render_heatmap_video_for_some_bees(ctx):
    page = ctx["page"]
    card = page.locator(".video-card")
    card.locator("button[data-video=heatmap]").click()
    expect(card.get_by_label("window")).to_be_visible()  # heatmap: "Window" instead of "Trail"
    card.get_by_label("window").select_option("60")
    card.get_by_role("button", name="W02", exact=True).click()  # leave W02 out
    card = _render_in_ui(page, ctx, "heatmap")
    expect(card.locator(".video-made-with")).to_contain_text("9 bees")


def test_results_videos_survive_reload(ctx):
    page = ctx["page"]
    page.reload()
    card = page.locator(".video-card")
    for kind in ("annotated", "paths", "heatmap"):
        expect(card.locator(f"button[data-video={kind}]")).to_contain_text("✓")
    expect(card.locator("video")).to_be_visible()


def test_results_visit_link_opens_explorer(ctx):
    page = ctx["page"]
    page.locator(".card", has_text="All visits").locator("a", has_text="view").first.click()
    expect(page).to_have_url(re.compile("/explorer$"))


# --------------------------------------------------------------------------- #
# explorer tab
# --------------------------------------------------------------------------- #
def test_explorer_frame_with_tracks(ctx):
    page = ctx["page"]
    page.goto(f"/#/exp/{ctx['exp_id']}/explorer")
    page.wait_for_function("() => { const i = document.querySelector('.stage img'); return i && i.complete && i.naturalWidth > 0; }")
    assert "overlay=true" in page.locator(".stage img").get_attribute("src")


def test_explorer_slider_and_keyboard(ctx):
    page = ctx["page"]
    _set_range(page, ".player input[type=range]", 10)
    expect(page.locator(".player .mono")).to_have_text("0:00:10")
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("ArrowRight")
    expect(page.locator(".player .mono")).to_have_text("0:00:11")


def test_explorer_play_pause(ctx):
    page = ctx["page"]
    btn = page.get_by_role("button", name=re.compile("Play"))
    btn.click()
    expect(page.get_by_role("button", name=re.compile("Pause"))).to_be_visible()
    page.wait_for_function("() => document.querySelector('.player .mono').textContent !== '0:00:11'", timeout=15_000)
    page.get_by_role("button", name=re.compile("Pause")).click()
    expect(page.get_by_role("button", name=re.compile("Play"))).to_be_visible()


def test_explorer_paths_and_heatmap(ctx):
    page = ctx["page"]
    paths = page.locator(".card", has_text="Paths")
    expect(paths.locator(".js-plotly-plot")).to_be_visible()
    toggle = paths.locator("button", has_text="W05")
    before = "active" in (toggle.get_attribute("class") or "")
    toggle.click()
    assert ("active" in (toggle.get_attribute("class") or "")) != before
    heat = page.locator(".card", has_text="Where bees spend time")
    expect(heat.locator(".js-plotly-plot")).to_be_visible()
    heat.locator("select").select_option("W01")
    page.wait_for_timeout(500)


# --------------------------------------------------------------------------- #
# list, queue, responsive, delete, console
# --------------------------------------------------------------------------- #
def test_results_warn_when_the_setup_was_edited_after_the_analysis(ctx):
    """Old results keep showing the setup they were made with, and say that the setup has changed since."""
    page = ctx["page"]
    eid = ctx["exp_id"]
    before = _api(ctx, f"/experiments/{eid}")["setup"]
    edited = {**before, "n_bees": 12}
    _api(ctx, f"/experiments/{eid}/setup", "PUT", edited)
    try:
        page.goto(f"/#/exp/{eid}/results")
        page.reload()
        expect(page.locator(".setup-changed")).to_contain_text("edited after this analysis")
        expect(page.locator(".card", has_text="Per-bee summary").locator("tbody tr")).to_have_count(10)
    finally:
        _api(ctx, f"/experiments/{eid}/setup", "PUT", before)
    page.reload()
    expect(page.locator(".setup-changed")).to_have_count(0)


def test_setup_nudges_towards_learning_the_marks(ctx):
    page = _open_setup(ctx)
    expect(page.locator(".alert.warn", has_text="built-in list")).to_be_visible()
    expect(page.get_by_label("minimum identity certainty percent")).to_have_value("0")


def test_list_shows_finished_experiment(ctx):
    page = ctx["page"]
    page.goto("/#/")
    row = page.locator("tbody tr", has_text="UI test colony (renamed)")
    expect(row).to_be_visible()
    expect(row.locator(".pill")).to_have_text("done")
    row.click()
    expect(page).to_have_url(re.compile(rf"#/exp/{ctx['exp_id']}$"))


def test_analysis_queue_page(ctx):
    page = ctx["page"]
    page.goto("/#/jobs")
    expect(page.locator("tbody tr").first.locator(".pill")).to_have_text("done")


def test_phone_width_has_no_horizontal_scroll(ctx):
    page = ctx["page"]
    page.set_viewport_size({"width": 390, "height": 844})
    try:
        for route in ("/#/", f"/#/exp/{ctx['exp_id']}/results", "/#/help"):
            page.goto(route)
            page.wait_for_timeout(400)
            overflow = page.evaluate("document.scrollingElement.scrollWidth - window.innerWidth")
            assert overflow <= 1, f"{route} scrolls horizontally by {overflow}px"
    finally:
        page.set_viewport_size({"width": 1400, "height": 1000})


def test_delete_experiment(ctx):
    page = ctx["page"]
    page.goto(f"/#/exp/{ctx['exp_id']}/overview")
    page.locator(".page-head").get_by_role("button", name="Delete").click()
    expect(page.locator("#modal")).to_be_visible()
    page.locator("#modal").get_by_role("button", name="Delete").click()
    _toast(page, "Experiment deleted")
    expect(page.get_by_text("No experiments yet")).to_be_visible()


# --------------------------------------------------------------------------- #
# unmarked mode: a second experiment, paths only
# --------------------------------------------------------------------------- #
def test_unmarked_experiment_end_to_end(ctx, video):
    page = ctx["page"]
    e = _api(ctx, "/experiments", "POST", {"name": "Unmarked colony"})
    ctx["unmarked_id"] = eid = e["id"]
    page.goto(f"/#/exp/{eid}/overview")
    page.reload()
    page.locator('input[type="file"]').set_input_files(str(video["path"]))
    _toast(page, "Upload finished")

    # setup: switch to unmarked, the colour table disappears, the bee count appears
    page.goto(f"/#/exp/{eid}/setup")
    page.reload()
    expect(page.locator("tr.bee-row").first).to_be_visible()
    page.locator("button[data-marking=none]").click()
    expect(page.locator("button[data-marking=none]")).to_have_class(re.compile("active"))
    expect(page.locator("tr.bee-row").first).to_be_hidden()
    expect(page.locator(".unmarked-panel")).to_be_visible()
    page.get_by_label("number of bees").fill("10")
    page.get_by_label("number of bees").dispatch_event("change")
    # queen cell (needed for visits)
    page.get_by_role("button", name="⬠ Queen cell: outline").click()
    pts = video["setup"].queen_cell.polygon_px[::4]
    for x, y in pts:
        _canvas_click(page, x, y)
    _canvas_click(page, *pts[0])
    page.get_by_role("button", name="Save setup").click()
    _toast(page, "Setup saved")
    # bee count entered → closed group: no "anonymous tracks" or "bees in the dish is empty" warnings
    expect(page.locator(".alert.warn", has_text="unmarked bees")).to_have_count(0)
    expect(page.locator(".alert.warn", has_text="Bees in the dish")).to_have_count(0)
    saved = _api(ctx, f"/experiments/{eid}")["setup"]
    assert saved["marking"] == "none" and saved["n_bees"] == 10

    # the choice survives a reload
    page.reload()
    expect(page.locator("button[data-marking=none]")).to_have_class(re.compile("active"))
    expect(page.locator(".unmarked-panel")).to_be_visible()

    # analyse
    page.goto(f"/#/exp/{eid}/analysis")
    page.get_by_role("button", name="▶ Analyse recording").click()
    expect(page.locator(".alert.ok", has_text="Finished")).to_be_visible(timeout=180_000)

    # results: closed group of 10 (unmarked U01…U10), explanation, bees-at-cell chart, per-bee table
    page.goto(f"/#/exp/{eid}/results")
    expect(page.locator(".closed-note")).to_contain_text("exactly 10 identities")
    expect(page.get_by_role("heading", name="Bees at the cell over time")).to_be_visible()
    expect(page.get_by_role("heading", name="Per-bee summary")).to_be_visible()
    rows = page.locator(".card", has_text="Per-bee summary").locator("tbody tr")
    expect(rows).to_have_count(10)
    expect(rows.first.locator("td").first).to_have_text(re.compile(r"U\d{2}"))
    page.wait_for_function("() => document.querySelectorAll('.js-plotly-plot').length >= 4")

    # explorer offers tracks
    page.goto(f"/#/exp/{eid}/explorer")
    paths = page.locator(".card", has_text="Paths")
    expect(paths.locator("button").first).to_have_text(re.compile(r"[TU]\d{2,3}"))
    expect(paths.locator(".js-plotly-plot")).to_be_visible()
    heat = page.locator(".card", has_text="Where bees spend time").locator("select option").first
    expect(heat).to_have_text(re.compile("all (tracks|bees)"))


def test_unmarked_experiment_cleanup(ctx):
    _api(ctx, f"/experiments/{ctx['unmarked_id']}", "DELETE")


def test_no_browser_errors_during_the_session(ctx):
    errs = _real_errors(ctx["errors"])
    assert not errs, "\n".join(errs)
