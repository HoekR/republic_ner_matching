(function () {
  const form = document.getElementById("label-form");
  if (!form) return;

  const exampleId = form.dataset.exampleId;
  const nextId = form.dataset.nextId;
  const marker = form.dataset.marker || "|||CUT|||";
  const expectedCuts = form.dataset.expectedCuts || "?";
  const statusEl = document.getElementById("save-status");
  const progress = document.getElementById("progress");
  const editor = document.getElementById("editor");
  const cutCount = document.getElementById("cut-count");
  const seeded = document.getElementById("seeded-text");

  function selectedVerdict() {
    const el = form.querySelector('input[name="verdict"]:checked');
    return el ? el.value : "defer";
  }

  function countCuts(text) {
    return String(text || "").split(marker).length - 1;
  }

  function updateCutPill() {
    if (!cutCount || !editor) return;
    const n = countCuts(editor.value);
    const verdict = selectedVerdict();
    cutCount.textContent = `${n} cuts (expect ${expectedCuts})`;
    const ok = verdict !== "approve" || String(n) === String(expectedCuts);
    cutCount.className = "status-pill " + (ok ? "done" : "pending");
  }

  function formPayload() {
    return {
      text: editor.value,
      note: document.getElementById("note").value,
      uncertain: document.getElementById("uncertain").checked,
      verdict: selectedVerdict(),
      labelled: true,
    };
  }

  async function save(andNext) {
    const verdict = selectedVerdict();
    const n = countCuts(editor.value);
    if (verdict === "approve" && n === 0 && Number(expectedCuts) > 0) {
      statusEl.textContent = `approve needs ${expectedCuts} ${marker} marker(s), or choose defer / skip.`;
      statusEl.className = "save-status err";
      return;
    }
    let warn = false;
    if (verdict === "approve" && String(n) !== String(expectedCuts)) {
      warn = true;
    }
    statusEl.textContent = "Saving…";
    statusEl.className = "save-status";
    try {
      const res = await fetch(`/api/save/${encodeURIComponent(exampleId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formPayload()),
      });
      if (!res.ok) throw new Error(await res.text());
      const body = await res.json();
      if (progress && body.stats) {
        progress.textContent = `${body.stats.labelled} / ${body.stats.total} labelled`;
      }
      const offsets = (body.row && body.row.gold_offsets) || [];
      statusEl.textContent = warn
        ? `Saved — ${n} cuts vs expect ${expectedCuts} (marked uncertain). offsets=${JSON.stringify(offsets)}`
        : `Saved. offsets=${JSON.stringify(offsets)}`;
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

  document.getElementById("btn-insert-cut")?.addEventListener("click", () => {
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.value = editor.value.slice(0, start) + marker + editor.value.slice(end);
    editor.selectionStart = editor.selectionEnd = start + marker.length;
    editor.focus();
    updateCutPill();
  });

  document.getElementById("btn-reset-machine")?.addEventListener("click", () => {
    if (!seeded) return;
    editor.value = seeded.value;
    updateCutPill();
    statusEl.textContent = "Reset to machine cuts (unsaved).";
    statusEl.className = "save-status";
  });

  editor?.addEventListener("input", updateCutPill);
  form.querySelectorAll('input[name="verdict"]').forEach((el) => {
    el.addEventListener("change", updateCutPill);
  });
  updateCutPill();
})();
