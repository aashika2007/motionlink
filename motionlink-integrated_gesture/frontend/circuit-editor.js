// Circuit workspace + analysis panel, wired to the Person 2 API (/api/circuits/...).
// Self-contained: uses existing elements from index.html and does not modify app.js
// or style.css. Person 3 can restyle or replace it; the API contract is in
// docs/integration.md.
//
// Coordinates: the API uses circuit metres with y UP. The canvas uses CSS pixels with
// y DOWN. Everything goes through view.toCanvas / view.toMetres below.
(() => {
  const canvas = document.getElementById("circuit-canvas");
  const label = document.getElementById("canvas-label");
  const panel = document.getElementById("circuit-workspace");
  const analysis = document.getElementById("analysis-workspace");
  if (!canvas || !panel) return;
  const ctx = canvas.getContext("2d");
  const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  // ------------------------------------------------------------------ styles + controls
  const style = document.createElement("style");
  style.textContent = `
    .ce-controls { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:0 0 12px; font-size:11px; color:var(--muted); }
    .ce-controls select, .ce-controls button { background:#0d1118; color:var(--text); border:1px solid var(--border); border-radius:6px; padding:7px 9px; font-size:11px; }
    .ce-controls button:hover { border-color:var(--accent); }
    .ce-controls input[type=range] { accent-color:var(--accent); width:110px; }
    #circuit-canvas.ce-grab { cursor:grab; } #circuit-canvas.ce-grabbing { cursor:grabbing; }
    .ce-results { display:grid; gap:14px; }
    .ce-cols { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:12px; }
    .ce-box { background:#0d1118; border:1px solid #222a35; border-radius:8px; padding:14px 16px; }
    .ce-box h4 { margin:0 0 10px; font-size:10px; letter-spacing:1.5px; color:var(--muted); font-weight:750; }
    .ce-box dl { display:grid; grid-template-columns:1fr auto; gap:6px 14px; margin:0; font-size:12px; }
    .ce-box dt { color:var(--muted); } .ce-box dd { margin:0; font-weight:700; font-variant-numeric:tabular-nums; text-align:right; }
    .ce-est { border-color:#3a3f22; } .ce-est h4 { color:var(--accent); }
    .ce-note { font-size:10px; color:var(--muted); line-height:1.6; margin:8px 0 0; }
    .ce-table { width:100%; border-collapse:collapse; font-size:11px; font-variant-numeric:tabular-nums; }
    .ce-table th { text-align:left; color:var(--muted); font-weight:600; padding:6px 8px; border-bottom:1px solid var(--border); }
    .ce-table td { padding:6px 8px; border-bottom:1px solid #1a212b; }
    .ce-gain { color:#5fd38d; } .ce-loss { color:#ff6b6b; }
    .ce-summary { margin:0; padding-left:18px; font-size:12px; line-height:1.7; }
    .ce-warn { color:#ff6b6b; }
    .ce-controls button[aria-pressed=true] { border-color:var(--accent); color:var(--accent); }
    .ce-pip { position:absolute; right:10px; bottom:10px; width:150px; border:1px solid var(--border); border-radius:6px; overflow:hidden; background:#000; }
    .ce-pip video { width:100%; display:block; transform:scaleX(-1); }
    .ce-pip span { position:absolute; left:6px; bottom:5px; right:6px; font-size:9px; color:#fff; text-shadow:0 1px 2px #000; }
    .ce-pip span.ce-pinch { color:var(--accent); font-weight:700; }`;
  document.head.appendChild(style);

  const controls = document.createElement("div");
  controls.className = "ce-controls";
  controls.innerHTML = `
    <label>Circuit <select id="ce-circuit" aria-label="Circuit"><option>Loading…</option></select></label>
    <label>Bend width <input id="ce-radius" type="range" min="10" max="150" value="40"> <span id="ce-radius-out">40 m</span></label>
    <button id="ce-reset" type="button">Reset line</button>
    <button id="ce-hands" type="button" aria-pressed="false" title="Use your webcam: pinch the green line to grab it, move your hand to bend it">Hand gestures: off</button>`;
  panel.querySelector(".canvas-wrap").before(controls);
  const select = controls.querySelector("#ce-circuit");
  const radiusInput = controls.querySelector("#ce-radius");

  // ------------------------------------------------------------------ state
  const S = { hand: null, circuit: null, refName: "raceline", refLine: null, refOffsets: null,
              offsets: null, line: null, view: null, drag: null, hover: -1, busy: false, pending: null };

  async function api(path, body) {
    const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    let res;
    try { res = await fetch(path, opts); }
    catch { throw new Error("Server not reachable. Start it with: python app.py, then open http://127.0.0.1:5000"); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }
  const setLabel = (t) => { if (label) label.textContent = t; };
  const setStatus = (id, t) => { const el = document.getElementById(id); if (el) el.textContent = t; };

  // ------------------------------------------------------------------ view transform
  function makeView(bounds, w, h, pad = 18) {
    const bw = bounds.max_x - bounds.min_x, bh = bounds.max_y - bounds.min_y;
    const s = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh);
    const ox = (w - s * bw) / 2, oy = (h - s * bh) / 2;
    return {
      scale: s,
      toCanvas: ([x, y]) => [ox + (x - bounds.min_x) * s, oy + (bounds.max_y - y) * s],   // flip y
      toMetres: ([px, py]) => [bounds.min_x + (px - ox) / s, bounds.max_y - (py - oy) / s],
    };
  }

  // ------------------------------------------------------------------ drawing
  function sizeCanvas() {
    const r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(r.width * dpr));
    canvas.height = Math.max(1, Math.round(r.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return r;
  }
  function path(pts, close) {
    ctx.beginPath();
    pts.forEach((p, i) => { const [x, y] = S.view.toCanvas(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    if (close) ctx.closePath();
  }
  function draw() {
    if (!S.circuit) return;
    const r = sizeCanvas();
    ctx.clearRect(0, 0, r.width, r.height);
    S.view = makeView(S.circuit.bounds_m, r.width, r.height);
    const c = S.circuit, closed = c.closed;
    // track surface
    ctx.beginPath();
    c.left_boundary.forEach((p, i) => { const [x, y] = S.view.toCanvas(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    if (closed) { ctx.closePath(); const [x0, y0] = S.view.toCanvas(c.right_boundary[0]); ctx.moveTo(x0, y0); }
    [...c.right_boundary].reverse().forEach((p) => { const [x, y] = S.view.toCanvas(p); ctx.lineTo(x, y); });
    ctx.closePath();
    ctx.fillStyle = "#1a212b";
    ctx.fill("evenodd");
    ctx.lineWidth = 1.2; ctx.strokeStyle = "#465163";
    path(c.left_boundary, closed); ctx.stroke();
    path(c.right_boundary, closed); ctx.stroke();
    // reference and edited lines
    ctx.setLineDash([5, 4]); ctx.lineWidth = 1.6; ctx.strokeStyle = css("--blue", "#58a6ff");
    path(S.refLine, closed); ctx.stroke(); ctx.setLineDash([]);
    ctx.lineWidth = 2.4; ctx.strokeStyle = css("--accent", "#d9ff43");
    path(S.line, closed); ctx.stroke();
    // start / finish (first centreline point) with direction of travel
    const [sx, sy] = S.view.toCanvas(c.centreline[0]), [tx, ty] = S.view.toCanvas(c.centreline[3]);
    ctx.fillStyle = "#edf1f7"; ctx.beginPath(); ctx.arc(sx, sy, 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "#edf1f7"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(sx + (tx - sx) * 2, sy + (ty - sy) * 2); ctx.stroke();
    if (S.hand) {
      const [hx, hy] = S.hand.px;
      ctx.beginPath(); ctx.arc(hx, hy, S.hand.pinch ? 7 : 11, 0, Math.PI * 2);
      ctx.fillStyle = S.hand.pinch ? css("--accent", "#d9ff43") : "rgba(217,255,67,0.15)"; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = css("--accent", "#d9ff43"); ctx.stroke();
    }
    const i = S.drag ? S.drag.index : S.hover;
    if (i >= 0) {
      const [hx, hy] = S.view.toCanvas(S.line[i]);
      ctx.fillStyle = css("--accent", "#d9ff43"); ctx.beginPath(); ctx.arc(hx, hy, S.drag ? 6 : 4.5, 0, Math.PI * 2); ctx.fill();
    }
  }

  // ------------------------------------------------------------------ editing
  function pointer(e) { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
  function nearest(px, radius = 14) {
    let best = -1, bd = Infinity;
    S.line.forEach((p, i) => { const [x, y] = S.view.toCanvas(p); const d = Math.hypot(x - px[0], y - px[1]); if (d < bd) { bd = d; best = i; } });
    return bd <= radius ? best : -1;
  }
  async function sendDrag(target) {
    if (S.busy) { S.pending = target; return; }
    S.busy = true;
    try {
      const res = await api(`/api/circuits/${S.circuit.id}/drag-to-point`, {
        offsets: S.drag.baseOffsets, grab_xy: S.drag.grabXY, target_xy: target, radius_m: +radiusInput.value });
      S.offsets = res.offsets; S.line = res.line; draw();
    } catch (err) { setLabel(err.message.toUpperCase()); }
    S.busy = false;
    if (S.pending) { const t = S.pending; S.pending = null; if (S.drag) await sendDrag(t); }
  }
  // Shared by mouse/touch and hand gestures: grab(px) → move(px) → release().
  function grab(px, radius) {
    if (!S.circuit || S.drag) return false;
    const i = nearest(px, radius);
    if (i < 0) return false;
    S.drag = { index: i, grabXY: S.line[i], baseOffsets: S.offsets.slice() };
    canvas.classList.add("ce-grabbing");
    draw();
    return true;
  }
  function move(px, radius) {
    if (!S.circuit) return;
    if (S.drag) { sendDrag(S.view.toMetres(px)); return; }
    const h = nearest(px, radius);
    if (h !== S.hover) { S.hover = h; canvas.classList.toggle("ce-grab", h >= 0); draw(); }
  }
  async function release() {
    if (!S.drag) return;
    while (S.busy) await new Promise((r) => setTimeout(r, 20));
    S.drag = null;
    canvas.classList.remove("ce-grabbing");
    draw();
    compare();
  }
  canvas.addEventListener("pointerdown", (e) => { if (grab(pointer(e), 14)) canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => move(pointer(e), 14));
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);

  // ------------------------------------------------------------------ hand gestures (optional)
  // MediaPipe loads only when the button is pressed (frontend/gestures.js). Pinch = grab,
  // move hand = bend, open fingers = release. The mouse keeps working throughout.
  const HAND_RADIUS = 28;  // px: a hand is less precise than a mouse
  const handBtn = controls.querySelector("#ce-hands");
  const pip = document.createElement("div");
  pip.className = "ce-pip"; pip.hidden = true;
  pip.innerHTML = `<video id="ce-cam" playsinline muted></video><span id="ce-cam-state">Starting camera…</span>`;
  panel.querySelector(".canvas-wrap").appendChild(pip);
  const camState = pip.querySelector("#ce-cam-state");
  let gestures = null;

  function handleHand(h) {
    if (!S.circuit || !S.view) return;
    if (!h.present) {
      S.hand = null;
      camState.textContent = "Show one hand to the camera";
      camState.classList.remove("ce-pinch");
      if (S.drag) release();   // hand left the frame: drop the line
      draw();
      return;
    }
    const r = canvas.getBoundingClientRect();
    const px = [h.x * r.width, h.y * r.height];
    S.hand = { px, pinch: h.pinch };
    camState.textContent = h.pinch ? (S.drag ? "Bending the line" : "Pinch near the green line") : "Hand found. Pinch to grab";
    camState.classList.toggle("ce-pinch", h.pinch);
    if (h.pressed) grab(px, HAND_RADIUS);
    else if (h.released) release();
    move(px, HAND_RADIUS);
    draw();
  }

  async function toggleHands() {
    if (gestures && gestures.cameraOn) {
      gestures.stop();
      S.hand = null; pip.hidden = true;
      handBtn.setAttribute("aria-pressed", "false"); handBtn.textContent = "Hand gestures: off";
      if (S.drag) release();
      draw();
      return;
    }
    pip.hidden = false;
    handBtn.disabled = true;
    try {
      const { GestureController } = await import("./gestures.js");
      gestures = gestures || new GestureController(pip.querySelector("#ce-cam"), {
        onHand: handleHand, onStatus: (m) => { camState.textContent = m; } });
      await gestures.start();
      if (!gestures.handsReady) {           // camera works but the hand model didn't load
        gestures.stop(); pip.hidden = true;
        setLabel("HAND TRACKING COULDN'T LOAD (NEEDS INTERNET FOR MEDIAPIPE) · USE THE MOUSE");
      } else {
        handBtn.setAttribute("aria-pressed", "true"); handBtn.textContent = "Hand gestures: on";
      }
    } catch (err) {
      pip.hidden = true;
      setLabel(`${err.message.toUpperCase()} · MOUSE STILL WORKS`);
    }
    handBtn.disabled = false;
  }
  handBtn.addEventListener("click", toggleHands);
  radiusInput.addEventListener("input", () => { controls.querySelector("#ce-radius-out").textContent = `${radiusInput.value} m`; });
  controls.querySelector("#ce-reset").addEventListener("click", () => {
    if (!S.circuit) return;
    S.offsets = S.refOffsets.slice(); S.line = S.refLine.map((p) => p.slice()); draw(); compare();
  });

  // ------------------------------------------------------------------ results
  const f = (v, d = 1) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));
  const sign = (v, d = 3) => {
    if (v === null || v === undefined) return "—";
    const r = Number(Number(v).toFixed(d));          // avoid "-0.0"
    return r === 0 ? (0).toFixed(d) : (r > 0 ? "+" : "") + r.toFixed(d);
  };
  async function compare() {
    if (!S.circuit) return;
    try {
      const r = await api(`/api/circuits/${S.circuit.id}/compare`, {
        reference: S.refName, edited: { offsets: S.offsets }, sections: "corners", max_points: 200 });
      renderResults(r);
    } catch (err) { renderError(err.message); }
  }
  function renderError(msg) {
    const box = analysis && analysis.querySelector(".analysis-empty, .ce-results");
    if (box) box.outerHTML = `<div class="analysis-empty"><span class="analysis-symbol">!</span><div><strong>${msg}</strong></div></div>`;
  }
  function renderResults(r) {
    if (!analysis) return;
    const m = r.measured, e = r.estimated, v = m.edited_validation, p = e.parameters;
    const tag = analysis.querySelector(".tag"); if (tag) tag.textContent = "MEASURED + SIMULATED";
    const changed = r.sections.filter((s) => Math.abs(s.estimated_time_delta_s) >= 0.001 || Math.abs(s.length_delta_m) >= 0.1);
    const rows = (changed.length ? changed : r.sections.slice(0, 6)).map((s) => `
      <tr><td>${s.label}</td><td>${f(s.from_station_m, 0)}–${f(s.to_station_m, 0)} m</td>
      <td>${sign(s.length_delta_m, 1)} m</td>
      <td>${f(s.reference_min_speed_mps * 3.6, 0)} → ${f(s.edited_min_speed_mps * 3.6, 0)} km/h</td>
      <td class="${s.estimated_time_delta_s < 0 ? "ce-gain" : s.estimated_time_delta_s > 0 ? "ce-loss" : ""}">${sign(s.estimated_time_delta_s)} s</td></tr>`).join("");
    const html = `<div class="ce-results">
      <div class="ce-cols">
        <div class="ce-box"><h4>MEASURED GEOMETRY · ${S.circuit.name.toUpperCase()}</h4><dl>
          <dt>Reference line (${S.refName === "raceline" ? "TUMFTM min-curvature" : "centreline"})</dt><dd>${f(m.reference_length_m)} m</dd>
          <dt>Edited line</dt><dd>${f(m.edited_length_m)} m</dd>
          <dt>Difference</dt><dd>${sign(m.length_delta_m, 1)} m</dd>
          <dt>Edited line inside track limits</dt><dd class="${v.valid ? "" : "ce-warn"}">${v.valid ? "Yes" : `No (${f(v.max_excess_m, 2)} m over)`}</dd>
          <dt>Mean |curvature|, ref → edited</dt><dd>${f(m.reference_mean_abs_curvature_1pm * 1000, 2)} → ${f(m.edited_mean_abs_curvature_1pm * 1000, 2)} /km</dd>
        </dl><p class="ce-note">From TUMFTM circuit geometry. Circuit metres, not video pixels.</p></div>
        <div class="ce-box ce-est"><h4>SIMULATED ESTIMATE · NOT A LAP TIME</h4><dl>
          <dt>Reference line</dt><dd>${f(e.reference_time_s, 2)} s</dd>
          <dt>Edited line</dt><dd>${f(e.edited_time_s, 2)} s</dd>
          <dt>Difference</dt><dd class="${e.time_delta_s < 0 ? "ce-gain" : e.time_delta_s > 0 ? "ce-loss" : ""}">${sign(e.time_delta_s)} s</dd>
        </dl><p class="ce-note">${r.label}<br>Assumed: lateral ${p.a_lat_max_mps2} m/s², accel ${p.a_accel_max_mps2} m/s², braking ${p.a_brake_max_mps2} m/s², top speed ${f(p.v_max_mps * 3.6, 0)} km/h (${p.note}).</p></div>
      </div>
      <div class="ce-box"><h4>${changed.length ? "CHANGED SECTIONS" : "SECTIONS"} · DETECTED, NOT OFFICIAL TURN NUMBERS</h4>
        <table class="ce-table"><thead><tr><th>Section</th><th>Distance</th><th>Length Δ</th><th>Min speed (est.)</th><th>Time Δ (est.)</th></tr></thead><tbody>${rows}</tbody></table></div>
      <ul class="ce-summary">${r.summary.map((s) => `<li>${s}</li>`).join("")}</ul>
      <p class="ce-note">Circuit data: TUMFTM racetrack-database (LGPL-3.0), ${S.circuit.source.track_file}${S.circuit.source.commit ? ` @ ${S.circuit.source.commit.slice(0, 7)}` : ""}.</p>
    </div>`;
    const box = analysis.querySelector(".analysis-empty, .ce-results");
    if (box) box.outerHTML = html; else analysis.insertAdjacentHTML("beforeend", html);
    const perf = document.querySelectorAll(".metric-card strong")[3];
    if (perf) perf.textContent = `${sign(e.time_delta_s)} S (ESTIMATE)`;
  }

  // ------------------------------------------------------------------ loading
  async function loadCircuit(id) {
    setLabel("LOADING CIRCUIT…");
    const c = await api(`/api/circuits/${encodeURIComponent(id)}`);
    S.circuit = c;
    S.refName = c.raceline ? "raceline" : "centreline";
    S.refLine = c.raceline || c.centreline;
    S.refOffsets = c.raceline_offsets || c.centreline.map(() => 0);
    S.offsets = S.refOffsets.slice();
    S.line = S.refLine.map((p) => p.slice());
    S.hover = -1;
    setStatus("circuit-status", `${c.name.toUpperCase()} · TUMFTM`);
    setLabel(`${c.name.toUpperCase()} · ${f(c.centreline_length_m / 1000, 3)} KM CENTRELINE · DRAG THE GREEN LINE`);
    const legendRef = panel.querySelector(".legend span");
    if (legendRef) legendRef.lastChild.textContent = c.raceline ? " Reference line (TUMFTM minimum-curvature)" : " Reference line (centreline; no race line in dataset)";
    const helper = panel.querySelector(".helper");
    if (helper) helper.textContent = "Real circuit geometry in metres (TUMFTM). The edited line is kept inside the track limits; lap times shown below are simulated estimates.";
    draw();
    compare();
  }
  async function init() {
    try {
      const { circuits } = await api("/api/circuits");
      if (!circuits.length) {
        select.innerHTML = "<option>None downloaded</option>";
        setLabel("NO CIRCUIT DATA · RUN: python scripts/fetch_tumftm.py --tracks Spielberg");
        return;
      }
      select.innerHTML = circuits.map((c) => `<option value="${c.id}">${c.name}${c.series ? ` (${c.series})` : ""}</option>`).join("");
      const pick = circuits.find((c) => c.id === "spielberg") || circuits[0];
      select.value = pick.id;
      select.addEventListener("change", () => loadCircuit(select.value).catch((err) => setLabel(err.message.toUpperCase())));
      await loadCircuit(pick.id);
    } catch (err) {
      select.innerHTML = "<option>Unavailable</option>";
      setLabel(err.message.toUpperCase());
    }
  }
  // app.js clears the canvas on resize; redraw afterwards (this listener is added later).
  window.addEventListener("resize", () => requestAnimationFrame(draw));
  window.MotionLinkCircuit = { state: S, compare, handleHand };
  init();
})();
