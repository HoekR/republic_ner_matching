/**
 * Before→after bipartite morph for hard recalibration.
 * Data: public/remediation.json from sequence_graph.remediation_viz_export
 *
 * t=0: production PINNED_TO (contested lids)
 * t=1: hard Session→Scan→Date path (OBSERVED_ON∘DATED_AS)
 * Intermediate: date→session edge endpoints interpolate in Y.
 */
import { select } from "d3-selection";
import { easeCubicInOut } from "d3-ease";
import { interpolateNumber } from "d3-interpolate";
import OpenSeadragon from "openseadragon";

const COLOURS = {
  production: "#7f8c8d",
  hard: "#2d6a4f",
  scan: "#1f4e79",
  review: "#c0392b",
  literal: "#b8860b",
  rail: "#d6cebf",
  ink: "#1a1814",
  muted: "#5e574c",
  disagree: "#8e44ad",
};

let DATA = null;
let selectedDate = null;
let morphT = 0;
let seaDragon = null;
let playing = false;
let playTimer = null;

function iiifInfoUrl(iiifUrl) {
  if (!iiifUrl) return null;
  const m = iiifUrl.match(/^(https?:\/\/.+?\.(?:jpg|jpeg|png))\/full\//i);
  if (m) return `${m[1]}/info.json`;
  if (iiifUrl.endsWith("/info.json")) return iiifUrl;
  return null;
}

function destroyViewer() {
  if (seaDragon) {
    seaDragon.destroy();
    seaDragon = null;
  }
}

function mountSeadragon(iiifUrl) {
  destroyViewer();
  const host = document.getElementById("osd");
  if (!host || !iiifUrl) return;
  const info = iiifInfoUrl(iiifUrl);
  seaDragon = OpenSeadragon({
    element: host,
    prefixUrl:
      "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/images/",
    tileSources: info || { type: "image", url: iiifUrl },
    showNavigator: true,
    navigatorPosition: "BOTTOM_RIGHT",
    gestureSettingsMouse: { clickToZoom: true, dblClickToZoom: true },
    maxZoomPixelRatio: 4,
    visibilityRatio: 0.8,
    homeFillsViewer: true,
  });
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function shortSession(label) {
  if (!label) return "—";
  return String(label).replace(/^session-\d+-/, "");
}

function renderMeta(meta) {
  document.getElementById("meta").textContent =
    `${meta.inventory}  focus ${meta.focus_lo}..${meta.focus_hi}  ·  ` +
    `lag ${meta.lag_calendar_lo}..${meta.lag_calendar_hi}  ·  ` +
    `${meta.n_dates} dates / ${meta.n_sessions} sessions / ${meta.n_scans} scans  ·  ` +
    `${meta.n_production_disagree} production≠hard  ·  median Δ ${meta.median_delta}`;
}

function renderLegend() {
  document.getElementById("legend").innerHTML = [
    ["production pin (before)", COLOURS.production],
    ["hard map (after)", COLOURS.hard],
    ["OBSERVED_ON / DATED_AS scan", COLOURS.scan],
    ["literal opening", COLOURS.literal],
    ["held-out review", COLOURS.review],
  ]
    .map(
      ([label, c]) =>
        `<span><i style="background:${c}"></i>${label}</span>`,
    )
    .join("");
}

function layout() {
  const host = document.getElementById("morphSvg");
  const w = Math.max(host.clientWidth || 900, 720);
  const n = Math.max(DATA.dates.length, DATA.sessions.length, 1);
  const h = Math.max(420, 28 + n * 22);
  const padT = 28;
  const padB = 20;
  const padL = 72;
  const padR = 72;
  const showScans = document.getElementById("showScans").checked;
  const xSess = padL;
  const xScan = showScans ? w * 0.5 : null;
  const xDate = w - padR;
  const innerH = h - padT - padB;

  const dateY = new Map();
  DATA.dates.forEach((d, i) => {
    const t = DATA.dates.length <= 1 ? 0.5 : i / (DATA.dates.length - 1);
    dateY.set(d.date, padT + t * innerH);
  });

  const sessY = new Map();
  DATA.sessions.forEach((s, i) => {
    const t = DATA.sessions.length <= 1 ? 0.5 : i / (DATA.sessions.length - 1);
    sessY.set(s.id, padT + t * innerH);
  });

  const scanY = new Map();
  if (showScans && DATA.scans.length) {
    DATA.scans.forEach((s, i) => {
      const t = DATA.scans.length <= 1 ? 0.5 : i / (DATA.scans.length - 1);
      scanY.set(s.scan_num, padT + t * innerH);
    });
  }

  return { w, h, padT, xSess, xScan, xDate, dateY, sessY, scanY, showScans };
}

function edgePath(x0, y0, x1, y1) {
  const mx = (x0 + x1) / 2;
  return `M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1}`;
}

function renderMorph() {
  const L = layout();
  const svg = select("#morphSvg");
  svg.attr("viewBox", `0 0 ${L.w} ${L.h}`).attr("width", "100%");
  svg.selectAll("*").remove();

  const g = svg.append("g").attr("class", "morph-root");

  // rails
  for (const [x, label] of [
    [L.xSess, "sessions"],
    [L.xDate, "dates"],
  ]) {
    g.append("line")
      .attr("x1", x)
      .attr("y1", L.padT - 8)
      .attr("x2", x)
      .attr("y2", L.h - 16)
      .attr("stroke", COLOURS.rail)
      .attr("stroke-width", 2);
    g.append("text")
      .attr("x", x)
      .attr("y", 14)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-family", "IBM Plex Mono, monospace")
      .attr("fill", COLOURS.muted)
      .text(label);
  }
  if (L.showScans && L.xScan != null) {
    g.append("line")
      .attr("x1", L.xScan)
      .attr("y1", L.padT - 8)
      .attr("x2", L.xScan)
      .attr("y2", L.h - 16)
      .attr("stroke", COLOURS.rail)
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "4 3");
    g.append("text")
      .attr("x", L.xScan)
      .attr("y", 14)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-family", "IBM Plex Mono, monospace")
      .attr("fill", COLOURS.muted)
      .text("scans (hard path)");
  }

  // session nodes
  DATA.sessions.forEach((s) => {
    const y = L.sessY.get(s.id);
    const node = g
      .append("g")
      .attr("transform", `translate(${L.xSess},${y})`);
    node
      .append("circle")
      .attr("r", 4.5)
      .attr("fill", COLOURS.ink);
    node
      .append("text")
      .attr("x", -10)
      .attr("dy", "0.35em")
      .attr("text-anchor", "end")
      .attr("font-size", 10)
      .attr("font-family", "IBM Plex Mono, monospace")
      .attr("fill", COLOURS.muted)
      .text(s.label);
    if (document.getElementById("showEvidence").checked && s.literal_opening) {
      node
        .append("circle")
        .attr("cx", 10)
        .attr("r", 3)
        .attr("fill", COLOURS.literal);
    }
  });

  // date nodes
  DATA.dates.forEach((d) => {
    const y = L.dateY.get(d.date);
    const selected = d.date === selectedDate;
    const node = g
      .append("g")
      .attr("transform", `translate(${L.xDate},${y})`)
      .style("cursor", "pointer")
      .on("click", () => selectDay(d.date));
    node
      .append("circle")
      .attr("r", selected ? 6 : 4.5)
      .attr("fill", d.production_disagrees ? COLOURS.disagree : COLOURS.ink)
      .attr("stroke", selected ? COLOURS.ink : "none")
      .attr("stroke-width", selected ? 2 : 0);
    node
      .append("text")
      .attr("x", 10)
      .attr("dy", "0.35em")
      .attr("font-size", 10)
      .attr("font-family", "IBM Plex Mono, monospace")
      .attr("fill", COLOURS.muted)
      .text(d.date.slice(5));
    if (document.getElementById("showEvidence").checked && d.review_held_out) {
      node
        .append("circle")
        .attr("cx", -12)
        .attr("r", 3.5)
        .attr("fill", COLOURS.review);
    }
  });

  // scan nodes (mid rail)
  if (L.showScans) {
    DATA.scans.forEach((s) => {
      const y = L.scanY.get(s.scan_num);
      const opacity = 0.15 + 0.85 * morphT;
      g.append("circle")
        .attr("cx", L.xScan)
        .attr("cy", y)
        .attr("r", 3)
        .attr("fill", COLOURS.scan)
        .attr("opacity", opacity);
      if (DATA.scans.length <= 40 || morphT > 0.55) {
        g.append("text")
          .attr("x", L.xScan)
          .attr("y", y - 7)
          .attr("text-anchor", "middle")
          .attr("font-size", 8)
          .attr("font-family", "IBM Plex Mono, monospace")
          .attr("fill", COLOURS.scan)
          .attr("opacity", opacity)
          .text(s.scan_num);
      }
    });
  }

  // pin edges: morph session endpoint from production → hard
  DATA.dates.forEach((d) => {
    const yDate = L.dateY.get(d.date);
    const yProd = L.sessY.get(d.production_session);
    const yHard = L.sessY.get(d.hard_session);
    if (yDate == null) return;
    if (yProd == null && yHard == null) return;

    const ySess =
      yProd != null && yHard != null
        ? lerp(yProd, yHard, morphT)
        : yHard ?? yProd;
    const stroke =
      morphT < 0.5
        ? COLOURS.production
        : d.production_disagrees
          ? COLOURS.hard
          : COLOURS.hard;
    const width = d.date === selectedDate ? 2.4 : 1.35;
    const opacity = d.production_disagrees
      ? 0.35 + 0.55 * Math.abs(morphT - 0.5) * 2
      : 0.55;

    g.append("path")
      .attr("d", edgePath(L.xSess, ySess, L.xDate, yDate))
      .attr("fill", "none")
      .attr("stroke", stroke)
      .attr("stroke-width", width)
      .attr("opacity", opacity)
      .style("cursor", "pointer")
      .on("click", () => selectDay(d.date));

    // hard path via scans (fades in)
    if (L.showScans && L.xScan != null && morphT > 0.05) {
      const pathOpacity = Math.max(0, (morphT - 0.05) / 0.95) * 0.75;
      const bridges = d.bridge_scans?.length
        ? d.bridge_scans
        : d.focus_scan != null
          ? [d.focus_scan]
          : [];
      bridges.forEach((sn) => {
        const yScan = L.scanY.get(sn);
        if (yScan == null || yHard == null) return;
        g.append("path")
          .attr("d", edgePath(L.xSess, yHard, L.xScan, yScan))
          .attr("fill", "none")
          .attr("stroke", COLOURS.scan)
          .attr("stroke-width", 1.1)
          .attr("opacity", pathOpacity);
        g.append("path")
          .attr("d", edgePath(L.xScan, yScan, L.xDate, yDate))
          .attr("fill", "none")
          .attr("stroke", COLOURS.scan)
          .attr("stroke-width", 1.1)
          .attr("opacity", pathOpacity);
      });
    }
  });

  // morph caption
  const phase =
    morphT < 0.08
      ? "before — production PINNED_TO"
      : morphT > 0.92
        ? "after — hard OBSERVED_ON ∘ DATED_AS"
        : `morph t=${morphT.toFixed(2)}`;
  g.append("text")
    .attr("x", L.w / 2)
    .attr("y", L.h - 4)
    .attr("text-anchor", "middle")
    .attr("font-size", 11)
    .attr("font-family", "IBM Plex Mono, monospace")
    .attr("fill", COLOURS.ink)
    .text(phase);
}

function evidenceLabel(d) {
  const bits = [];
  if (d.literal_opening) bits.push("literal");
  if (d.review_held_out) bits.push("review✓");
  if (d.production_disagrees) bits.push("shifted");
  return bits.join(", ") || "—";
}

function renderTable() {
  const tbody = document.querySelector("#dayTable tbody");
  tbody.innerHTML = DATA.dates
    .map((d) => {
      const delta =
        d.pin_delta == null
          ? "—"
          : `${d.pin_delta > 0 ? "+" : ""}${d.pin_delta}`;
      const deltaClass =
        d.pin_delta > 0 ? "delta-pos" : d.pin_delta < 0 ? "delta-neg" : "";
      const bridge = d.bridge_scans?.[0] ?? d.focus_scan ?? "—";
      const active = d.date === selectedDate ? "active" : "";
      return `<tr data-date="${d.date}" class="${active}">
        <td>${d.date}</td>
        <td>${shortSession(d.production_label)}</td>
        <td>${shortSession(d.hard_label)}</td>
        <td class="${deltaClass}">${delta}</td>
        <td>${bridge}</td>
        <td>${evidenceLabel(d)}</td>
      </tr>`;
    })
    .join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => selectDay(tr.dataset.date));
  });
}

function renderDetail(day) {
  destroyViewer();
  const el = document.getElementById("detail");
  if (!day) {
    el.innerHTML = `<h2>Day</h2><p class="muted">Select a date on the morph or in the table.</p>`;
    return;
  }
  const review = day.review_held_out;
  const notes = (day.notes || [])
    .map(
      (n) =>
        `<div class="note"><div class="muted">${n.review_id || ""} · ${n.flag || ""}</div>${(n.note || "").replace(/</g, "&lt;")}</div>`,
    )
    .join("");
  const folio = day.iiif_url
    ? `<div id="osd" class="osd"></div>
       <p class="muted">scroll/pinch zoom · drag pan ·
         <a href="${day.iiif_url}" target="_blank" rel="noreferrer">full IIIF · scan ${day.focus_scan ?? "?"}</a>
       </p>`
    : `<p class="muted">No IIIF for this day.</p>`;

  el.innerHTML = `
    <h2>Day</h2>
    <p class="date">${day.date}</p>
    <p class="kv"><b>before</b> ${shortSession(day.production_label)} (production PINNED_TO)</p>
    <p class="kv"><b>after</b> ${shortSession(day.hard_label)} (hard composite)</p>
    <p class="kv"><b>pin Δ</b> ${day.pin_delta == null ? "—" : day.pin_delta}</p>
    <p class="kv"><b>bridge scans</b> ${(day.bridge_scans || []).join(", ") || "—"}</p>
    <p class="kv"><b>OBSERVED_ON</b> ${(day.observed_scans || []).join(", ") || "—"}</p>
    <p class="kv"><b>DATED_AS</b> ${(day.dated_as_scans || []).join(", ") || "—"}</p>
    <p class="kv"><b>literal opening</b> ${day.literal_opening ? "yes" : "no"}</p>
    <p class="kv"><b>held-out review</b> ${
      review
        ? `scan ${review.review_scan} · on_hard=${review.review_scan_on_hard_dated_path}`
        : "—"
    }</p>
    <div class="channels">
      <div class="channel"><span class="dot" style="background:${COLOURS.production}"></span><span>production lid (dropped)</span></div>
      <div class="channel"><span class="dot" style="background:${COLOURS.hard}"></span><span>hard map active</span></div>
      <div class="channel"><span class="dot" style="background:${COLOURS.scan}"></span><span>OBSERVED_ON ∘ DATED_AS</span></div>
    </div>
    ${folio}
    ${notes || '<p class="muted">No note covering this day.</p>'}
  `;
  if (day.iiif_url) mountSeadragon(day.iiif_url);
}

function selectDay(date) {
  selectedDate = date;
  const day = DATA.dates.find((d) => d.date === date) || null;
  renderMorph();
  renderTable();
  renderDetail(day);
}

function setMorph(t, { render = true } = {}) {
  morphT = Math.max(0, Math.min(1, t));
  const slider = document.getElementById("morph");
  slider.value = String(Math.round(morphT * 1000));
  if (render) renderMorph();
}

function playMorph() {
  if (playing) {
    playing = false;
    if (playTimer) cancelAnimationFrame(playTimer);
    document.getElementById("play").textContent = "play";
    return;
  }
  playing = true;
  document.getElementById("play").textContent = "pause";
  const start = morphT >= 0.99 ? 0 : morphT;
  const from = start;
  const to = 1;
  const dur = 1800;
  const t0 = performance.now();
  const interp = interpolateNumber(from, to);

  function frame(now) {
    if (!playing) return;
    const u = Math.min(1, (now - t0) / dur);
    setMorph(interp(easeCubicInOut(u)));
    if (u < 1) {
      playTimer = requestAnimationFrame(frame);
    } else {
      playing = false;
      document.getElementById("play").textContent = "play";
    }
  }
  playTimer = requestAnimationFrame(frame);
}

function bind() {
  document.getElementById("morph").addEventListener("input", (e) => {
    playing = false;
    document.getElementById("play").textContent = "play";
    setMorph(Number(e.target.value) / 1000);
  });
  document.getElementById("play").addEventListener("click", playMorph);
  document.getElementById("showScans").addEventListener("change", renderMorph);
  document
    .getElementById("showEvidence")
    .addEventListener("change", renderMorph);
  window.addEventListener("resize", () => renderMorph());
}

async function main() {
  const res = await fetch("/remediation.json");
  if (!res.ok) {
    document.getElementById("meta").textContent =
      "missing public/remediation.json — run: uv run python -m sequence_graph.remediation_viz_export";
    return;
  }
  DATA = await res.json();
  renderMeta(DATA.meta || {});
  renderLegend();
  bind();
  selectedDate =
    DATA.dates.find((d) => d.review_held_out)?.date ||
    DATA.dates.find((d) => d.production_disagrees)?.date ||
    DATA.dates[0]?.date ||
    null;
  setMorph(0, { render: false });
  renderMorph();
  renderTable();
  renderDetail(DATA.dates.find((d) => d.date === selectedDate) || null);
}

main();
