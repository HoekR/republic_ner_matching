(function () {
  const form = document.getElementById("label-form");
  if (!form) return;

  const date = form.dataset.date;
  const nextId = form.dataset.nextId;
  const needed = form.dataset.needed;
  const markers = {
    cut: form.dataset.markerCut,
    end: form.dataset.markerEnd,
    start: form.dataset.markerStart,
    date_end: form.dataset.markerDateEnd,
    date_start: form.dataset.markerDateStart,
  };
  const editor = document.getElementById("editor");
  const statusEl = document.getElementById("save-status");
  const progress = document.getElementById("progress");
  const cutCount = document.getElementById("cut-count");
  const dateCount = document.getElementById("date-count");

  function countMarker(text, marker) {
    return String(text || "").split(marker).length - 1;
  }

  function updatePills() {
    const text = editor.value;
    const nRes = countMarker(text, markers.cut) + countMarker(text, markers.start);
    const nDate = countMarker(text, markers.date_end) + countMarker(text, markers.date_start);
    cutCount.textContent = `${nRes} / ${needed} res`;
    cutCount.className = "status-pill " + (String(nRes) === String(needed) ? "done" : "pending");
    dateCount.textContent = `${nDate} date`;
  }

  function insertMarker(kind) {
    const marker = markers[kind];
    if (!marker) return;
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.value = editor.value.slice(0, start) + marker + editor.value.slice(end);
    editor.selectionStart = editor.selectionEnd = start + marker.length;
    editor.focus();
    updatePills();
  }

  function payload() {
    return {
      text: editor.value,
      startsMid: document.getElementById("startsMid").checked,
      notes: document.getElementById("notes").value,
      labelled: true,
    };
  }

  async function save(andNext) {
    const nRes = countMarker(editor.value, markers.cut) + countMarker(editor.value, markers.start);
    const mismatch = String(nRes) !== String(needed);
    statusEl.textContent = "Saving…";
    statusEl.className = "save-status";
    try {
      const res = await fetch(`/api/save/${encodeURIComponent(date)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      if (!res.ok) throw new Error(await res.text());
      const body = await res.json();
      if (progress && body.stats) {
        progress.textContent = `${body.stats.labelled} / ${body.stats.total} labelled`;
      }
      statusEl.textContent = mismatch
        ? `Saved (${nRes} transitions vs ${needed} suggested — OK if the day is partial/messy).`
        : "Saved to disk.";
      statusEl.className = "save-status ok";
      if (andNext && nextId) {
        window.location.href = `/label/${encodeURIComponent(nextId)}`;
      }
    } catch (err) {
      statusEl.textContent = `Error: ${err.message}`;
      statusEl.className = "save-status err";
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    save(true);
  });
  document.getElementById("btn-save-stay")?.addEventListener("click", () => save(false));
  form.querySelectorAll("[data-insert]").forEach((btn) => {
    btn.addEventListener("click", () => insertMarker(btn.dataset.insert));
  });
  editor?.addEventListener("input", updatePills);
  updatePills();
})();
