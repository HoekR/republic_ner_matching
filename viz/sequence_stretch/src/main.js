/**
 * Conflict timeline + table for annotated stretch claims.
 * Data: public/stretch.json from sequence_graph.stretch_viz_export
 * Folio panel: OpenSeadragon over diginfra IIIF info.json.
 */
import { select } from "d3-selection";
import { zoom, zoomIdentity } from "d3-zoom";
import OpenSeadragon from "openseadragon";

const COLOURS = {
  conflict: "#c0392b",
  review: "#c0392b",
  physical: "#8e44ad",
  production: "#7f8c8d",
  literal: "#1f4e79",
  ok: "#2d6a4f",
  rail: "#d6cebf",
  ink: "#1a1814",
};

let DATA = null;
let selectedDate = null;
let timelineZoom = null;
let savedTransform = zoomIdentity;
let seaDragon = null;

function iiifInfoUrl(iiifUrl) {
  if (!iiifUrl) return null;
  // .../file.jpg/full/full/0/default.jpg → .../file.jpg/info.json
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

function shortSession(label) {
  if (!label) return "—";
  return label.replace(/^session-\d+-/, "");
}

function renderMeta(meta) {
  document.getElementById("meta").textContent =
    `${meta.inventory}  ${meta.display_lo}..${meta.display_hi}  ·  ` +
    `${meta.n_conflicts} conflicts / ${meta.n_days} days  ·  ` +
    `${meta.n_review_claims} review claims`;
}

function renderLegend() {
  document.getElementById("legend").innerHTML = [
    ["conflict / review", COLOURS.conflict],
    ["physical ≠ production", COLOURS.physical],
    ["aligned pins", COLOURS.ok],
    ["no pin", COLOURS.rail],
  ]
    .map(
      ([label, c]) =>
        `<span><i style="background:${c}"></i>${label}</span>`,
    )
    .join("");
}

function dayColour(day) {
  if (day.review_claims?.length) return COLOURS.review;
  if (day.reasons?.includes("production_ne_physical")) return COLOURS.physical;
  if (day.reasons?.includes("physical_without_production")) return COLOURS.physical;
  if (day.production_session || day.physical_session) return COLOURS.ok;
  return COLOURS.rail;
}

function renderTimeline() {
  const host = document.getElementById("timeline");
  const days = DATA.days;
  const w = Math.max(host.clientWidth || 800, 640);
  const h = 140;
  const padL = 36;
  const padR = 16;
  const trackY = 64;
  const inner = w - padL - padR;
  const n = Math.max(days.length - 1, 1);
  const xAt = (i) => padL + (i / n) * inner;

  const svg = select(host);
  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${w} ${h}`);

  svg
    .append("text")
    .attr("x", padL)
    .attr("y", 18)
    .attr("font-size", 11)
    .attr("font-family", "IBM Plex Mono, monospace")
    .attr("fill", "#5e574c")
    .text("calendar →");

  const viewport = svg.append("g").attr("class", "viewport");

  viewport
    .append("line")
    .attr("x1", padL)
    .attr("y1", trackY)
    .attr("x2", w - padR)
    .attr("y2", trackY)
    .attr("stroke", COLOURS.rail)
    .attr("stroke-width", 2);

  const marks = viewport.append("g").attr("class", "marks");
  days.forEach((day, i) => {
    const x = xAt(i);
    const c = dayColour(day);
    const r = day.is_conflict ? 6.5 : 3.5;
    const selected = day.date === selectedDate;
    const g = marks
      .append("g")
      .attr("class", "day-mark")
      .attr("transform", `translate(${x},${trackY})`)
      .style("cursor", "pointer")
      .on("click", (event) => {
        event.stopPropagation();
        selectDay(day.date);
      });

    g.append("circle")
      .attr("r", r)
      .attr("fill", c)
      .attr("stroke", selected ? COLOURS.ink : "white")
      .attr("stroke-width", selected ? 2 : 1);

    if (day.pin_delta != null && day.pin_delta !== 0) {
      g.append("text")
        .attr("y", -12)
        .attr("text-anchor", "middle")
        .attr("font-size", 9)
        .attr("font-family", "IBM Plex Mono, monospace")
        .attr("fill", COLOURS.physical)
        .text(`${day.pin_delta > 0 ? "+" : ""}${day.pin_delta}`);
    }

    if (
      i === 0 ||
      i === days.length - 1 ||
      day.date.endsWith("-01") ||
      day.is_conflict
    ) {
      g.append("text")
        .attr("y", 28)
        .attr("text-anchor", "middle")
        .attr("font-size", 9)
        .attr("font-family", "IBM Plex Mono, monospace")
        .attr("fill", "#5e574c")
        .text(day.date.slice(5));
    }
  });

  timelineZoom = zoom()
    .scaleExtent([0.6, 12])
    .extent([
      [0, 0],
      [w, h],
    ])
    .translateExtent([
      [-w, -h],
      [2 * w, 2 * h],
    ])
    .on("zoom", (event) => {
      savedTransform = event.transform;
      viewport.attr("transform", event.transform);
    });

  svg.call(timelineZoom);
  svg.call(timelineZoom.transform, savedTransform);
  svg.on("dblclick.zoom", null);
  svg.on("dblclick", () => {
    savedTransform = zoomIdentity;
    svg.call(timelineZoom.transform, zoomIdentity);
  });
}

function renderTable() {
  const only = document.getElementById("conflictsOnly").checked;
  const rows = only
    ? DATA.conflicts
    : DATA.days.filter(
        (d) =>
          d.production_session ||
          d.physical_session ||
          d.review_claims?.length,
      );
  const tbody = document.querySelector("#conflictTable tbody");
  tbody.innerHTML = rows
    .map((d) => {
      const delta =
        d.pin_delta == null
          ? "—"
          : `${d.pin_delta > 0 ? "+" : ""}${d.pin_delta}`;
      const deltaClass =
        d.pin_delta > 0 ? "delta-pos" : d.pin_delta < 0 ? "delta-neg" : "";
      const review = d.review_claims?.[0]
        ? String(d.review_claims[0].scan_num)
        : "—";
      const why = (d.reasons || []).join(", ") || "—";
      const active = d.date === selectedDate ? "active" : "";
      return `<tr data-date="${d.date}" class="${active}">
        <td>${d.date}</td>
        <td>${shortSession(d.production_label)}</td>
        <td>${shortSession(d.physical_label)}</td>
        <td class="${deltaClass}">${delta}</td>
        <td>${review}</td>
        <td>${why}</td>
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
    el.innerHTML = `<h2>Day</h2><p class="muted">Select a day on the timeline or in the table.</p>`;
    return;
  }

  const channels = [
    ["production", day.production_label, COLOURS.production],
    ["physical", day.physical_label, COLOURS.physical],
    [
      "review",
      day.review_claims?.map((r) => `scan ${r.scan_num}`).join(", ") || null,
      COLOURS.review,
    ],
    [
      "literal DATED_AS",
      day.literal_scans?.map((s) => `scan ${s.scan_num}`).join(", ") || null,
      COLOURS.literal,
    ],
  ]
    .map(
      ([name, val, colour]) =>
        `<div class="channel"><span class="dot" style="background:${colour}"></span><span><b>${name}</b> ${val || "—"}</span></div>`,
    )
    .join("");

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
    <p class="kv"><b>reasons</b> ${(day.reasons || []).join(", ") || "—"}</p>
    <p class="kv"><b>pin Δ</b> ${day.pin_delta == null ? "—" : day.pin_delta}</p>
    <div class="channels">${channels}</div>
    ${folio}
    ${notes || '<p class="muted">No note covering this day.</p>'}
  `;

  if (day.iiif_url) {
    mountSeadragon(day.iiif_url);
  }
}

function selectDay(date) {
  selectedDate = date;
  const day = DATA.days.find((d) => d.date === date) || null;
  renderTimeline();
  renderTable();
  renderDetail(day);
}

function bind() {
  document.getElementById("conflictsOnly").addEventListener("change", () => {
    renderTable();
  });
  window.addEventListener("resize", () => renderTimeline());
}

async function main() {
  const res = await fetch("/stretch.json");
  if (!res.ok) {
    document.getElementById("meta").textContent =
      "missing public/stretch.json — run: uv run python -m sequence_graph.stretch_viz_export";
    return;
  }
  DATA = await res.json();
  renderMeta(DATA.meta || {});
  renderLegend();
  bind();
  const first =
    DATA.conflicts?.find((d) => d.review_claims?.length) ||
    DATA.conflicts?.[0] ||
    DATA.days?.[0];
  selectedDate = first?.date || null;
  renderTimeline();
  renderTable();
  renderDetail(first || null);
}

main();
