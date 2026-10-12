(() => {
  const form = document.getElementById("label-form");
  if (!form) return;
  const reviewId = form.dataset.reviewId;
  const status = document.getElementById("save-status");
  const progress = document.getElementById("progress");
  const other = document.getElementById("other-session");
  const note = document.getElementById("note");

  async function save(choice) {
    status.textContent = "Saving…";
    status.className = "save-status";
    const body = {
      choice,
      other_session: other.value.trim(),
      note: note.value,
    };
    try {
      const res = await fetch(`/api/save/${encodeURIComponent(reviewId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        status.textContent = data.error || "Save failed";
        status.className = "save-status err";
        return;
      }
      if (choice === "not_found") {
        status.textContent = "Saved → not_found";
      } else if (data.correct_session) {
        status.textContent = `Saved → ${data.correct_session}`;
      } else {
        status.textContent = "Cleared";
      }
      status.className = "save-status ok";
      if (progress && data.stats) {
        progress.textContent = `${data.stats.labelled} / ${data.stats.total} labelled`;
      }
      if (choice !== "clear" && data.next_id) {
        window.location.href = `/label/${encodeURIComponent(data.next_id)}`;
      } else if (choice !== "clear") {
        window.location.reload();
      }
    } catch (err) {
      status.textContent = String(err);
      status.className = "save-status err";
    }
  }

  form.querySelectorAll("[data-choice]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const choice = btn.getAttribute("data-choice");
      if (choice === "other" && !other.value.trim()) {
        status.textContent = "Enter other session id first";
        status.className = "save-status err";
        other.focus();
        return;
      }
      save(choice);
    });
  });
})();
