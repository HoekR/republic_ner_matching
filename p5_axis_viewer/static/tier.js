(() => {
  const board = document.getElementById("tier-board");
  const svg = document.getElementById("tier-edges");
  if (!board || !svg) return;

  let edges = [];
  try {
    edges = JSON.parse(board.dataset.edges || "[]");
  } catch (_err) {
    edges = [];
  }

  const kindClass = {
    ALIGNED_TO: "edge-aligned",
    content_match: "edge-content",
    PINNED_TO: "edge-pinned",
  };

  function nodeEl(id) {
    return document.getElementById(`node-${id}`);
  }

  function isVisible(el) {
    if (!el) return false;
    const details = el.closest("details.tier-lane");
    if (details && !details.open) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function center(el, boardBox) {
    const r = el.getBoundingClientRect();
    return {
      x: r.left + r.width / 2 - boardBox.left,
      y: r.top + r.height / 2 - boardBox.top,
    };
  }

  function draw() {
    const boardBox = board.getBoundingClientRect();
    svg.setAttribute("width", String(boardBox.width));
    svg.setAttribute("height", String(Math.max(boardBox.height, 1)));
    svg.innerHTML = "";

    edges.forEach((edge) => {
      const a = nodeEl(edge.from_id);
      const b = nodeEl(edge.to_id);
      if (!isVisible(a) || !isVisible(b)) return;
      const p1 = center(a, boardBox);
      const p2 = center(b, boardBox);
      const midX = (p1.x + p2.x) / 2;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute(
        "d",
        `M ${p1.x} ${p1.y} C ${midX} ${p1.y}, ${midX} ${p2.y}, ${p2.x} ${p2.y}`
      );
      path.setAttribute(
        "class",
        `tier-edge ${kindClass[edge.kind] || ""} ${edge.suspect ? "suspect" : ""}`
      );
      path.setAttribute("fill", "none");
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = edge.hover || edge.kind;
      path.appendChild(title);
      svg.appendChild(path);
    });
  }

  draw();
  window.addEventListener("resize", draw);
  board.querySelectorAll("details.tier-lane").forEach((el) => {
    el.addEventListener("toggle", () => {
      requestAnimationFrame(draw);
    });
  });
})();
