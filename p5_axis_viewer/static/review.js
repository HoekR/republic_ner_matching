(() => {
  const form = document.getElementById("review-form");
  if (!form) return;

  const status = document.getElementById("save-status");
  const progress = document.getElementById("progress");
  const labelledPill = document.getElementById("labelled-pill");
  const dayBox = document.getElementById("day_notes");
  const date = form.dataset.date;
  const nextId = form.dataset.nextId;
  const rangeFrom = form.dataset.from;
  const rangeTo = form.dataset.to;

  function collectHosts() {
    const hosts = {};
    document.querySelectorAll("textarea.host-notes").forEach((el) => {
      const axisId = el.getAttribute("data-axis-id");
      if (axisId) hosts[axisId] = el.value;
    });
    return hosts;
  }

  function selectedVerdict() {
    const el = form.querySelector('input[name="verdict"]:checked');
    return el ? el.value : "";
  }

  function payload() {
    return {
      day_notes: dayBox ? dayBox.value : "",
      hosts: collectHosts(),
      verdict: selectedVerdict(),
      labelled: true,
      from: rangeFrom,
      to: rangeTo,
    };
  }

  async function save(andNext) {
    const verdict = selectedVerdict();
    if (!verdict) {
      if (status) {
        status.textContent = "Pick a verdict before saving.";
        status.className = "save-status err";
      }
      return;
    }
    if (status) {
      status.textContent = "Saving…";
      status.className = "save-status";
    }
    try {
      const response = await fetch(`/api/review/${encodeURIComponent(date)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) {
        throw new Error((body && body.error) || response.statusText);
      }
      if (progress && body.review_stats) {
        progress.textContent =
          `${body.review_stats.labelled} / ${body.review_stats.total} labelled` +
          (rangeFrom && rangeTo ? ` · ${rangeFrom}→${rangeTo}` : "");
      }
      if (labelledPill) {
        labelledPill.textContent = "Saved";
        labelledPill.className = "status-pill done";
      }
      if (status) {
        status.textContent = "Saved to disk.";
        status.className = "save-status ok";
      }
      if (andNext) {
        const target = body.next_unlabelled || nextId;
        if (target) {
          const q = new URLSearchParams({ from: rangeFrom, to: rangeTo });
          window.location.href = `/review/${encodeURIComponent(target)}?${q}`;
        } else if (status) {
          status.textContent = "Saved — sample complete.";
        }
      }
    } catch (err) {
      if (status) {
        status.textContent = `Error: ${err.message || err}`;
        status.className = "save-status err";
      }
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    save(true);
  });
  const stay = document.getElementById("btn-save-stay");
  if (stay) stay.addEventListener("click", () => save(false));
})();
