(function () {
  const form = document.getElementById("label-form");
  if (!form) return;

  const exampleId = form.dataset.exampleId;
  const nextId = form.dataset.nextId;
  const marker = form.dataset.marker || "|||CUT|||";
  const startMarker = form.dataset.startMarker || "|||START|||";
  const expectedCuts = form.dataset.expectedCuts || "?";
  const statusEl = document.getElementById("save-status");
  const progress = document.getElementById("progress");
  const editor = document.getElementById("editor");
  const cutCount = document.getElementById("cut-count");

  function selectedVerdict() {
    const el = form.querySelector('input[name="verdict"]:checked');
    return el ? el.value : "cuts";
  }

  function countCuts(text) {
    return String(text || "").split(marker).length - 1;
  }

  function updateCutPill() {
    if (!cutCount || !editor) return;
    const n = countCuts(editor.value);
    const verdict = selectedVerdict();
    cutCount.textContent = `${n} cuts (concordance says ${expectedCuts})`;
    // "pending" here means "not yet annotated", not "wrong": a count differing from
    // the concordance is a legitimate, savable verdict.
    const ok = verdict !== "cuts" || n > 0;
    cutCount.className = "status-pill " + (ok ? "done" : "pending");
  }

  function formPayload() {
    return {
      text: editor.value,
      paragraph_notes: document.getElementById("paragraph_notes").value,
      cut_notes: document.getElementById("cut_notes").value,
      uncertain: document.getElementById("uncertain").checked,
      clutter: document.getElementById("clutter").checked,
      verdict: selectedVerdict(),
      labelled: true,
    };
  }

  async function save(andNext) {
    const verdict = selectedVerdict();
    const n = countCuts(editor.value);
    if (verdict === "cuts" && n === 0) {
      statusEl.textContent = `cuts verdict needs at least one ${marker} marker, or choose no_cut / false_lump / skip.`;
      statusEl.className = "save-status err";
      return;
    }
    // A count other than expectedCuts does NOT block the save. expectedCuts is the
    // concordance's n_share prediction, which is the thing under test — the human
    // disagreeing with it is the finding, not a form error. Warn, then save.
    let disagree = false;
    if (verdict === "cuts" && String(n) !== String(expectedCuts)) {
      disagree = true;
    }
    if ((verdict === "no_cut" || verdict === "false_lump") && n > 0) {
      statusEl.textContent = `${verdict} cannot keep CUT markers — remove them or use cuts.`;
      statusEl.className = "save-status err";
      return;
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
      statusEl.textContent = disagree
        ? `Saved to disk — ${n} cuts recorded against the concordance's ${expectedCuts}.`
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

  function insertMarker(text) {
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.value = editor.value.slice(0, start) + text + editor.value.slice(end);
    editor.selectionStart = editor.selectionEnd = start + text.length;
    editor.focus();
    updateCutPill();
  }

  document.getElementById("btn-insert-cut")?.addEventListener("click", () => insertMarker(marker));

  document.getElementById("btn-insert-start")?.addEventListener("click", () => {
    if (editor.value.includes(startMarker)) {
      statusEl.textContent = `${startMarker} is already placed — remove it first.`;
      statusEl.className = "save-status err";
      return;
    }
    insertMarker(startMarker);
  });

  editor?.addEventListener("input", updateCutPill);
  form.querySelectorAll('input[name="verdict"]').forEach((el) => {
    el.addEventListener("change", updateCutPill);
  });
  updateCutPill();
})();
