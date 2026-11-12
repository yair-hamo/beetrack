/* beetrack single-page UI. Plain JS, no build step.
 *
 * Structure
 *   utils      – DOM builder h(), formatting, api(), toast(), modal helpers
 *   router     – hash routes: #/  #/new  #/jobs  #/help  #/exp/:id/:tab
 *   views      – list, new, jobs, help, experiment (overview | setup | analysis | results | explorer)
 *   widgets    – uploader, setup canvas editor, bee registry, job monitor, charts (Plotly)
 */
"use strict";

/* ======================================================================== */
/* utils                                                                    */
/* ======================================================================== */
const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const fmt = {
  dur(s) {
    if (s == null || !isFinite(s)) return "–";
    s = Math.round(s);
    const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    return hh ? `${hh}h ${String(mm).padStart(2, "0")}m` : mm ? `${mm}m ${String(ss).padStart(2, "0")}s` : `${ss}s`;
  },
  clock(s) {
    s = Math.max(0, Math.floor(s || 0));
    const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    return `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  },
  bytes(b) {
    if (!b) return "0 B";
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(b < 10 && i ? 1 : 0)} ${u[i]}`;
  },
  num(v, d = 1) { return v == null || !isFinite(v) ? "–" : Number(v).toFixed(d); },
  pct(v) { return v == null || !isFinite(v) ? "–" : `${Math.round(v * 100)}%`; },
  date(iso) { return iso ? new Date(iso).toLocaleString() : "–"; },
};

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const res = await fetch(`/api${path}`, init);
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : res.statusText;
    if (Array.isArray(msg)) msg = msg.map((e) => `${(e.loc || []).join(".")}: ${e.msg}`).join("; ");
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}` }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? 7000 : 3500);
}
// Handled errors are shown to the user as a toast and logged as warnings (not console errors).
const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, "error"); console.warn(e); } };

function openModal(content) {
  const m = $("#modal"), card = $("#modalCard");
  card.replaceChildren(content);
  m.classList.remove("hidden");
  const close = () => m.classList.add("hidden");
  m.onclick = (e) => { if (e.target === m) close(); };
  return close;
}
function confirmModal(title, text, okLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    let close;
    const done = (v) => { close(); resolve(v); };
    close = openModal(h("div", {},
      h("h2", {}, title), h("p", { class: "muted" }, text),
      h("div", { class: "modal-actions" },
        h("button", { onclick: () => done(false) }, "Cancel"),
        h("button", { class: danger ? "danger" : "primary", onclick: () => done(true) }, okLabel))));
  });
}

const statusClass = (s) => (s || "").replace(/\s+/g, "-");
const pill = (s) => h("span", { class: `pill ${statusClass(s)}` }, s);

/* Every bee is drawn in the colour of its paint dot, everywhere (tables, charts, video overlay).
 * White would vanish on a light page, so it is drawn as light grey. */
const UI_VERSION = "0.3.0";
function dotColor(name) {
  const hex = (App.palette[name] || {}).display || "#999999";
  return name === "white" || /^#f[0-9a-f]f[0-9a-f]f[0-9a-f]$/i.test(hex) ? "#b9bcc2" : hex;
}
const CAT = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];
const beeColor = (bees, id) => {
  const b = bees.find((x) => x.bee_id === id);
  if (b && b.color) return dotColor(b.color);
  const n = parseInt(String(id).replace(/\D/g, ""), 10);  // anonymous track T007 → categorical colour 7
  return CAT[(isNaN(n) ? 0 : n) % CAT.length];
};
/* bees (marked) or tracks (unmarked) to show for a run, from the setup that run used and its metrics */
function subjects(runSetup, metrics) {
  if (runSetup.marking !== "none") {
    const reg = new Set(runSetup.bees.map((b) => b.bee_id));
    const extra = (metrics || []).map((m) => m.bee_id).filter((id) => !reg.has(id)).sort().map((id) => ({ bee_id: id }));
    return { bees: [...runSetup.bees, ...extra], unmarked: false };  // + unmarked members of a closed group (U…)
  }
  const ids = (metrics || []).map((m) => m.bee_id).sort();
  return { bees: ids.map((id) => ({ bee_id: id })), unmarked: true };
}

const App = { defaults: null, palette: {}, timers: new Set() };
function clearTimers() { for (const t of App.timers) clearInterval(t); App.timers.clear(); }

/* palette for swatches/colours: the defaults, plus the marks learned for the current experiment */
function usePalette(learned) {
  App.palette = Object.fromEntries([...App.defaults.palette, ...(learned || [])].map((c) => [c.name, c]));
}

/* bees saved before v0.2 had thorax/abdomen; the dot colour is the thorax colour */
function normalizeBee(b) {
  const { thorax, abdomen, ...rest } = b;
  return { ...rest, color: b.color || thorax || "" };
}

function codeSwatches(bee) {
  const c = bee.color;
  if (!c && bee.bee_id) return h("span", { class: "code", title: "anonymous track" }, h("span", { class: "swatch", style: { background: beeColor([], bee.bee_id), borderRadius: "50%" } }));
  return h("span", { class: "code", title: c || "" },
    c ? h("span", { class: "swatch", style: { background: (App.palette[c] || {}).display || "#999" } }) : null);
}

/* ======================================================================== */
/* Plotly helpers                                                           */
/* ======================================================================== */
function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function plotLayout(extra = {}) {
  const ink = cssVar("--ink-2"), grid = cssVar("--border");
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, system-ui, sans-serif", color: ink, size: 12 },
    margin: { l: 56, r: 16, t: 16, b: 44 },
    xaxis: { gridcolor: grid, zerolinecolor: grid, linecolor: grid },
    yaxis: { gridcolor: grid, zerolinecolor: grid, linecolor: grid },
    legend: { orientation: "h", y: -0.18 },
    hoverlabel: { font: { family: "Inter, system-ui, sans-serif" } },
  }, extra);
}
function plot(el, data, layout) {
  if (!window.Plotly) { el.replaceChildren(h("div", { class: "chart-fallback" }, "Chart library failed to load (static/vendor/plotly.min.js).")); return; }
  Plotly.react(el, data, plotLayout(layout), { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"] });
}

/* ======================================================================== */
/* router                                                                   */
/* ======================================================================== */
async function route() {
  clearTimers();
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  document.querySelectorAll("nav a").forEach((a) => a.classList.remove("active"));
  const nav = (k) => { const a = document.querySelector(`nav a[data-nav="${k}"]`); if (a) a.classList.add("active"); };
  // Each navigation renders into its own container. If an earlier, slower route finishes late,
  // it writes into its own (now detached) container instead of overwriting the current page.
  const view = h("div", { class: "route" });
  $("#view").replaceChildren(view);
  try {
    if (parts[0] === "exp" && parts[1]) { nav("list"); await viewExperiment(view, Number(parts[1]), parts[2] || "overview"); }
    else if (parts[0] === "new") { nav("new"); viewNew(view); }
    else if (parts[0] === "jobs") { nav("jobs"); await viewJobs(view); }
    else if (parts[0] === "help") { nav("help"); viewHelp(view); }
    else { nav("list"); await viewList(view); }
  } catch (e) {
    view.replaceChildren(h("div", { class: "card empty" }, h("div", { class: "big" }, "⚠"), h("div", {}, e.message)));
  }
}

/* ======================================================================== */
/* list                                                                     */
/* ======================================================================== */
async function viewList(view) {
  const exps = await api("/experiments");
  const head = h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "Experiments"), h("div", { class: "sub" }, "Each experiment is one dish recording: video segments, setup, and analysis results.")),
    h("a", { class: "btn primary", href: "#/new" }, "＋ New experiment"));
  if (!exps.length) {
    view.replaceChildren(head, h("div", { class: "card empty" },
      h("div", { class: "big" }, "🐝"), h("h2", {}, "No experiments yet"),
      h("p", {}, "Create one, upload a recording, mark the queen cell, and run the analysis."),
      h("a", { class: "btn primary", href: "#/new" }, "Create the first experiment")));
    return;
  }
  const rows = exps.map((e) => h("tr", { class: "clickable", onclick: () => (location.hash = `#/exp/${e.id}`) },
    h("td", { class: "mono muted" }, `#${e.id}`),
    h("td", {}, h("b", {}, e.name), e.notes ? h("div", { class: "tiny muted" }, e.notes.slice(0, 80)) : null),
    h("td", {}, e.station || "–"),
    h("td", {}, e.recorded_on || "–"),
    h("td", { class: "num" }, e.n_videos),
    h("td", { class: "num" }, fmt.dur(e.duration_s)),
    h("td", { class: "num" }, e.n_bees),
    h("td", {}, pill(e.status), e.status === "analysing" && e.latest_job ? h("span", { class: "tiny muted" }, ` ${Math.round(e.latest_job.progress * 100)}%`) : null)));
  view.replaceChildren(head, h("div", { class: "card", style: { padding: 0 } }, h("div", { class: "table-wrap" },
    h("table", {}, h("thead", {}, h("tr", {}, ["ID", "Name", "Station", "Recorded", "Videos", "Duration", "Bees", "Status"]
      .map((t, i) => h("th", { class: [4, 5, 6].includes(i) ? "num" : "" }, t)))), h("tbody", {}, rows)))));
  if (exps.some((e) => e.status === "analysing" || e.status === "rendering")) {
    const t = setInterval(() => { if (location.hash === "" || location.hash === "#/") route(); }, 4000);
    App.timers.add(t);
  }
}

/* ======================================================================== */
/* new                                                                      */
/* ======================================================================== */
function viewNew(view) {
  const today = new Date().toISOString().slice(0, 10);
  const f = {
    name: h("input", { placeholder: "e.g. Colony A, cell 3, day 1", required: true }),
    station: h("input", { placeholder: "station1" }),
    recorded_on: h("input", { type: "date", value: today }),
    notes: h("textarea", { style: { minHeight: "90px", fontFamily: "var(--font)" }, placeholder: "Larva age, colony, temperature, anything worth remembering…" }),
  };
  const submit = guard(async (ev) => {
    ev.preventDefault();
    const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value.trim()]));
    if (!body.name) { toast("Give the experiment a name", "error"); return; }
    const e = await api("/experiments", { method: "POST", body });
    toast("Experiment created, now upload the video");
    location.hash = `#/exp/${e.id}/overview`;
  });
  view.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "New experiment"), h("div", { class: "sub" }, "Metadata first; you'll upload video and mark the queen cell next."))),
    h("form", { class: "card form", style: { maxWidth: "640px" }, onsubmit: submit },
      h("label", {}, "Name", f.name),
      h("div", { class: "form two" }, h("label", {}, "Station", f.station), h("label", {}, "Recorded on", f.recorded_on)),
      h("label", {}, "Notes", f.notes),
      h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "Create experiment"), h("a", { class: "btn ghost", href: "#/" }, "Cancel"))));
  f.name.focus();
}

/* ======================================================================== */
/* jobs                                                                     */
/* ======================================================================== */
async function viewJobs(view) {
  const render = async () => {
    const jobs = await api("/jobs");
    const rows = jobs.map((j) => h("tr", {},
      h("td", { class: "mono muted" }, `#${j.id}`),
      h("td", {}, h("a", { href: `#/exp/${j.experiment_id}/analysis` }, `experiment #${j.experiment_id}`)),
      h("td", {}, pill(j.status)),
      h("td", { style: { minWidth: "160px" } }, ["running", "queued"].includes(j.status)
        ? h("div", { class: `progress ${j.status === "queued" ? "indeterminate" : ""}` }, h("div", { style: { width: `${j.progress * 100}%` } }))
        : fmt.pct(j.progress)),
      h("td", { class: "muted" }, j.message || ""),
      h("td", { class: "muted tiny" }, fmt.date(j.created_at))));
    view.replaceChildren(
      h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Analysis queue"), h("div", { class: "sub" }, "Analyses run one at a time on this computer, each in its own process."))),
      jobs.length ? h("div", { class: "card", style: { padding: 0 } }, h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Job", "Experiment", "Status", "Progress", "Message", "Created"].map((t) => h("th", {}, t)))), h("tbody", {}, rows))))
        : h("div", { class: "card empty" }, h("div", { class: "big" }, "⟳"), "No analyses yet."));
  };
  await render();
  App.timers.add(setInterval(guard(render), 3000));
}

/* ======================================================================== */
/* help                                                                     */
/* ======================================================================== */
function viewHelp(view) {
  const steps = [["1 · Detect", "Dark bees on the light dish are segmented in every analysed frame."],
    ["2 · Read dot", "The paint dot on each bee is classified into a palette colour."],
    ["3 · Link", "Detections are linked frame-to-frame into short, clean tracklets."],
    ["4 · Identify", "Colour evidence is summed per tracklet; each bee gets at most one place at a time."],
    ["5 · Paths", "Per-bee trajectories in mm, gaps filled carefully, heading from the thorax dot + motion."],
    ["6 · Visits", "Head within the contact / vicinity zone of the queen cell → visits with durations."]];
  view.replaceChildren(h("div", { class: "prose" },
    h("h1", {}, "How it works"),
    h("p", {}, "beetrack measures which worker visits the queen cell, how often and for how long, and keeps the full path of every bee."),
    h("div", { class: "pipeline-steps" }, steps.map(([t, d]) => h("div", {}, h("b", {}, t), d))),
    h("h2", {}, "Workflow"),
    h("ol", {},
      h("li", {}, "Create an experiment and upload the video (several 1-hour segments are fine; upload them in time order)."),
      h("li", {}, "Setup tab: check the dish circle (auto-detected, or click 3 points on the rim), mark the queen cell (“Queen cell: ellipse”: drag from one end of the cell to the other, then drag the middle to move it, the ends to resize/rotate, the side dot for width; or “outline” for odd shapes; or “Copy cell from…” another experiment), and confirm which dot colour each bee wears."),
      h("li", {}, "Use the colour probe on a few paint dots. If the measured hue is far from the palette, adjust the palette hues in Analysis → configuration."),
      h("li", {}, "Analysis tab: run. Expect roughly 5–15 minutes per hour of video on a recent Mac."),
      h("li", {}, "Results: visits per bee, durations, timeline and downloads. Explorer: scrub the video with tracks drawn on it to verify.")),
    h("h2", {}, "Definitions"),
    h("ul", {},
      h("li", {}, h("b", {}, "Contact zone"), ": the queen-cell outline grown by 3 mm (about antenna reach). ", h("b", {}, "Vicinity"), ": grown by 10 mm."),
      h("li", {}, h("b", {}, "Visit"), ": the bee's head inside a zone. Gaps under 1.5 s are merged; visits under 1 s are dropped. All thresholds are editable in the configuration."),
      h("li", {}, h("b", {}, "Tracked fraction"), ": share of the recording with a known position for that bee. Treat bees with low coverage with care.")),
    h("h2", {}, "Validate before you publish"),
    h("p", {}, "Use the Explorer to spot-check identities on random frames, and report identity accuracy (see docs/VALIDATION.md).")));
}

/* ======================================================================== */
/* experiment                                                               */
/* ======================================================================== */
const TABS = [["overview", "Overview"], ["setup", "Setup"], ["analysis", "Analysis"], ["results", "Results"], ["explorer", "Explorer"]];

async function viewExperiment(view, id, tab) {
  const e = await api(`/experiments/${id}`);
  App.exp = e;
  usePalette(e.setup.palette);
  const head = h("div", { class: "page-head" },
    h("div", {}, h("div", { class: "row" }, h("h1", {}, e.name), pill(e.status)),
      h("div", { class: "sub" }, [e.station && `Station ${e.station}`, e.recorded_on, `${e.n_videos} video${e.n_videos === 1 ? "" : "s"}`, fmt.dur(e.duration_s)].filter(Boolean).join(" · "))),
    h("div", { class: "row" },
      e.has_results ? h("a", { class: "btn", href: `#/exp/${id}/results` }, "View results") : null,
      h("button", { class: "danger small", onclick: guard(async () => {
        if (!(await confirmModal("Delete experiment?", `“${e.name}”, its videos and all results will be permanently deleted from this computer.`, "Delete", true))) return;
        await api(`/experiments/${id}`, { method: "DELETE" }); toast("Experiment deleted"); location.hash = "#/";
      }) }, "Delete")));
  const tabs = h("div", { class: "tabs" }, TABS.map(([k, label]) => h("a", { href: `#/exp/${id}/${k}`, class: k === tab ? "active" : "" }, label,
    k === "overview" && e.check.errors.length ? h("span", { class: "count" }, e.check.errors.length) : null)));
  const body = h("div", {});
  view.replaceChildren(head, tabs, body);
  const fn = { overview: tabOverview, setup: tabSetup, analysis: tabAnalysis, results: tabResults, explorer: tabExplorer }[tab] || tabOverview;
  await fn(body, e);
}

/* ---------- overview ---------------------------------------------------- */
function checklist(e) {
  const items = [];
  if (!e.videos.length) items.push(h("div", { class: "alert info" }, "① Upload the recording below."));
  e.check.errors.forEach((m) => items.push(h("div", { class: "alert error" }, "✕ ", m)));
  e.check.warnings.forEach((m) => items.push(h("div", { class: "alert warn" }, "! ", m)));
  if (e.videos.length && !e.check.errors.length) items.push(h("div", { class: "alert ok" }, "✓ Ready to analyse. ", h("a", { href: `#/exp/${e.id}/analysis` }, "Go to Analysis →")));
  return h("div", { class: "alerts" }, items);
}

async function tabOverview(body, e) {
  const f = { name: h("input", { value: e.name }), station: h("input", { value: e.station }), recorded_on: h("input", { type: "date", value: e.recorded_on }),
    notes: h("textarea", { style: { minHeight: "90px", fontFamily: "var(--font)" } }, e.notes) };
  const save = guard(async () => {
    await api(`/experiments/${e.id}`, { method: "PATCH", body: Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value])) });
    toast("Saved"); route();
  });
  const vids = e.videos.map((v) => h("tr", {},
    h("td", { class: "mono muted" }, v.position + 1), h("td", {}, v.filename), h("td", {}, `${v.width}×${v.height}`), h("td", { class: "num" }, `${fmt.num(v.fps, 2)} fps`),
    h("td", { class: "num" }, fmt.dur(v.duration_s)), h("td", { class: "num" }, fmt.bytes(v.size_bytes)),
    h("td", {}, h("button", { class: "ghost small danger", title: "Remove", onclick: guard(async () => {
      if (!(await confirmModal("Remove video?", `${v.filename} will be deleted from the server.`, "Remove", true))) return;
      await api(`/experiments/${e.id}/videos/${v.id}`, { method: "DELETE" }); route();
    }) }, "✕"))));
  body.replaceChildren(h("div", { class: "split" },
    h("div", { class: "grid" },
      h("div", { class: "card" }, h("h2", {}, "Checklist"), checklist(e)),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Video segments"), h("span", { class: "muted tiny" }, "analysed as one continuous timeline, in this order")),
        vids.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["#", "File", "Resolution", "Rate", "Duration", "Size", ""].map((t) => h("th", {}, t)))), h("tbody", {}, vids))) : null,
        uploader(e))),
    h("div", { class: "card form" }, h("h2", {}, "Details"),
      h("label", {}, "Name", f.name), h("div", { class: "form two" }, h("label", {}, "Station", f.station), h("label", {}, "Recorded on", f.recorded_on)),
      h("label", {}, "Notes", f.notes), h("div", {}, h("button", { class: "primary", onclick: save }, "Save details")))));
}

function uploader(e) {
  const input = h("input", { type: "file", accept: "video/*,.mkv,.avi,.mov,.mp4", multiple: true, class: "hidden" });
  const list = h("div", {});
  const zone = h("div", { class: "dropzone", onclick: () => input.click() },
    h("div", { style: { fontSize: "26px" } }, "⬆"), h("div", {}, h("b", {}, "Drop video files here"), " or click to choose"),
    h("div", { class: "tiny" }, "MP4 / MKV / AVI / MOV. Large files are fine; keep this tab open while uploading."));
  const send = (files) => {
    const queue = [...files].sort((a, b) => a.name.localeCompare(b.name));
    const next = () => {
      const file = queue.shift();
      if (!file) { toast("Upload finished"); route(); return; }
      const bar = h("div", { style: { width: "0%" } }), pct = h("span", { class: "tiny muted" }, "0%");
      list.append(h("div", { class: "upload-item" }, h("span", {}, file.name, " ", h("span", { class: "muted tiny" }, fmt.bytes(file.size))), h("div", { class: "progress" }, bar), pct));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/experiments/${e.id}/videos`);
      xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) { const p = (ev.loaded / ev.total) * 100; bar.style.width = `${p}%`; pct.textContent = `${Math.round(p)}%`; } };
      xhr.onload = () => {
        if (xhr.status >= 300) { let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail; } catch {} toast(`${file.name}: ${m}`, "error"); pct.textContent = "failed"; }
        else pct.textContent = "✓";
        next();
      };
      xhr.onerror = () => { toast(`${file.name}: network error`, "error"); next(); };
      const fd = new FormData(); fd.append("file", file); xhr.send(fd);
    };
    next();
  };
  input.onchange = () => send(input.files);
  zone.ondragover = (ev) => { ev.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = (ev) => { ev.preventDefault(); zone.classList.remove("over"); send(ev.dataTransfer.files); };
  return h("div", { style: { marginTop: "12px" } }, zone, input, list);
}

/* ---------- setup ------------------------------------------------------- */
async function tabSetup(body, e) {
  if (!e.videos.length) { body.replaceChildren(h("div", { class: "card empty" }, "Upload a video first (Overview tab).")); return; }
  const v0 = e.videos[0];
  const W = v0.width, H = v0.height;
  const duration = e.videos.reduce((a, v) => a + v.duration_s, 0);
  const setup = structuredClone(e.setup);
  setup.bees = setup.bees.map(normalizeBee);
  let tool = null, pts = [], t = 0, drag = null;

  const img = h("img", { alt: "frame" });
  const canvas = h("canvas", { width: W, height: H, tabindex: "0", "aria-label": "setup canvas" });
  const stage = h("div", { class: "stage" }, img, canvas);
  const hint = h("div", { class: "hint-bar" }, "Choose a tool. The dish is detected automatically after upload; check that the orange circle sits on the rim.");
  const cellInfo = h("div", { class: "cell-info muted tiny" });
  const dirtyBadge = h("span", { class: "pill queued hidden dirty-badge" }, "unsaved changes");
  const probeOut = h("div", { class: "probe muted" });
  const diam = h("input", { type: "number", step: "0.5", min: "10", value: (setup.dish && setup.dish.diameter_mm) || 150, style: { width: "90px" }, "aria-label": "dish diameter" });
  const slider = h("input", { type: "range", min: 0, max: Math.max(0, Math.floor(duration)), value: 0, step: 1 });
  const clock = h("span", { class: "mono muted" }, fmt.clock(0));
  const alerts = h("div", { class: "alerts" });
  const markDirty = () => dirtyBadge.classList.remove("hidden");

  const loadFrame = () => { img.src = `/api/experiments/${e.id}/frame?t=${t}&overlay=false&max_width=${W}`; };
  slider.oninput = () => { t = Number(slider.value); clock.textContent = fmt.clock(t); };
  slider.onchange = loadFrame;

  /* ---- queen-cell geometry (image pixels) ---- */
  const r1 = (v) => Math.round(v * 10) / 10;
  const pxPerMm = () => (setup.dish ? (2 * setup.dish.radius_px) / setup.dish.diameter_mm : null);
  const axes = (s) => { const a = (s.angle_deg * Math.PI) / 180; return [[Math.cos(a), Math.sin(a)], [-Math.sin(a), Math.cos(a)]]; };
  const ellipsePoly = (s, n = 48) => {
    const [u, v] = axes(s);
    return [...Array(n).keys()].map((i) => {
      const th = (2 * Math.PI * i) / n, a = (Math.cos(th) * s.length_px) / 2, b = (Math.sin(th) * s.width_px) / 2;
      return [r1(s.cx + a * u[0] + b * v[0]), r1(s.cy + a * u[1] + b * v[1])];
    });
  };
  setup.ignore_areas = setup.ignore_areas || [];
  let selected = setup.queen_cell ? "cell" : null;
  const getObj = (key = selected) => (key === "cell" ? setup.queen_cell : key && key.startsWith("ignore:") ? setup.ignore_areas[Number(key.slice(7))] : null);
  const putObj = (geom) => {  // geom = {shape, polygon_px}; keeps the object's other fields (name, learn_background)
    if (selected === "cell") setup.queen_cell = { learn_background: true, ...(setup.queen_cell || {}), ...geom };
    else if (selected && selected.startsWith("ignore:")) { const i = Number(selected.slice(7)); setup.ignore_areas[i] = { ...setup.ignore_areas[i], ...geom }; }
  };
  const shape = () => (getObj() && getObj().shape) || null;
  const setEllipse = (s) => {
    s.length_px = Math.max(4, s.length_px); s.width_px = Math.max(3, s.width_px);
    s.angle_deg = ((s.angle_deg % 360) + 360) % 360;
    putObj({ shape: { type: "ellipse", ...s }, polygon_px: ellipsePoly(s) });
    markDirty(); draw();
  };
  const setPolygon = (poly) => { putObj({ shape: null, polygon_px: poly.map(([x, y]) => [r1(x), r1(y)]) }); markDirty(); draw(); };
  const handlesOf = () => {
    const q = getObj();
    if (!q) return [];
    const s = q.shape;
    if (s) {
      const [u, v] = axes(s), L = s.length_px / 2, Wd = s.width_px / 2;
      return [
        { kind: "center", p: [s.cx, s.cy] },
        { kind: "end1", p: [s.cx - L * u[0], s.cy - L * u[1]] },
        { kind: "end2", p: [s.cx + L * u[0], s.cy + L * u[1]] },
        { kind: "side", p: [s.cx + Wd * v[0], s.cy + Wd * v[1]] },
      ];
    }
    return q.polygon_px.map((p, i) => ({ kind: "vertex", i, p }));
  };
  const inside = (p, poly) => {  // ray casting
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  const handleR = () => Math.max(6, W / 110);
  const polyArea = (p) => Math.abs(p.reduce((a, [x, y], i) => { const [x2, y2] = p[(i + 1) % p.length]; return a + x * y2 - x2 * y; }, 0)) / 2;
  const hitTest = (p) => {
    const hs = handlesOf().filter((x) => x.kind !== "center");
    let best = null, bd = handleR() * 1.6;
    for (const x of hs) { const d = Math.hypot(p[0] - x.p[0], p[1] - x.p[1]); if (d < bd) { bd = d; best = x; } }
    if (best) return best;
    const c = handlesOf().find((x) => x.kind === "center");
    if (c && Math.hypot(p[0] - c.p[0], p[1] - c.p[1]) < handleR() * 1.6) return { kind: "move" };
    if (getObj() && inside(p, getObj().polygon_px)) return { kind: "move" };
    // another object under the pointer → select it (smallest first, so a small area inside a big one is reachable)
    const objs = [["cell", setup.queen_cell], ...setup.ignore_areas.map((a, i) => [`ignore:${i}`, a])]
      .filter(([, o]) => o && inside(p, o.polygon_px))
      .sort((a, b) => polyArea(a[1].polygon_px) - polyArea(b[1].polygon_px));
    if (objs.length) return { kind: "move", select: objs[0][0] };
    return null;
  };
  const describeCell = () => {
    const q = getObj(), k = pxPerMm();
    const what = selected === "cell" ? "Queen cell" : q ? `Ignore area “${q.name || "ignore"}”` : "";
    if (!q) { cellInfo.textContent = setup.queen_cell ? "Click a shape to select it." : "No queen cell yet: use “Queen cell: ellipse” and drag from one end of the cell to the other."; return; }
    const u = (px) => (k ? `${(px / k).toFixed(1)} mm` : `${Math.round(px)} px`);
    if (q.shape) {
      const s = q.shape;
      cellInfo.textContent = `${what} (ellipse): ${u(s.length_px)} × ${u(s.width_px)}, angle ${Math.round(s.angle_deg)}°, centre (${Math.round(s.cx)}, ${Math.round(s.cy)}) px. Drag the middle to move, the ends to resize/rotate, the side dot for width. Arrow keys nudge (Shift = ×10).`;
    } else {
      const xs = q.polygon_px.map((p) => p[0]), ys = q.polygon_px.map((p) => p[1]);
      cellInfo.textContent = `${what} (outline, ${q.polygon_px.length} points): ${u(Math.max(...xs) - Math.min(...xs))} × ${u(Math.max(...ys) - Math.min(...ys))}. Drag a corner to reshape, drag inside to move. Arrow keys nudge (Shift = ×10).`;
    }
  };

  const ctx = canvas.getContext("2d");
  const draw = () => {
    ctx.clearRect(0, 0, W, H);
    const lw = Math.max(2, W / 600);
    if (setup.dish) {
      const [cx, cy] = setup.dish.center_px;
      ctx.strokeStyle = "#ffa53c"; ctx.lineWidth = lw; ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(cx, cy, setup.dish.radius_px, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx - 12, cy); ctx.lineTo(cx + 12, cy); ctx.moveTo(cx, cy - 12); ctx.lineTo(cx, cy + 12); ctx.stroke();
      ctx.fillStyle = "#ffa53c"; ctx.font = `${Math.round(W / 70)}px Inter, sans-serif`;
      ctx.fillText(`${setup.dish.diameter_mm} mm · ${(2 * setup.dish.radius_px / setup.dish.diameter_mm).toFixed(2)} px/mm`, cx - setup.dish.radius_px, cy - setup.dish.radius_px - 10);
    }
    const path = (p) => { ctx.beginPath(); p.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); };
    setup.ignore_areas.forEach((a, i) => {  // grey, hatched: nothing is detected here
      path(a.polygon_px);
      ctx.save(); ctx.clip();
      ctx.fillStyle = "rgba(80,80,80,.28)"; ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "rgba(255,255,255,.55)"; ctx.lineWidth = Math.max(1, lw / 2);
      for (let d = -H; d < W; d += Math.max(8, W / 60)) { ctx.beginPath(); ctx.moveTo(d, H); ctx.lineTo(d + H, 0); ctx.stroke(); }
      ctx.restore();
      ctx.strokeStyle = selected === `ignore:${i}` ? "#ffffff" : "#6b7280"; ctx.lineWidth = lw; ctx.setLineDash([6, 4]); path(a.polygon_px); ctx.stroke(); ctx.setLineDash([]);
      const xs = a.polygon_px.map((p) => p[0]), ys = a.polygon_px.map((p) => p[1]);
      ctx.fillStyle = "#ffffff"; ctx.font = `600 ${Math.round(W / 60)}px Inter, sans-serif`;
      ctx.fillText(`✕ ${a.name || "ignore"}`, Math.min(...xs) + 4, (Math.min(...ys) + Math.max(...ys)) / 2);
    });
    const q = getObj();
    if (setup.queen_cell && setup.queen_cell.polygon_px.length) {
      ctx.strokeStyle = "#e5484d"; ctx.fillStyle = "rgba(229,72,77,.18)"; ctx.lineWidth = lw; ctx.setLineDash([]);
      path(setup.queen_cell.polygon_px); ctx.fill(); ctx.stroke();
    }
    if (q && q.polygon_px.length) {
      if (!tool) {
        const hs = handlesOf(), R = handleR();
        ctx.strokeStyle = selected === "cell" ? "#e5484d" : "#ffffff";
        if (q.shape) {  // axis line
          const e1 = hs[1].p, e2 = hs[2].p;
          ctx.setLineDash([6, 5]); ctx.beginPath(); ctx.moveTo(...e1); ctx.lineTo(...e2); ctx.stroke(); ctx.setLineDash([]);
        }
        for (const x of hs) {
          ctx.beginPath(); ctx.arc(x.p[0], x.p[1], x.kind === "vertex" ? R * 0.6 : R, 0, Math.PI * 2);
          ctx.fillStyle = x.kind === "center" ? (selected === "cell" ? "#e5484d" : "#374151") : "#ffffff"; ctx.fill();
          ctx.lineWidth = lw; ctx.strokeStyle = selected === "cell" ? "#e5484d" : "#374151"; ctx.stroke();
        }
      }
    }
    if (pts.length) {
      ctx.strokeStyle = "#3dd6f5"; ctx.fillStyle = "#3dd6f5"; ctx.lineWidth = lw; ctx.setLineDash([8, 6]);
      ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); ctx.setLineDash([]);
      pts.forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, lw * 2.2, 0, Math.PI * 2); ctx.fill(); });
    }
    describeCell();
    renderAreaList();
  };
  img.onload = draw;

  const toPx = (ev) => { const r = canvas.getBoundingClientRect(); return [(ev.clientX - r.left) * (W / r.width), (ev.clientY - r.top) * (H / r.height)]; };
  const toolBtns = {};
  const setTool = (name) => {
    tool = tool === name ? null : name; pts = [];
    Object.entries(toolBtns).forEach(([k, b]) => b.classList.toggle("active", k === tool));
    stage.classList.toggle("tool-active", !!tool);
    hint.textContent = {
      dish: "Click 3 points on the inner rim of the dish.",
      ellipse: "Drag from one end of the queen cell to the other. You can adjust it afterwards.",
      cell: "Click around the queen cell outline. Double-click (or click the first point) to finish.",
      "ignore-ellipse": "Drag across the area to ignore (food, water tube…). Nothing inside it will be detected.",
      "ignore-poly": "Click around the area to ignore. Double-click (or click the first point) to finish.",
      probe: "Click a paint spot to read its colour.",
    }[tool] || "Choose a tool, or drag the queen cell to adjust it.";
    draw();
  };
  const newIgnore = () => { setup.ignore_areas.push({ name: setup.ignore_areas.length ? `area ${setup.ignore_areas.length + 1}` : "food", shape: null, polygon_px: [] }); selected = `ignore:${setup.ignore_areas.length - 1}`; };
  const finishCell = () => {
    if (pts.length < 3) { toast("Need at least 3 points", "error"); return; }
    const poly = pts.slice(), ignoring = tool === "ignore-poly";
    if (ignoring) newIgnore(); else selected = "cell";
    setTool(null); setPolygon(poly); hint.textContent = ignoring ? "Ignore area set: drag to adjust, rename it below, then save." : "Queen cell set: drag to adjust, then save.";
  };

  /* ---- pointer: draw a new ellipse, or edit the existing cell ---- */
  canvas.addEventListener("pointerdown", (ev) => {
    const p = toPx(ev);
    if (tool === "ellipse" || tool === "ignore-ellipse") {
      if (tool === "ignore-ellipse") newIgnore(); else selected = "cell";
      drag = { kind: "new", p0: p, ignoring: tool === "ignore-ellipse" }; canvas.setPointerCapture(ev.pointerId); return;
    }
    if (tool) return;
    const hit = hitTest(p);
    if (!hit) { if (selected) { selected = null; draw(); } return; }
    if (hit.select) { selected = hit.select; draw(); }
    drag = { ...hit, start: p, orig: structuredClone(getObj()) };
    canvas.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  canvas.addEventListener("pointermove", (ev) => {
    const p = toPx(ev);
    if (!drag) {
      if (!tool) {
        const hit = hitTest(p);
        canvas.style.cursor = !hit ? "default" : hit.kind === "move" ? "move" : hit.kind === "side" ? "ew-resize" : "grab";
      }
      return;
    }
    if (drag.kind === "new") {
      const [x0, y0] = drag.p0, L = Math.hypot(p[0] - x0, p[1] - y0);
      if (L < 3) return;
      setEllipse({ cx: (x0 + p[0]) / 2, cy: (y0 + p[1]) / 2, length_px: L, width_px: L * 0.42, angle_deg: (Math.atan2(p[1] - y0, p[0] - x0) * 180) / Math.PI });
      return;
    }
    const dx = p[0] - drag.start[0], dy = p[1] - drag.start[1];
    const o = drag.orig;
    if (drag.kind === "move") {
      if (o.shape) setEllipse({ ...o.shape, cx: o.shape.cx + dx, cy: o.shape.cy + dy });
      else setPolygon(o.polygon_px.map(([x, y]) => [x + dx, y + dy]));
    } else if (drag.kind === "vertex") {
      setPolygon(o.polygon_px.map((q, i) => (i === drag.i ? p : q)));
    } else if (o.shape) {
      const s = o.shape, [u, v] = axes(s), L = s.length_px / 2;
      const e1 = [s.cx - L * u[0], s.cy - L * u[1]], e2 = [s.cx + L * u[0], s.cy + L * u[1]];
      if (drag.kind === "end1" || drag.kind === "end2") {
        const fixed = drag.kind === "end1" ? e2 : e1, moving = p;
        const [a, b] = drag.kind === "end1" ? [moving, fixed] : [fixed, moving];  // keep end1 → end2 direction
        setEllipse({ ...s, cx: (a[0] + b[0]) / 2, cy: (a[1] + b[1]) / 2, length_px: Math.hypot(b[0] - a[0], b[1] - a[1]),
          angle_deg: (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI });
      } else if (drag.kind === "side") {
        setEllipse({ ...s, width_px: 2 * Math.abs((p[0] - s.cx) * v[0] + (p[1] - s.cy) * v[1]) });
      }
    }
  });
  const endDrag = () => {
    if (drag && drag.kind === "new") {
      if (!shape()) {  // too small: discard the half-created area
        if (drag.ignoring) { setup.ignore_areas.pop(); selected = setup.queen_cell ? "cell" : null; }
        drag = null; draw(); return;
      }
      const ign = drag.ignoring;
      setTool(null); hint.textContent = ign ? "Ignore area set: drag to adjust, rename it below, then save." : "Queen cell set: drag to adjust, then save.";
    }
    drag = null;
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  /* ---- clicks: dish points, polygon points, colour probe ---- */
  canvas.addEventListener("click", guard(async (ev) => {
    if (!tool || tool === "ellipse" || tool === "ignore-ellipse") return;
    const p = toPx(ev);
    if (tool === "probe") {
      const r = await api(`/experiments/${e.id}/probe?x=${p[0]}&y=${p[1]}&t=${t}`);
      const cls = Object.entries(r.classified).filter(([, n]) => n > 0).map(([k, n]) => `${k}:${n}`).join(" ") || "none";
      probeOut.replaceChildren(h("span", { class: "swatch", style: { background: r.hex } }), ` H ${r.h.toFixed(0)}  S ${r.s.toFixed(0)}  V ${r.v.toFixed(0)}  → palette: ${cls}`);
      return;
    }
    if ((tool === "cell" || tool === "ignore-poly") && pts.length >= 3) {
      const [x0, y0] = pts[0];
      if (Math.hypot(p[0] - x0, p[1] - y0) < W / 120) { finishCell(); return; }
    }
    pts.push(p); draw();
    if (tool === "dish" && pts.length === 3) {
      const r = await api(`/experiments/${e.id}/dish`, { method: "POST", body: { diameter_mm: Number(diam.value), points: pts } });
      setup.dish = r.setup.dish; setTool(null); showCheck(r.check); toast("Dish set from 3 points");
    }
  }));
  canvas.addEventListener("dblclick", (ev) => { if (tool === "cell" || tool === "ignore-poly") { ev.preventDefault(); pts.pop(); finishCell(); } });

  /* ---- keyboard: nudge the cell, Esc cancels a tool ---- */
  document.onkeydown = (ev) => {
    if (!location.hash.includes("/setup") || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
    if (ev.key === "Escape") { if (tool) setTool(tool); return; }
    if ((ev.key === "Delete" || ev.key === "Backspace") && selected && selected.startsWith("ignore:") && !tool) { ev.preventDefault(); deleteSelectedArea(); return; }
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key];
    if (!d || !getObj() || tool) return;
    ev.preventDefault();
    const k = ev.shiftKey ? 10 : 1, q = getObj();
    if (q.shape) setEllipse({ ...q.shape, cx: q.shape.cx + d[0] * k, cy: q.shape.cy + d[1] * k });
    else setPolygon(q.polygon_px.map(([x, y]) => [x + d[0] * k, y + d[1] * k]));
  };

  /* ---- copy the queen cell from another experiment ---- */
  const copySel = h("select", { class: "copy-cell", "aria-label": "copy queen cell from", style: { width: "auto" } }, h("option", { value: "" }, "Copy cell & areas from…"));
  (async () => {
    try {
      const others = (await api("/experiments")).filter((x) => x.id !== e.id).slice(0, 40);
      const full = await Promise.all(others.map((x) => api(`/experiments/${x.id}`).catch(() => null)));
      const withCell = full.filter((x) => x && (x.setup.queen_cell || (x.setup.ignore_areas || []).length) && x.videos.length);
      copySel.append(...withCell.map((x) => h("option", { value: x.id }, `#${x.id} ${x.name}`)));
      copySel.disabled = !withCell.length;
      copySel.title = withCell.length ? "Start from another experiment's queen cell, then adjust it" : "No other experiment has a queen cell yet";
      copySel.onchange = () => {
        const src = withCell.find((x) => String(x.id) === copySel.value);
        if (!src) return;
        const k = W / src.videos[0].width;  // same camera framing assumed; scale if the resolution differs
        const scaleArea = (a) => (a.shape
          ? { ...a, shape: { ...a.shape, cx: a.shape.cx * k, cy: a.shape.cy * k, length_px: a.shape.length_px * k, width_px: a.shape.width_px * k },
              polygon_px: ellipsePoly({ ...a.shape, cx: a.shape.cx * k, cy: a.shape.cy * k, length_px: a.shape.length_px * k, width_px: a.shape.width_px * k }) }
          : { ...a, polygon_px: a.polygon_px.map(([x, y]) => [r1(x * k), r1(y * k)]) });
        if (src.setup.queen_cell) setup.queen_cell = scaleArea(src.setup.queen_cell);
        setup.ignore_areas = (src.setup.ignore_areas || []).map(scaleArea);
        selected = setup.queen_cell ? "cell" : null;
        markDirty(); draw();
        toast(`Queen cell and ${setup.ignore_areas.length} ignore area(s) copied from #${src.id}. Drag them into place, then save.`);
        copySel.value = "";
      };
    } catch (err) { copySel.disabled = true; }
  })();

  const autoDish = guard(async () => {
    const r = await api(`/experiments/${e.id}/dish`, { method: "POST", body: { diameter_mm: Number(diam.value) } });
    setup.dish = r.setup.dish; draw(); showCheck(r.check); toast("Dish detected");
  });
  diam.onchange = () => { if (setup.dish) { setup.dish.diameter_mm = Number(diam.value); markDirty(); draw(); } };

  toolBtns.dish = h("button", { class: "small", onclick: () => setTool("dish") }, "◯ Dish: 3 points");
  toolBtns.ellipse = h("button", { class: "small", onclick: () => setTool("ellipse") }, "⬭ Queen cell: ellipse");
  toolBtns.cell = h("button", { class: "small", onclick: () => setTool("cell") }, "⬠ Queen cell: outline");
  toolBtns.probe = h("button", { class: "small", onclick: () => setTool("probe") }, "⊙ Colour probe");
  toolBtns["ignore-ellipse"] = h("button", { class: "small", onclick: () => setTool("ignore-ellipse") }, "▨ Ignore area: ellipse");
  toolBtns["ignore-poly"] = h("button", { class: "small", onclick: () => setTool("ignore-poly") }, "▨ Ignore area: outline");
  function deleteSelectedArea() {
    if (!selected || !selected.startsWith("ignore:")) return;
    setup.ignore_areas.splice(Number(selected.slice(7)), 1);
    selected = setup.queen_cell ? "cell" : null; markDirty(); draw();
  }
  const learnBg = h("input", { type: "checkbox", "aria-label": "learn cell background" });
  learnBg.onchange = () => { if (setup.queen_cell) { setup.queen_cell.learn_background = learnBg.checked; markDirty(); } };
  const areaList = h("div", { class: "area-list" });
  function renderAreaList() {
    learnBg.checked = !setup.queen_cell || setup.queen_cell.learn_background !== false;
    learnBg.disabled = !setup.queen_cell;
    areaList.replaceChildren(
      h("label", { class: "inline-check" }, learnBg, "Learn the queen cell's own look, so its dark wax isn't counted as bees (bees walking on it are still found)"),
      setup.ignore_areas.length ? h("div", { class: "row", style: { gap: "6px", marginTop: "6px" } },
        h("span", { class: "muted tiny" }, "Ignore areas:"),
        ...setup.ignore_areas.map((a, i) => {
          const name = h("input", { value: a.name || "", "aria-label": `ignore area ${i + 1} name`, style: { width: "110px" } });
          name.onchange = () => { a.name = name.value.trim() || "ignore"; markDirty(); draw(); };
          name.onfocus = () => { selected = `ignore:${i}`; draw(); };
          return h("span", { class: `area-chip ${selected === `ignore:${i}` ? "active" : ""}` }, name,
            h("button", { class: "ghost small danger", title: "Delete this area", onclick: () => { selected = `ignore:${i}`; deleteSelectedArea(); } }, "✕"));
        })) : h("div", { class: "muted tiny", style: { marginTop: "6px" } }, "No ignore areas. Draw one over the food, water tube or anything dark that isn't a bee."));
  }
  const toolbar = h("div", { class: "toolbar" },
    h("button", { class: "small", onclick: autoDish }, "✦ Auto-detect dish"), toolBtns.dish,
    h("span", { class: "sep" }), toolBtns.ellipse, toolBtns.cell,
    h("button", { class: "small ghost", onclick: () => { setup.queen_cell = null; selected = null; markDirty(); draw(); } }, "Clear cell"),
    h("span", { class: "sep" }), toolBtns["ignore-ellipse"], toolBtns["ignore-poly"], copySel,
    h("span", { class: "sep" }), toolBtns.probe,
    h("span", { class: "sep" }), h("span", { class: "muted tiny" }, "Dish Ø mm"), diam);

  /* bee registry */
  let palette = setup.palette && setup.palette.length ? setup.palette : App.defaults.palette;
  const colorSelect = (value) => {
    const s = h("select", { "aria-label": "dot colour" },
      palette.map((c) => h("option", { value: c.name }, c.name)));
    s.value = value;  // set explicitly; the "selected" attribute is unreliable on detached elements
    return s;
  };
  const beeBody = h("tbody", {});
  const renderBees = () => {
    beeBody.replaceChildren(...setup.bees.map((b, i) => {
      const id = h("input", { value: b.bee_id }), col = colorSelect(b.color), lab = h("input", { value: b.label || "", placeholder: "optional" });
      const sw = h("td", {}, codeSwatches(b));
      const upd = () => { b.bee_id = id.value.trim(); b.color = col.value; b.label = lab.value; sw.replaceChildren(codeSwatches(b)); markDirty(); };
      [id, col, lab].forEach((el) => el.addEventListener("change", upd));
      return h("tr", { class: "bee-row" },
        h("td", {}, id), h("td", {}, col), sw, h("td", {}, lab),
        h("td", {}, h("button", { class: "ghost small danger", onclick: () => { setup.bees.splice(i, 1); renderBees(); } }, "✕")));
    }));
  };
  renderBees();
  const addBee = () => {
    const used = new Set(setup.bees.map((b) => b.color));
    const free = palette.find((c) => !used.has(c.name));
    if (!free) { toast("Every palette colour is already used. Add a colour to the palette (Analysis → configuration) first.", "error"); return; }
    setup.bees.push({ bee_id: `W${String(setup.bees.length + 1).padStart(2, "0")}`, color: free.name, label: "" }); renderBees();
  };
  const resetBees = () => {
    setup.bees = setup.palette && setup.palette.length
      ? setup.palette.map((c, i) => ({ bee_id: `W${String(i + 1).padStart(2, "0")}`, color: c.name, label: "" }))
      : structuredClone(App.defaults.setup.bees).map(normalizeBee);
    renderBees();
  };

  /* marking mode: colour dots (identities) or unmarked (anonymous paths) */
  if (!setup.marking) setup.marking = "color";
  const nBees = h("input", { type: "number", min: 1, max: 500, step: 1, value: setup.n_bees || "", placeholder: "e.g. 10", style: { width: "110px" }, "aria-label": "number of bees" });
  nBees.onchange = () => { setup.n_bees = nBees.value ? Number(nBees.value) : null; markDirty(); };
  const markBtns = {
    color: h("button", { class: "small", "data-marking": "color", onclick: () => { setup.marking = "color"; renderMarking(); } }, "● Colour dots"),
    none: h("button", { class: "small", "data-marking": "none", onclick: () => { setup.marking = "none"; renderMarking(); } }, "○ Unmarked (paths only)"),
  };
  /* ---- learn the marks from the video ---- */
  const discoverBox = h("div", { class: "discover-box" });
  const paletteNote = h("div", { class: "muted tiny palette-note" });
  const renderPaletteNote = () => {
    const learned = setup.palette && setup.palette.length;
    paletteNote.replaceChildren(learned
      ? h("span", {}, `Using ${setup.palette.length} marks learned from this video. `, h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); setup.palette = null; setup.mark_model = null; palette = App.defaults.palette; usePalette(null); resetBees(); markDirty(); renderPaletteNote(); } }, "Back to the standard palette"))
      : "Using the standard palette. Better: let the system find the marks in your video.");
  };
  const runDiscover = guard(async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true; btn.textContent = "Looking at the video…";
    discoverBox.replaceChildren(h("div", { class: "progress indeterminate" }, h("div", {})));
    try {
      const res = await api(`/experiments/${e.id}/discover-marks`, { method: "POST", body: {} });
      renderDiscovery(res);
    } finally { btn.disabled = false; btn.textContent = "✦ Find the marks in the video"; }
  });
  function renderDiscovery(res) {
    if (!res.clusters.length) {
      discoverBox.replaceChildren(h("div", { class: "alert warn" }, "No marks found. Check the bees are detected (dish, ignore areas), and that the marks face the camera."));
      return;
    }
    let n = 0;
    const rows = res.clusters.map((c) => {
      const use = h("input", { type: "checkbox", "aria-label": `use ${c.name}` });
      use.checked = c.likely_mark;
      const name = h("input", { value: c.name.replace(/^grey/, "mark"), "aria-label": `name of ${c.name}`, style: { width: "110px" } });
      const bee = h("input", { value: c.likely_mark ? `W${String(++n).padStart(2, "0")}` : "", placeholder: "bee ID", "aria-label": `bee for ${c.name}`, style: { width: "80px" } });
      use.onchange = () => { if (use.checked && !bee.value) bee.value = `W${String(++n).padStart(2, "0")}`; card.classList.toggle("off", !use.checked); };
      const card = h("div", { class: `mark-card ${c.likely_mark ? "" : "off"}` },
        h("div", { class: "mark-head" },
          h("label", { class: "inline-check" }, use, h("span", { class: "swatch big", style: { background: c.display } })),
          name, h("span", { class: "muted tiny" }, "→ bee"), bee,
          h("span", { class: "muted tiny" }, `${c.n_spots} sightings in ${c.n_frames} frames`),
          c.why_not ? h("span", { class: "tiny warn-text" }, c.why_not) : null),
        h("div", { class: "mark-examples" }, c.examples.map((u) => h("img", { src: u, alt: "example", loading: "lazy" }))));
      return { c, use, name, bee, card };
    });
    const apply = () => {
      const chosen = rows.filter((r) => r.use.checked && r.bee.value.trim());
      if (!chosen.length) { toast("Tick at least one mark and give it a bee ID", "error"); return; }
      const byBee = new Map();  // same bee ID on several groups = one mark seen in different light → merge
      for (const r of chosen) {
        const id = r.bee.value.trim();
        if (!byBee.has(id)) byBee.set(id, { name: r.name.value.trim() || r.c.name, labs: [], tol: 0, display: r.c.display });
        const m = byBee.get(id); m.labs.push(r.c.lab); m.tol = Math.max(m.tol, r.c.tol);
      }
      const names = new Set();
      setup.palette = [...byBee.values()].map((m) => { let nm = m.name; for (let k = 2; names.has(nm); k++) nm = `${m.name} ${k}`; names.add(nm); m.name = nm; return { name: nm, labs: m.labs, tol: m.tol, display: m.display }; });
      setup.mark_model = { cuticle_hue_deg: res.cuticle.hue_deg, l_white: res.cuticle.l_white, chroma_max: res.cuticle.chroma_max, min_spot_mm2: res.min_spot_mm2 };
      setup.bees = [...byBee.entries()].map(([id, m]) => ({ bee_id: id, color: m.name, label: "" }));
      setup.marking = "color";
      palette = setup.palette; usePalette(setup.palette);
      renderBees(); renderMarking(); renderPaletteNote(); markDirty();
      discoverBox.replaceChildren(h("div", { class: "alert ok" }, `✓ ${setup.bees.length} bees from ${chosen.length} mark groups. Save the setup to keep them.`));
    };
    discoverBox.replaceChildren(
      h("p", { class: "muted tiny" }, `Found ${res.clusters.length} groups of mark-like spots in ${res.n_frames} frames (${res.n_spots} sightings). `,
        res.excluded_px ? "The queen cell, the ignore areas and a 1 mm band around them were left out. " : "Tip: outline the queen cell and draw ignore areas over food first, so their colours aren't mistaken for marks. ",
        "Tick the real marks and give each a bee. Give two groups the same bee to merge them (the same paint in different light)."),
      ...rows.map((r) => r.card),
      h("div", { class: "row", style: { marginTop: "10px" } }, h("button", { class: "primary use-marks", onclick: apply }, "Use these marks"),
        h("button", { class: "ghost small", onclick: () => discoverBox.replaceChildren() }, "Close")));
  }
  const votes = h("input", { type: "number", min: 1, max: 100, step: 1, value: setup.id_min_votes ?? 3, style: { width: "70px" }, "aria-label": "minimum mark readings" });
  const purity = h("input", { type: "number", min: 50, max: 100, step: 5, value: Math.round((setup.id_min_purity ?? 0.6) * 100), style: { width: "70px" }, "aria-label": "minimum agreement percent" });
  const minProb = h("input", { type: "number", min: 0, max: 95, step: 5, value: Math.round((setup.id_min_probability ?? 0) * 100), style: { width: "70px" }, "aria-label": "minimum identity certainty percent" });
  minProb.onchange = () => { setup.id_min_probability = Number(minProb.value) / 100; markDirty(); };
  votes.onchange = () => { setup.id_min_votes = Number(votes.value); markDirty(); };
  purity.onchange = () => { setup.id_min_purity = Number(purity.value) / 100; markDirty(); };
  const colourPanel = h("div", {},
    h("div", { class: "row", style: { margin: "12px 0 6px", gap: "8px" } },
      h("button", { class: "discover-marks", onclick: runDiscover }, "✦ Find the marks in the video"), paletteNote),
    discoverBox,
    h("div", { class: "row", style: { justifyContent: "space-between", margin: "12px 0 6px" } },
      h("p", { class: "muted tiny", style: { margin: 0 } }, "One colour per bee (marks on the back, the belly, or both)."),
      h("div", { class: "row" }, h("button", { class: "small", onclick: addBee }, "＋ Add"), h("button", { class: "small ghost", onclick: resetBees }, "Defaults"))),
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["ID", "Dot colour", "", "Label", ""].map((x) => h("th", {}, x)))), beeBody)),
    h("div", { class: "id-threshold muted tiny" },
      "A track is named after a bee when its mark was read at least ", votes, " times and at least ", purity,
      " % of the readings agree; the name then applies to that whole piece of track, also where the mark was hidden. ",
      "Other pieces are named by following the bee's motion, with a certainty. Leave out positions less certain than ", minProb,
      " % (0 keeps everything; 50 gives far fewer wrong names but shorter paths)."));
  renderPaletteNote();
  const unmarkedPanel = h("div", { class: "unmarked-panel" },
    h("div", { class: "alert info", style: { margin: "12px 0" } },
      "Bees are tracked without marks. Each track (T001, T002, …) is one bee for as long as it can be followed without doubt. ",
      "After two bees touch, they continue under new track IDs. Use this mode for paths, activity and the total time bees spend at the queen cell, not for per-individual statistics."),
    "");
  const beesCard = h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Bees"),
    h("div", { class: "row segmented" }, markBtns.color, markBtns.none)),
    h("label", { class: "n-bees" }, "Bees in the dish, marked or not (balances false detections against misses)", nBees),
    colourPanel, unmarkedPanel);
  function renderMarking() {
    Object.entries(markBtns).forEach(([k, b]) => b.classList.toggle("active", setup.marking === k));
    colourPanel.classList.toggle("hidden", setup.marking !== "color");
    unmarkedPanel.classList.toggle("hidden", setup.marking !== "none");
  }

  const showCheck = (check) => {
    alerts.replaceChildren(...check.errors.map((m) => h("div", { class: "alert error" }, "✕ ", m)), ...check.warnings.map((m) => h("div", { class: "alert warn" }, "! ", m)),
      !check.errors.length ? h("div", { class: "alert ok" }, "✓ Setup is complete.") : null);
  };
  showCheck(e.check);
  const save = guard(async () => {
    if (setup.dish) setup.dish.diameter_mm = Number(diam.value);
    const r = await api(`/experiments/${e.id}/setup`, { method: "PUT", body: setup });
    setup.queen_cell = r.setup.queen_cell;  // server-normalised (outline regenerated from the ellipse)
    setup.ignore_areas = r.setup.ignore_areas || [];
    showCheck(r.check); dirtyBadge.classList.add("hidden"); draw(); toast("Setup saved");
  });

  body.replaceChildren(h("div", { class: "split" },
    h("div", { class: "card" }, toolbar, stage, hint, cellInfo, areaList,
      h("div", { class: "player" }, h("span", { class: "muted tiny" }, "Frame at"), slider, clock), probeOut),
    h("div", { class: "grid" },
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Status"), h("div", { class: "row" }, dirtyBadge, h("button", { class: "primary", onclick: save }, "Save setup"))), alerts),
      beesCard)));
  renderMarking();
  loadFrame();
}

/* ---------- analysis ---------------------------------------------------- */
async function tabAnalysis(body, e) {
  const jobBox = h("div", {});
  const history = h("div", {});
  const ta = h("textarea", { spellcheck: "false" }, e.config_yaml || "");
  const cfgNote = h("div", { class: "muted tiny" }, e.config_yaml ? "Custom configuration in use." : "Empty = defaults. Paste or load the defaults, edit, and save.");

  const renderJob = (j) => {
    if (!j) { jobBox.replaceChildren(h("p", { class: "muted" }, "No analysis has run yet.")); return; }
    const running = ["queued", "running"].includes(j.status);
    jobBox.replaceChildren(
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("div", { class: "row" }, h("b", {}, `Job #${j.id}`), pill(j.status), j.stage ? h("span", { class: "muted" }, j.stage) : null),
        running ? h("button", { class: "small danger", onclick: guard(async () => { await api(`/jobs/${j.id}/cancel`, { method: "POST" }); toast("Cancelling…"); }) }, "Cancel") : null),
      h("div", { class: `progress ${j.status === "queued" ? "indeterminate" : ""}`, style: { margin: "12px 0 8px" } }, h("div", { style: { width: `${(j.progress || 0) * 100}%` } })),
      h("div", { class: "muted mono tiny" }, j.message || ""),
      j.status === "done" ? h("div", { class: "alert ok", style: { marginTop: "10px" } }, "✓ Finished. ", h("a", { href: `#/exp/${e.id}/results` }, "Open results →")) : null,
      j.status === "failed" ? h("details", { style: { marginTop: "10px" } }, h("summary", { class: "alert error" }, "✕ ", j.message || "failed"), h("pre", { class: "mono tiny", style: { whiteSpace: "pre-wrap" } }, j.error)) : null);
    return running;
  };
  const poll = guard(async () => {
    const latest = (await api(`/experiments/${e.id}`)).latest_job;
    if (!renderJob(latest)) { clearTimers(); if (latest && latest.status === "done") route(); }
  });
  const run = guard(async () => {
    await api(`/experiments/${e.id}/analyze`, { method: "POST" });
    toast("Analysis queued"); renderJob({ id: "…", status: "queued", progress: 0, message: "waiting for the worker" });
    App.timers.add(setInterval(poll, 1500));
  });
  const saveCfg = guard(async () => { await api(`/experiments/${e.id}/config`, { method: "PUT", body: { yaml: ta.value } }); toast("Configuration saved"); cfgNote.textContent = ta.value.trim() ? "Custom configuration in use." : "Using defaults."; });

  const running = renderJob(e.latest_job);
  if (running) App.timers.add(setInterval(poll, 1500));
  history.replaceChildren(e.jobs.length ? h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Job", "Status", "Started", "Finished", "Message"].map((x) => h("th", {}, x)))),
    h("tbody", {}, e.jobs.map((j) => h("tr", {}, h("td", { class: "mono" }, `#${j.id}${j.kind === "render" ? " · video" : ""}`), h("td", {}, pill(j.status)), h("td", { class: "tiny muted" }, fmt.date(j.started_at)), h("td", { class: "tiny muted" }, fmt.date(j.finished_at)), h("td", { class: "muted" }, j.message)))))) : h("p", { class: "muted" }, "–"));

  const blocked = e.check.errors.length > 0 || !e.videos.length;
  body.replaceChildren(h("div", { class: "split" },
    h("div", { class: "grid" },
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Run analysis"),
        h("button", { class: "primary", onclick: run, disabled: blocked || running }, "▶ Analyse recording")),
        blocked ? h("div", { class: "alert warn" }, "Finish the setup first: ", e.check.errors.join("; ") || "upload a video") : h("p", { class: "muted", style: { marginTop: 0 } },
          `${fmt.dur(e.duration_s)} of video. Results of every run are kept; the latest successful run is shown in Results.`),
        jobBox),
      h("div", { class: "card" }, h("h2", {}, "History"), history)),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Configuration"),
      h("div", { class: "row" }, h("button", { class: "small ghost", onclick: () => { ta.value = App.defaults.config_yaml; } }, "Load defaults"), h("button", { class: "small", onclick: saveCfg }, "Save"))),
      cfgNote, ta,
      h("p", { class: "muted tiny" }, "All lengths are in mm and times in seconds. Use the same configuration for every experiment in a study so results stay comparable."))));
}

/* ---------- results ----------------------------------------------------- */
async function tabResults(body, e) {
  if (!e.has_results) { body.replaceChildren(h("div", { class: "card empty" }, h("div", { class: "big" }, "📊"), "No results yet. ", h("a", { href: `#/exp/${e.id}/analysis` }, "Run the analysis"), ".")); return; }
  const r = await api(`/experiments/${e.id}/results`);
  // everything on this page is shown with the setup the analysis used, not the (possibly edited) current one
  App.palette = Object.fromEntries([...App.defaults.palette, ...r.run_setup.palette].map((c) => [c.name, c]));
  const { bees: allBees, unmarked } = subjects(r.run_setup, r.metrics);
  // many anonymous tracks: charts show the tracks that visited, else the longest-tracked ones
  const visitedIds = new Set(r.visits.map((v) => v.bee_id));
  const byCoverage = r.metrics.slice().sort((a, b) => (b.tracked_fraction || 0) - (a.tracked_fraction || 0)).map((m) => m.bee_id);
  const chartIds = unmarked ? byCoverage.filter((id) => visitedIds.has(id)).concat(byCoverage.filter((id) => !visitedIds.has(id))).slice(0, 30).sort() : null;
  const bees = unmarked ? allBees.filter((b) => chartIds.includes(b.bee_id)) : allBees;
  const closed = r.summary.closed_group;  // known number of bees: exactly N identities, with probabilities
  const who = unmarked && !closed ? "track" : "bee";
  const zones = r.zones.map((z) => z.name);
  let zone = zones[0];
  const S = r.summary;

  const zoneBtns = h("div", { class: "row" }, zones.map((z) => h("button", { class: `small ${z === zone ? "active" : ""}`, "data-zone": z, onclick: () => { zone = z; renderZone(); } },
    `${z} (${(r.zones.find((q) => q.name === z) || {}).margin_mm} mm)`)));
  const kpis = h("div", { class: "grid kpis" });
  const cCount = h("div", { class: "chart" });
  const cBars = h("div", { class: "chart" }), cDur = h("div", { class: "chart" }), cGantt = h("div", { class: "chart tall" }), cBinned = h("div", { class: "chart" });
  const metricsBox = h("div", { class: "table-wrap" }), visitsBox = h("div", { class: "table-wrap", style: { maxHeight: "420px" } });

  const kpi = (label, value, hint) => h("div", { class: "card kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), hint ? h("div", { class: "hint" }, hint) : null);

  function renderZone() {
    zoneBtns.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.zone === zone));
    const V = r.visits.filter((v) => v.zone === zone);
    const M = r.metrics;
    const ids = bees.map((b) => b.bee_id);
    const total = V.reduce((a, v) => a + v.duration_s, 0);
    const byBee = Object.fromEntries(ids.map((id) => [id, V.filter((v) => v.bee_id === id)]));
    const top = ids.slice().sort((a, b) => byBee[b].length - byBee[a].length)[0];
    const visitors = ids.filter((id) => byBee[id].length).length;
    const meanCov = M.reduce((a, m) => a + (m.tracked_fraction || 0), 0) / Math.max(1, M.length);
    kpis.replaceChildren(
      kpi("Visits", V.length, `${zone} zone`),
      kpi("Time at the cell", fmt.dur(total), `${fmt.pct(total / Math.max(1, S.duration_s))} of the recording (summed over bees)`),
      unmarked && !closed ? kpi("Tracks", r.metrics.length, `${visitedIds.size} visited the cell`) : kpi("Bees that visited", `${visitors} / ${ids.length}`),
      kpi(unmarked && !closed ? "Track with most visits" : "Most frequent visitor", top && byBee[top].length ? top : "–", top && byBee[top].length ? `${byBee[top].length} visits` : ""),
      kpi("Mean visit", fmt.dur(V.length ? total / V.length : null)),
      unmarked
        ? kpi("Bees per frame", fmt.num(S.mean_bees_per_frame, 1), S.expected_bees ? `of ${S.expected_bees} in the dish` : "on average")
        : kpi("Tracking coverage", fmt.pct(meanCov), `IDs on ${fmt.pct(S.detections_identified_fraction)} of detections`));

    const colors = ids.map((id) => beeColor(bees, id));
    plot(cBars, [{ type: "bar", x: ids, y: ids.map((id) => byBee[id].length), marker: { color: colors }, hovertemplate: "%{x}: %{y} visits<extra></extra>" }],
      { yaxis: { title: "visits", gridcolor: cssVar("--border") }, showlegend: false });
    plot(cDur, [{ type: "box", x: V.map((v) => v.bee_id), y: V.map((v) => v.duration_s), boxpoints: "all", jitter: 0.4, pointpos: 0, marker: { color: cssVar("--honey"), size: 5 },
      line: { color: cssVar("--ink-3") }, fillcolor: "rgba(0,0,0,0)", hovertemplate: "%{x}: %{y:.1f} s<extra></extra>" }],
      { yaxis: { title: "visit duration (s)", gridcolor: cssVar("--border") }, xaxis: { categoryorder: "array", categoryarray: ids }, showlegend: false });

    // Gantt timeline: one row per bee, a bar per visit
    plot(cGantt, ids.map((id) => ({
      type: "bar", orientation: "h", name: id, y: byBee[id].map(() => id), x: byBee[id].map((v) => v.duration_s), base: byBee[id].map((v) => v.start_s),
      marker: { color: beeColor(bees, id) }, customdata: byBee[id].map((v) => [fmt.clock(v.start_s), v.duration_s.toFixed(1), Math.round(v.observed_fraction * 100)]),
      hovertemplate: `${id}<br>start %{customdata[0]}<br>%{customdata[1]} s · %{customdata[2]}% observed<extra></extra>`,
    })), { barmode: "overlay", showlegend: false, xaxis: { title: "time since start (s)", range: [0, S.duration_s], gridcolor: cssVar("--border") },
      yaxis: { categoryorder: "array", categoryarray: ids.slice().reverse(), gridcolor: cssVar("--border") }, bargap: 0.35 });

    // number of bees in the zone over time (all visits, so every track counts, shown or not)
    const ev = r.visits.filter((v) => v.zone === zone).flatMap((v) => [[v.start_s, 1], [v.start_s + v.duration_s, -1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cx = [0], cy = [0];
    let n = 0;
    for (const [t, d] of ev) { cx.push(t, t); cy.push(n, n + d); n += d; }
    cx.push(S.duration_s); cy.push(n);
    plot(cCount, [{ type: "scatter", mode: "lines", x: cx, y: cy, fill: "tozeroy", line: { color: cssVar("--honey"), width: 1.5, shape: "hv" },
      fillcolor: "rgba(232,163,23,0.25)", hovertemplate: "%{x:.0f} s: %{y} bees<extra></extra>" }],
      { xaxis: { title: "time since start (s)", range: [0, S.duration_s] }, yaxis: { title: "bees in zone", rangemode: "tozero", dtick: 1 }, showlegend: false });

    const B = r.binned.filter((b) => b.zone === zone);
    const bins = [...new Set(B.map((b) => b.bin_start_s))].sort((a, b) => a - b);
    plot(cBinned, [{ type: "heatmap", x: bins.map((s) => s / 60), y: ids, z: ids.map((id) => bins.map((s) => (B.find((b) => b.bee_id === id && b.bin_start_s === s) || {}).seconds || 0)),
      colorscale: [[0, "rgba(232,163,23,0.03)"], [1, cssVar("--honey")]], hovertemplate: "%{y} · min %{x}: %{z:.0f} s<extra></extra>", colorbar: { title: { text: "s" }, thickness: 10 } }],
      { xaxis: { title: "time bin start (min)" }, yaxis: { autorange: "reversed" } });

    // metrics table
    const cols = [["bee_id", "Bee", (v) => h("span", { class: "row", style: { gap: "6px" } }, codeSwatches(bees.find((b) => b.bee_id === v) || { bee_id: v }), v)],
      [`${zone}_visits`, "Visits"], [`${zone}_total_s`, "Total (s)", (v) => fmt.num(v, 0)], [`${zone}_mean_s`, "Mean (s)", (v) => fmt.num(v)], [`${zone}_median_s`, "Median (s)", (v) => fmt.num(v)],
      [`${zone}_max_s`, "Longest (s)", (v) => fmt.num(v)], [`${zone}_first_visit_s`, "First visit", (v) => (v == null ? "–" : fmt.clock(v))], [`${zone}_visits_per_h`, "Visits/h", (v) => fmt.num(v)],
      ["distance_m", "Walked (m)", (v) => fmt.num(v, 2)], ["mean_speed_mm_s", "Speed (mm/s)", (v) => fmt.num(v)], ["tracked_fraction", "Coverage", (v) => fmt.pct(v)],
      ["id_probability", "ID certainty", (v) => fmt.pct(v)]];
    metricsBox.replaceChildren(sortableTable(cols, M));
    visitsBox.replaceChildren(sortableTable([["bee_id", "Bee"], ["visit_no", "#"], ["start_s", "Start", (v) => fmt.clock(v)], ["end_s", "End", (v) => fmt.clock(v)],
      ["duration_s", "Duration (s)", (v) => fmt.num(v)], ["observed_fraction", "Observed", (v) => fmt.pct(v)], ["min_distance_mm", "Closest (mm)", (v) => fmt.num(v)], ["id_probability", "ID certainty", (v) => fmt.pct(v)],
      ["start_s", "", (v) => h("a", { href: `#/exp/${e.id}/explorer`, onclick: () => { App.explorerT = v; } }, "view ↗")]], V));
  }

  const dl = (name, label) => h("a", { class: "btn small", href: `/api/experiments/${e.id}/download/${name}` }, "⬇ ", label);

  /* ---- detection balance: false detections vs misses, from the known number of bees ---- */
  const th = S.detection_threshold;
  const balanceChart = h("div", { class: "chart", style: { minHeight: "240px" } });
  const balanceCard = th ? h("div", { class: "card balance-card", style: { marginTop: "16px" } },
    h("div", { class: "card-head" }, h("h2", {}, "Detection balance"),
      h("span", { class: "muted tiny" }, `sensitivity ${th.chosen} chosen: ~${th.median_count} bees per frame for ${th.expected_bees} in the dish`)),
    h("p", { class: "muted tiny", style: { marginTop: "-6px" } },
      "Each sensitivity was tried on sample frames. Too sensitive finds more blobs than bees (false detections); too strict misses bees. ",
      "The one closest to the real count is used (ties: the stricter). If the real count differs, set “Bees in the dish” in Setup."),
    balanceChart) : null;
  if (th) setTimeout(() => plot(balanceChart, [
    { type: "scatter", mode: "lines+markers", x: th.tried.map((t) => t[0]), y: th.tried.map((t) => t[1]), name: "bees found per frame",
      line: { color: cssVar("--honey"), width: 2 }, marker: { size: th.tried.map((t) => (t[0] === th.chosen ? 13 : 7)) },
      hovertemplate: "sensitivity %{x}: %{y} per frame<extra></extra>" },
    { type: "scatter", mode: "lines", x: [th.tried[0][0], th.tried[th.tried.length - 1][0]], y: [th.expected_bees, th.expected_bees],
      name: "bees in the dish", line: { color: cssVar("--ink-3"), dash: "dot" }, hoverinfo: "skip" },
  ], { xaxis: { title: "threshold (higher = stricter)" }, yaxis: { title: "bees per frame", rangemode: "tozero" }, legend: { orientation: "h", y: -0.3 } }), 0);

  /* ---- result videos: annotated recording, paths map, heatmap (each rendered on demand) ---- */
  const VIDEO_KINDS = [
    ["annotated", "Annotated recording", "The original video with every track, head point and trail drawn on."],
    ["paths", "Paths", "A map of the dish with each bee's path and position; bees at the queen cell are ringed."],
    ["heatmap", "Where bees spend time", "Occupancy building up over time (cumulative), or over a sliding window."],
  ];
  const analysedDt = 1 / (S.analysed_fps || 15);
  const STEP_OPTS = [[0, "real time"], [0.5, "0.5 s / step"], [1, "1 s / step"], [2, "2 s / step"], [5, "5 s / step"], [10, "10 s / step"], [30, "30 s / step"], [60, "1 min / step"]];
  const TRAIL_OPTS = [[0, "no trail"], [2, "2 s"], [5, "5 s"], [15, "15 s"], [60, "60 s"], [300, "5 min"], [900, "15 min"], [-1, "entire path"]];
  const WINDOW_OPTS = [[15, "last 15 s"], [60, "last 60 s"], [300, "last 5 min"], [900, "last 15 min"], [3600, "last hour"], [-1, "cumulative"]];
  const FPS_OPTS = [10, 15, 25, 30];
  const vstate = Object.fromEntries(VIDEO_KINDS.map(([k]) => [k, { step_s: k === "annotated" ? 0 : 0.5, trail_s: k === "annotated" ? 5 : -1, fps: 15, bees: null }]));
  let vkind = "annotated", vinfo = r.videos || { annotated: r.annotated_video };
  const vtabs = h("div", { class: "row segmented video-tabs" });
  const vbody = h("div", { class: "video-panel" });
  const videoCard = h("div", { class: "card video-card", style: { marginTop: "16px" } },
    h("div", { class: "card-head" }, h("h2", {}, "Videos"), vtabs), vbody);
  const sel = (opts, value, label, onchange) => {
    const s = h("select", { "aria-label": label, style: { width: "auto" } }, opts.map(([v, l]) => h("option", { value: v }, l)));
    s.value = String(value); s.onchange = () => onchange(Number(s.value)); return s;
  };
  const estimate = (o) => {
    const stepS = o.step_s ? Math.max(analysedDt, Math.round(o.step_s / analysedDt) * analysedDt) : analysedDt;
    const frames = Math.max(1, Math.floor(S.duration_s / stepS));
    const speed = stepS * o.fps;
    return `≈ ${frames.toLocaleString()} frames → ${fmt.dur(frames / o.fps)} of video at ${o.fps} fps, ${speed >= 1.05 ? `${fmt.num(speed, speed < 10 ? 1 : 0)}× faster than real time` : "about real time"}`;
  };
  function renderVideos() {
    vtabs.replaceChildren(...VIDEO_KINDS.map(([k, label]) => h("button", { class: `small ${k === vkind ? "active" : ""}`, "data-video": k,
      onclick: () => { vkind = k; renderVideos(); } }, label, vinfo[k] && vinfo[k].exists ? " ✓" : "")));
    const [, , desc] = VIDEO_KINDS.find(([k]) => k === vkind);
    const o = vstate[vkind], info = vinfo[vkind] || {}, j = info.job;
    const busy = j && ["queued", "running"].includes(j.status);
    const est = h("span", { class: "muted tiny video-estimate" }, estimate(o));
    const refresh = () => { est.textContent = estimate(o); };
    const beeChips = h("div", { class: "row", style: { gap: "4px" } }, ...allBees.slice(0, 40).map((b) => {
      const on = !o.bees || o.bees.includes(b.bee_id);
      const btn = h("button", { class: `small ${on ? "active" : ""}`, style: { borderColor: beeColor(allBees, b.bee_id) } }, b.bee_id);
      btn.onclick = () => {
        const cur = new Set(o.bees || allBees.map((x) => x.bee_id));
        cur.has(b.bee_id) ? cur.delete(b.bee_id) : cur.add(b.bee_id);
        o.bees = cur.size === allBees.length ? null : [...cur];
        btn.classList.toggle("active");
      };
      return btn;
    }));
    const options = h("div", { class: "video-options" },
      h("label", {}, "Step", sel(STEP_OPTS, o.step_s || 0, "step", (v) => { o.step_s = v || null; refresh(); })),
      h("label", {}, vkind === "heatmap" ? "Window" : "Trail",
        vkind === "heatmap" ? sel(WINDOW_OPTS, o.trail_s, "window", (v) => { o.trail_s = v; })
          : sel(TRAIL_OPTS, o.trail_s, "trail", (v) => { o.trail_s = v; })),
      h("label", {}, "Playback", sel(FPS_OPTS.map((f) => [f, `${f} fps`]), o.fps, "playback fps", (v) => { o.fps = v; refresh(); })));
    const player = info.exists && !busy ? h("div", { class: "video-result" },
      h("video", { controls: true, preload: "metadata", src: `/api/experiments/${e.id}/download/${vkind}.mp4?v=${j ? j.id : 0}`, style: { width: "100%", borderRadius: "10px", background: "#111" } }),
      h("div", { class: "row", style: { marginTop: "10px" } },
        h("a", { class: "btn small primary", href: `/api/experiments/${e.id}/download/${vkind}.mp4` }, `⬇ Download ${vkind} video`, h("span", { class: "muted" }, ` (${fmt.bytes(info.size_bytes)})`)),
        info.options ? h("span", { class: "muted tiny video-made-with" }, `made with ${info.options.description}${info.options.bees ? ` · ${info.options.bees.length} bees` : ""}`) : null)) : null;
    const progress = busy ? h("div", {},
      h("div", { class: "row" }, pill(j.status), h("span", { class: "muted mono tiny" }, j.message || "waiting for the worker")),
      h("div", { class: `progress ${j.status === "queued" ? "indeterminate" : ""}`, style: { marginTop: "10px" } }, h("div", { style: { width: `${(j.progress || 0) * 100}%` } }))) : null;
    const failed = j && j.status === "failed" && !busy ? h("div", { class: "alert error" }, "✕ Rendering failed: ", j.message) : null;
    vbody.replaceChildren(
      h("p", { class: "muted", style: { marginTop: 0 } }, desc),
      options,
      h("div", { style: { margin: "8px 0" } }, h("div", { class: "muted tiny", style: { marginBottom: "4px" } }, "Bees (click to leave out)"), beeChips),
      h("div", { class: "row", style: { margin: "12px 0" } },
        h("button", { class: "primary render-video", disabled: busy, onclick: () => startRender(vkind) }, info.exists ? "🎬 Render again with these settings" : `🎬 Render ${VIDEO_KINDS.find(([k]) => k === vkind)[1].toLowerCase()} video`),
        est),
      failed, progress, player);
  }
  const anyBusy = () => Object.values(vinfo).some((x) => x && x.job && ["queued", "running"].includes(x.job.status));
  const pollVideo = guard(async () => {
    vinfo = (await api(`/experiments/${e.id}/results`)).videos;
    renderVideos();
    if (!anyBusy()) clearTimers();
  });
  const startRender = guard(async (kind) => {
    const o = vstate[kind];
    const j = await api(`/experiments/${e.id}/render`, { method: "POST", body: { video: kind, step_s: o.step_s, trail_s: o.trail_s, fps: o.fps, bees: o.bees } });
    vinfo[kind] = { ...(vinfo[kind] || {}), job: j };
    renderVideos();
    if (App.timers.size === 0) App.timers.add(setInterval(pollVideo, 1500));
  });
  renderVideos();
  if (anyBusy()) App.timers.add(setInterval(pollVideo, 1500));

  body.replaceChildren(
    h("div", { class: "card-head" }, zoneBtns, h("span", { class: "muted tiny" }, `run #${r.job_id} · ${S.analysed_frames.toLocaleString()} frames at ${fmt.num(S.analysed_fps, 1)} fps · ${fmt.num(S.px_per_mm, 2)} px/mm`)),
    r.setup_changed ? h("div", { class: "alert warn setup-changed", style: { marginBottom: "16px" } },
      "! The setup was edited after this analysis. These results still show the setup they were made with. ",
      h("a", { href: `#/exp/${e.id}/analysis` }, "Run the analysis again"), " to use the new setup.") : null,
    closed ? h("div", { class: "alert info closed-note", style: { marginBottom: "16px" } },
      `Closed group: ${closed.n_total} bees in the dish → exactly ${closed.n_total} identities`,
      closed.marked.length ? ` (${closed.marked.length} marked, ${closed.unmarked.length} unmarked)` : " (unmarked U01…)",
      `. Every track is assigned to one of them from its mark readings and its motion; the average probability is ${fmt.pct(closed.mean_probability)}. `,
      closed.dropped_detections ? `${closed.dropped_fraction > 0.001 ? fmt.pct(closed.dropped_fraction) : closed.dropped_detections} of detections exceeded ${closed.n_total} bees at once and were dropped as false detections. ` : "",
      closed.mark_share != null && closed.marked.length ? `${fmt.pct(closed.mark_share)} of named positions come from a mark that was read; the rest were followed by motion and are less certain. ` : "",
      "The tables show each bee's and each visit's ID certainty; uncertain positions are labelled with it in the videos.")
    : unmarked ? h("div", { class: "alert info unmarked-note", style: { marginBottom: "16px" } },
      `Unmarked bees: ${r.metrics.length} anonymous tracks. Totals and "bees at the cell" are reliable; `,
      "per-track numbers are lower bounds for individual bees, because a bee continues under a new track after touching another. ",
      "Tip: set “Bees in the dish” in Setup to get exactly that many identities instead. ",
      r.metrics.length > 30 ? "Charts show the 30 most relevant tracks; the tables list all." : "") : null,
    S.warnings.filter((w) => !w.startsWith("unmarked bees")).length ? h("div", { class: "alerts", style: { marginBottom: "16px" } },
      S.warnings.filter((w) => !w.startsWith("unmarked bees")).map((w) => h("div", { class: "alert warn" }, "! ", w,
        w.startsWith("bees measure") && S.bee_size && S.bee_size.suggested_dish_diameter_mm
          ? h("button", { class: "small use-diameter", style: { marginLeft: "10px" }, onclick: guard(async () => {
              const st = structuredClone(e.setup);
              st.dish.diameter_mm = S.bee_size.suggested_dish_diameter_mm;
              await api(`/experiments/${e.id}/setup`, { method: "PUT", body: st });
              toast(`Dish set to ${st.dish.diameter_mm} mm. Re-run the analysis to update mm values.`);
            }) }, `Use ${S.bee_size.suggested_dish_diameter_mm} mm`)
          : null))) : null,
    kpis,
    h("div", { class: "grid cols-2", style: { marginTop: "16px" } },
      h("div", { class: "card" }, h("h2", {}, `Visits per ${who}`), cBars),
      h("div", { class: "card" }, h("h2", {}, "Visit durations"), cDur)),
    h("div", { class: "card", style: { marginTop: "16px" } }, h("h2", {}, "Timeline"), h("p", { class: "muted tiny", style: { marginTop: "-6px" } }, "Each bar is one visit. Hover for start time, duration and how much was directly observed."), cGantt),
    h("div", { class: "card", style: { marginTop: "16px" } }, h("h2", {}, "Bees at the cell over time"),
      h("p", { class: "muted tiny", style: { marginTop: "-6px" } }, "How many bees are in the zone at each moment. Valid with or without marks."), cCount),
    unmarked ? null : h("div", { class: "card", style: { marginTop: "16px" } }, h("h2", {}, "Time at the cell per bin"), cBinned),
    h("div", { class: "card", style: { marginTop: "16px" } }, h("div", { class: "card-head" }, h("h2", {}, unmarked && !closed ? "Per-track summary" : "Per-bee summary"),
      h("div", { class: "row" }, dl("bee_metrics.csv", "metrics"), dl("visits.csv", "visits"), dl("binned_visits.csv", "binned"), dl("trajectories.csv", "trajectories CSV"), dl("trajectories.parquet", "parquet"),
        dl("annotations.csv", "path annotations CSV"), dl("annotations_mot.txt", "annotations (MOT)"), dl("summary.json", "run info"))),
      metricsBox),
    h("div", { class: "card", style: { marginTop: "16px" } }, h("h2", {}, "All visits"), visitsBox),
    balanceCard, videoCard);
  renderZone();
}

function sortableTable(cols, rows) {
  let key = null, dir = 1;
  const tbody = h("tbody", {});
  const render = () => {
    const data = key == null ? rows : rows.slice().sort((a, b) => { const x = a[key], y = b[key]; return (x == null) - (y == null) || (x < y ? -dir : x > y ? dir : 0); });
    tbody.replaceChildren(...data.map((r) => h("tr", {}, cols.map(([k, , f]) => h("td", { class: typeof r[k] === "number" ? "num" : "" }, f ? f(r[k], r) : r[k] ?? "–")))));
  };
  const head = h("tr", {}, cols.map(([k, label]) => h("th", { class: label ? "sortable" : "", onclick: () => { if (!label) return; dir = key === k ? -dir : 1; key = k; render(); } }, label)));
  render();
  return h("table", {}, h("thead", {}, head), tbody);
}

/* ---------- explorer ---------------------------------------------------- */
async function tabExplorer(body, e) {
  if (!e.videos.length) { body.replaceChildren(h("div", { class: "card empty" }, "Upload a video first.")); return; }
  let bees = [];  // filled from the run's own setup and trajectories below
  const duration = e.videos.reduce((a, v) => a + v.duration_s, 0);
  let t = App.explorerT || 0; App.explorerT = 0;
  let playing = false, loading = false;
  const img = h("img", { alt: "frame" });
  const slider = h("input", { type: "range", min: 0, max: Math.floor(duration), step: 0.5, value: t });
  const clock = h("span", { class: "mono" }, fmt.clock(t));
  const trail = h("select", {}, [0, 2, 5, 15, 60].map((s) => h("option", { value: s, selected: s === 5 }, s ? `${s}s trail` : "no trail")));
  const speed = h("select", {}, [[0.5, "0.5 s/step"], [1, "1 s/step"], [5, "5 s/step"], [15, "15 s/step"]].map(([v, l]) => h("option", { value: v, selected: v === 1 }, l)));
  const playBtn = h("button", { class: "small" }, "▶ Play");

  const load = () => { loading = true; img.src = `/api/experiments/${e.id}/frame?t=${t}&overlay=true&trail_s=${trail.value}`; clock.textContent = fmt.clock(t); slider.value = t; };
  img.onload = img.onerror = () => {
    loading = false;
    if (playing) setTimeout(() => { if (!playing) return; t = Math.min(duration, t + Number(speed.value)); if (t >= duration) togglePlay(); load(); }, 60);
  };
  const togglePlay = () => { playing = !playing; playBtn.textContent = playing ? "❚❚ Pause" : "▶ Play"; if (playing && !loading) load(); };
  playBtn.onclick = togglePlay;
  slider.oninput = () => { t = Number(slider.value); clock.textContent = fmt.clock(t); };
  slider.onchange = () => { if (!loading) load(); };
  trail.onchange = load;
  document.onkeydown = (ev) => {
    if (!location.hash.includes("/explorer") || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
    if (ev.key === "ArrowRight") { t = Math.min(duration, t + Number(speed.value)); load(); }
    if (ev.key === "ArrowLeft") { t = Math.max(0, t - Number(speed.value)); load(); }
    if (ev.key === " ") { ev.preventDefault(); togglePlay(); }
  };

  const viewer = h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Video with tracks"), h("span", { class: "muted tiny" }, "← → step · space play · * = interpolated position")),
    h("div", { class: "stage" }, img), h("div", { class: "player" }, playBtn, slider, clock), h("div", { class: "row", style: { marginTop: "8px" } }, trail, speed));

  const cTraj = h("div", { class: "chart tall" }), cHeat = h("div", { class: "chart tall" });
  const pick = h("div", { class: "row" });
  const heatSel = h("select", { style: { width: "auto" } }, h("option", { value: "" }, "all bees"), bees.map((b) => h("option", { value: b.bee_id }, b.bee_id)));
  body.replaceChildren(viewer);
  load();
  if (!e.has_results) { body.append(h("div", { class: "card empty", style: { marginTop: "16px" } }, "Run the analysis to see trajectories here.")); return; }

  body.append(h("div", { class: "grid cols-2", style: { marginTop: "16px" } },
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Paths"), pick), cTraj),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Where bees spend time"), heatSel), cHeat)));

  const [geo, tr] = await Promise.all([api(`/experiments/${e.id}/geometry`), api(`/experiments/${e.id}/results/trajectories?step_s=0.5`)]);
  {
    // registered bees first (in their mark colours), then other identities (U…/T…); at most 30, longest first
    App.palette = Object.fromEntries([...App.defaults.palette, ...(geo.palette || [])].map((c) => [c.name, c]));
    const len = (id) => tr[id].x.filter((v) => v !== null).length;
    const reg = geo.marking === "none" ? [] : (geo.bees || []).filter((b) => tr[b.bee_id]);
    const regIds = new Set(reg.map((b) => b.bee_id));
    const others = Object.keys(tr).filter((id) => !regIds.has(id)).sort((a, b) => len(b) - len(a)).slice(0, 30 - reg.length).sort();
    bees = [...reg, ...others.map((id) => ({ bee_id: id }))];
    heatSel.replaceChildren(h("option", { value: "" }, others.some((id) => id.startsWith("T")) ? "all tracks" : "all bees"),
      ...bees.map((b) => h("option", { value: b.bee_id }, b.bee_id)));
  }
  const shown = new Set(bees.map((b) => b.bee_id).slice(0, 3));
  const outline = () => {
    const R = geo.dish_radius_mm || 75, th = [...Array(121).keys()].map((i) => (i / 120) * 2 * Math.PI);
    const out = [{ type: "scatter", mode: "lines", x: th.map((a) => R * Math.cos(a)), y: th.map((a) => R * Math.sin(a)), line: { color: cssVar("--ink-3"), width: 1.5 }, hoverinfo: "skip", showlegend: false }];
    if (geo.queen_cell) out.push({ type: "scatter", mode: "lines", x: [...geo.queen_cell.x, geo.queen_cell.x[0]], y: [...geo.queen_cell.y, geo.queen_cell.y[0]], fill: "toself", fillcolor: "rgba(229,72,77,.15)", line: { color: "#e5484d", width: 2 }, name: "queen cell", hoverinfo: "name" });
    (geo.zones || []).forEach((z) => out.push({ type: "scatter", mode: "lines", x: [...z.x, z.x[0]], y: [...z.y, z.y[0]], line: { color: "#e5484d", width: 1, dash: "dot" }, name: z.name, hoverinfo: "name", showlegend: false }));
    return out;
  };
  const sq = (R) => ({ xaxis: { range: [-R * 1.05, R * 1.05], zeroline: false, title: "x (mm)", gridcolor: cssVar("--border") }, yaxis: { range: [-R * 1.05, R * 1.05], scaleanchor: "x", zeroline: false, title: "y (mm)", gridcolor: cssVar("--border") } });
  const drawTraj = () => {
    const R = geo.dish_radius_mm || 75;
    const lines = [...shown].filter((id) => tr[id]).map((id) => ({ type: "scattergl", mode: "lines", name: id, x: tr[id].x, y: tr[id].y, customdata: tr[id].t,
      line: { color: beeColor(bees, id), width: 1.2 }, opacity: 0.85, hovertemplate: `${id} · %{customdata:.0f} s<extra></extra>` }));
    plot(cTraj, [...outline(), ...lines], Object.assign(sq(R), { showlegend: false, margin: { l: 48, r: 8, t: 8, b: 40 } }));
  };
  pick.replaceChildren(...bees.map((b) => {
    const btn = h("button", { class: `small ${shown.has(b.bee_id) ? "active" : ""}`, style: { borderColor: beeColor(bees, b.bee_id) } }, b.bee_id);
    btn.onclick = () => { shown.has(b.bee_id) ? shown.delete(b.bee_id) : shown.add(b.bee_id); btn.classList.toggle("active"); drawTraj(); };
    return btn;
  }));
  const drawHeat = guard(async () => {
    const hm = await api(`/experiments/${e.id}/results/heatmap?bins=70${heatSel.value ? `&bee=${encodeURIComponent(heatSel.value)}` : ""}`);
    const R = geo.dish_radius_mm || 75;
    plot(cHeat, [{ type: "heatmap", x: hm.x, y: hm.y, z: hm.z.map((row) => row.map((v) => (v > 0 ? Math.log10(1 + v) : null))), colorscale: "YlOrBr", showscale: false,
      hovertemplate: "x %{x:.0f} · y %{y:.0f} mm<extra></extra>" }, ...outline()], Object.assign(sq(R), { showlegend: false, margin: { l: 48, r: 8, t: 8, b: 40 } }));
  });
  heatSel.onchange = drawHeat;
  drawTraj(); drawHeat();
}

/* ======================================================================== */
/* boot                                                                     */
/* ======================================================================== */
(function theme() {
  const saved = (() => { try { return localStorage.getItem("beetrack-theme"); } catch { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  $("#themeToggle").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("beetrack-theme", next); } catch {}
    route();
  };
})();

(async function boot() {
  try {
    App.defaults = await api("/defaults");
    App.palette = Object.fromEntries(App.defaults.palette.map((c) => [c.name, c]));
    const hlt = await api("/health");
    $("#version").textContent = `v${hlt.version}`;
    if (hlt.version !== UI_VERSION) {
      // The page (static files) is newer or older than the running server: saves would fail in confusing ways.
      document.body.prepend(h("div", { class: "version-banner", role: "alert" },
        h("b", {}, "The server is running a different version "), `(server v${hlt.version}, page v${UI_VERSION}). `,
        "Stop it (Ctrl+C) and start ", h("code", {}, "beetrack serve"), " again, then reload this page."));
    }
  } catch (e) { toast(`Server not reachable: ${e.message}`, "error"); }
  window.addEventListener("hashchange", route);
  route();
})();
