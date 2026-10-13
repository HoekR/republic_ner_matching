(() => {
  const form = document.getElementById("day-notes-form");
  if (!form) return;

  const status = document.getElementById("notes-status");
  const dayBox = document.getElementById("day_notes");

  function collectHosts() {
    const hosts = {};
    document.querySelectorAll("textarea.host-notes").forEach((el) => {
      const axisId = el.getAttribute("data-axis-id");
      if (axisId) hosts[axisId] = el.value;
    });
    return hosts;
  }

  async function saveNotes(event) {
    if (event) event.preventDefault();
    const date = form.getAttribute("data-date");
    if (!date) return;
    if (status) status.textContent = "Saving…";
    try {
      const response = await fetch(`/api/notes/${encodeURIComponent(date)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          day_notes: dayBox ? dayBox.value : "",
          hosts: collectHosts(),
        }),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) {
        throw new Error((body && body.error) || response.statusText);
      }
      if (status) status.textContent = `Saved ${body.updated_at || ""}`;
    } catch (err) {
      if (status) status.textContent = `Save failed: ${err.message || err}`;
    }
  }

  form.addEventListener("submit", saveNotes);
})();
