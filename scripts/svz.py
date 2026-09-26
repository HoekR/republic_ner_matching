#!/usr/bin/env python3
"""Manage the lightweight project state dashboard (SvZ).

The machine source of truth is docs/state.json. docs/STATE.md is rendered from
that file so AI agents and humans can read a compact, visual dashboard.

`review` supports the continue/switch/stop discipline in docs/ITERATION_POLICY.md:
it classifies each track's latest recorded metric delta (improving / stagnant /
regressing) so a session can start by asking "which track has the clearest next
gain" instead of resuming whatever was last open.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_JSON = Path("docs/state.json")
STATE_MD = Path("docs/STATE.md")
DECISIONS_MD = Path("docs/DECISIONS.md")
MANUAL_MARKER = "<!-- Manual notes below this line are preserved by scripts/svz.py render. -->"
VALID_STATUSES = {"todo", "inprogress", "done", "blocked"}
DEFAULT_TREND_THRESHOLD = 0.03


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_state() -> dict[str, Any]:
    if not STATE_JSON.exists():
        raise SystemExit(f"Missing {STATE_JSON}. Run from the project root or create state.json first.")
    return json.loads(STATE_JSON.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    state["last_updated"] = now_stamp()
    STATE_JSON.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def task_symbol(status: str) -> str:
    return {"done": "x", "inprogress": "/", "blocked": "!"}.get(status, " ")


def mermaid_class(status: str) -> str:
    return status if status in VALID_STATUSES else "todo"


def mermaid_id(task_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "_", task_id)
    return clean if clean and clean[0].isalpha() else f"T_{clean}"


def find_task(state: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for task in state.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def parse_number(value: Any) -> float | None:
    """Best-effort numeric read of a metric value: '0.576', '70.7%', '9/21'."""
    text = str(value).strip()
    if not text:
        return None
    fraction = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)", text)
    if fraction:
        numerator, denominator = (float(part) for part in fraction.groups())
        return numerator / denominator if denominator else None
    is_percent = text.endswith("%")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group())
    return number / 100 if is_percent else number


def classify_trend(history: list[dict[str, Any]], threshold: float) -> tuple[str, float | None]:
    """Compare the two most recent numeric history points.

    Returns (verdict, delta) where verdict is one of:
    "improving", "stagnant", "regressing", "insufficient-history".
    Direction is read literally (higher = improving) — invert the metric's own
    value at recording time (e.g. record 1 - other_bucket_pct) if lower is better.
    """
    numeric_points = [point.get("value") for point in history]
    numeric_points = [parse_number(value) for value in numeric_points]
    numeric_points = [value for value in numeric_points if value is not None]
    if len(numeric_points) < 2:
        return "insufficient-history", None
    previous, latest = numeric_points[-2], numeric_points[-1]
    delta = latest - previous
    relative = delta / abs(previous) if previous else (None if delta == 0 else delta)
    if relative is None:
        verdict = "stagnant"
    elif relative > threshold:
        verdict = "improving"
    elif relative < -threshold:
        verdict = "regressing"
    else:
        verdict = "stagnant"
    return verdict, delta


def preserved_notes() -> str:
    if not STATE_MD.exists():
        return "## Notes\n\n"
    content = STATE_MD.read_text(encoding="utf-8")
    if MANUAL_MARKER not in content:
        return "## Notes\n\n"
    return content.split(MANUAL_MARKER, 1)[1].lstrip()


def render_markdown(state: dict[str, Any]) -> str:
    tasks = state.get("tasks", [])
    metrics = state.get("metrics", [])
    blockers = state.get("blockers", [])
    dependencies = state.get("dependencies", [])
    next_actions = state.get("next_actions", [])
    last_updated = state.get("last_updated") or "not set"

    lines: list[str] = [
        "# Current Project State (SvZ)",
        "",
        f"Last updated: {last_updated}",
        "",
        "```mermaid",
        "flowchart TD",
        "    classDef done fill:#2e7d32,stroke:#1b5e20,color:#fff,stroke-width:2px;",
        "    classDef inprogress fill:#f57c00,stroke:#e65100,color:#fff,stroke-width:2px;",
        "    classDef todo fill:#424242,stroke:#212121,color:#ddd,stroke-width:1px,stroke-dasharray: 5 5;",
        "    classDef blocked fill:#c62828,stroke:#b71c1c,color:#fff,stroke-width:2px;",
        "",
    ]
    for task in tasks:
        node_id = mermaid_id(str(task.get("id", "task")))
        label = f"{task.get('id', '')}: {task.get('title', '')}".replace('"', "'")
        lines.append(f"    {node_id}[\"{label}\"] :::{mermaid_class(str(task.get('status', 'todo')))}")
    if dependencies:
        for dependency in dependencies:
            source = mermaid_id(str(dependency.get("from", "")))
            target = mermaid_id(str(dependency.get("to", "")))
            if source and target:
                lines.append(f"    {source} --> {target}")
    else:
        for first, second in zip(tasks, tasks[1:]):
            lines.append(f"    {mermaid_id(str(first.get('id', '')))} --> {mermaid_id(str(second.get('id', '')))}")
    lines.extend(["```", "", "## Overall Progress", ""])

    if tasks:
        for task in tasks:
            status = str(task.get("status", "todo"))
            task_line = f"- [{task_symbol(status)}] {task.get('id')}: {task.get('title')}"
            if task.get("notes"):
                task_line += f" — {task['notes']}"
            lines.append(task_line)
    else:
        lines.append("No tasks recorded yet.")

    lines.extend(["", "## Active Focus", "", str(state.get("active_focus") or "No active focus recorded."), ""])
    lines.extend(["## Key Intermediate Results & Metrics", ""])
    if metrics:
        for metric_entry in metrics:
            value = metric_entry.get("value", "")
            label = metric_entry.get("label") or metric_entry.get("name") or "metric"
            scope = metric_entry.get("scope")
            prefix = f"{scope} — " if scope else ""
            verdict, delta = classify_trend(metric_entry.get("history", []), DEFAULT_TREND_THRESHOLD)
            trend = f" ({verdict}, Δ{delta:+.3f})" if delta is not None else ""
            lines.append(f"- **{prefix}{label}:** {value}{trend}")
    else:
        lines.append("No metrics recorded yet.")

    lines.extend(["", "## Blockers / Open Questions", ""])
    if blockers:
        lines.extend(f"- [ ] {item}" for item in blockers)
    else:
        lines.append("No blockers recorded.")

    lines.extend(["", "## Next Actions", ""])
    if next_actions:
        lines.extend(f"- {item}" for item in next_actions)
    else:
        lines.append("No next actions recorded.")

    lines.extend(["", MANUAL_MARKER, preserved_notes().rstrip(), ""])
    return "\n".join(lines)


def render(_: argparse.Namespace) -> None:
    state = load_state()
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print(f"Rendered {STATE_MD} from {STATE_JSON}")


def status(_: argparse.Namespace) -> None:
    state = load_state()
    print(f"Project: {state.get('project', 'unknown')}")
    print(f"Last updated: {state.get('last_updated') or 'not set'}")
    print(f"Active focus: {state.get('active_focus') or 'none'}")
    print("\nTasks:")
    for task in state.get("tasks", []):
        print(f"  [{task_symbol(str(task.get('status', 'todo')))}] {task.get('id')}: {task.get('title')}")
    if state.get("metrics"):
        print("\nMetrics:")
        for metric_entry in state["metrics"]:
            scope = f"{metric_entry.get('scope')}: " if metric_entry.get("scope") else ""
            print(f"  - {scope}{metric_entry.get('label') or metric_entry.get('name')}: {metric_entry.get('value')}")


def update(args: argparse.Namespace) -> None:
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    state = load_state()
    task = find_task(state, args.task_id)
    if task is None:
        task = {"id": args.task_id, "title": args.title or args.task_id, "status": args.status, "notes": ""}
        state.setdefault("tasks", []).append(task)
    else:
        task["status"] = args.status
        if args.title:
            task["title"] = args.title
    if args.notes is not None:
        task["notes"] = args.notes
    if args.next_action is not None:
        task["next_action"] = args.next_action
    if args.goal is not None:
        task["goal"] = args.goal
    if args.cost is not None:
        if args.cost not in VALID_COSTS:
            raise SystemExit(f"--cost must be one of: {', '.join(sorted(VALID_COSTS))}")
        task["cost"] = args.cost
    if args.blocks is not None:
        task["blocks"] = args.blocks
    save_state(state)
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print(f"Set {args.task_id} to {args.status}")


def focus(args: argparse.Namespace) -> None:
    state = load_state()
    state["active_focus"] = args.text
    save_state(state)
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print("Updated active focus")


def metric(args: argparse.Namespace) -> None:
    state = load_state()
    today = today_date()
    metrics = state.setdefault("metrics", [])
    for existing in metrics:
        if existing.get("scope") == args.scope and existing.get("name") == args.name:
            history = existing.setdefault("history", [])
            if history and history[-1].get("date") == today:
                history[-1]["value"] = args.value
            else:
                history.append({"date": today, "value": args.value})
            existing["value"] = args.value
            if args.label:
                existing["label"] = args.label
            break
    else:
        metrics.append(
            {
                "scope": args.scope,
                "name": args.name,
                "label": args.label or args.name,
                "value": args.value,
                "history": [{"date": today, "value": args.value}],
            }
        )
    save_state(state)
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print(f"Recorded metric {args.name}={args.value}")


def decision(args: argparse.Namespace) -> None:
    DECISIONS_MD.parent.mkdir(parents=True, exist_ok=True)
    if not DECISIONS_MD.exists():
        DECISIONS_MD.write_text("# Decision Log\n\n", encoding="utf-8")
    entry = (
        f"\n## {datetime.now().strftime('%Y-%m-%d')}: {args.title}\n\n"
        f"- **Context:** {args.context}\n"
        f"- **Decision:** {args.decision}\n"
        f"- **Reason:** {args.reason}\n"
    )
    with DECISIONS_MD.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    print(f"Appended decision to {DECISIONS_MD}")


def query(args: argparse.Namespace) -> None:
    state = load_state()
    haystack = json.dumps(state, ensure_ascii=False, indent=2).lower()
    if args.term.lower() not in haystack:
        print(f"No matches for {args.term!r}")
        return
    print(json.dumps(state, ensure_ascii=False, indent=2))


COST_BONUS = {"cheap": 5, "session": 2, "multi-session": 0}
VALID_COSTS = set(COST_BONUS)


def task_next_action(task: dict[str, Any]) -> str | None:
    """Explicit `next_action` field, else a "Next action: ..." sentence in the notes."""
    explicit = str(task.get("next_action") or "").strip()
    if explicit:
        return explicit
    match = re.search(r"Next action:\s*(.+?)(?:\.\s|\.$|$)", str(task.get("notes") or ""), re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def metric_health(metrics: list[dict[str, Any]], threshold: float) -> str:
    """One word for what this track's metrics collectively say."""
    if not metrics:
        return "no-metric"
    verdicts = {classify_trend(entry.get("history", []), threshold)[0] for entry in metrics}
    if "improving" in verdicts:
        return "improving"
    if "regressing" in verdicts:
        return "regressing"
    if verdicts == {"insufficient-history"}:
        return "unjudgeable"
    return "all-stagnant"


def score_task(task: dict[str, Any], health: str) -> int:
    """Rank candidates by leverage first, then cheapness — never by momentum."""
    score = 10 * len(task.get("blocks") or [])
    score += COST_BONUS.get(str(task.get("cost") or ""), 1)
    if task_next_action(task):
        score += 1
    if health == "no-metric":
        score += 2  # unmeasurable work is a defect worth surfacing, per ITERATION_POLICY.md
    return score


def propose(state: dict[str, Any], by_scope: dict[str, list[dict[str, Any]]], threshold: float) -> None:
    """Recommend one next step with a reason and a goal, per docs/APPROACH_OVERVIEW.md section 4.

    Reporting status alone leaves the prioritising to whoever is already deepest in a
    branch, which is how momentum beats leverage. This section makes the call explicit
    so it can be argued with.
    """
    tasks = state.get("tasks", [])
    by_id = {str(task.get("id")): task for task in tasks}
    health_by_id = {
        str(task.get("id")): metric_health(by_scope.get(str(task.get("id")), []), threshold) for task in tasks
    }

    active = [task for task in tasks if task.get("status") == "inprogress"]
    candidates = [task for task in tasks if task.get("status") in {"todo", "inprogress"}]
    if not candidates:
        return

    ranked = sorted(candidates, key=lambda task: score_task(task, health_by_id[str(task.get("id"))]), reverse=True)
    best = ranked[0]
    best_id = str(best.get("id"))

    print("\n== Proposed next step ==")
    print(f"Recommended: {best_id} — {best.get('title')}")

    reasons = []
    blocks = [block for block in (best.get("blocks") or []) if block in by_id]
    if blocks:
        open_blocks = [block for block in blocks if by_id[block].get("status") in {"todo", "inprogress"}]
        closed_blocks = [block for block in blocks if block not in open_blocks]
        if open_blocks:
            reasons.append(f"upstream of {len(open_blocks)} open track(s): {', '.join(open_blocks)}")
        if closed_blocks:
            # A failure here reopens conclusions already accepted as final — the sharpest reason of all.
            reasons.append(f"if it fails, {len(closed_blocks)} closed track(s) become suspect: {', '.join(closed_blocks)}")
    if best.get("cost"):
        reasons.append(f"cost {best.get('cost')}")
    if health_by_id[best_id] == "no-metric":
        reasons.append("no metric recorded, so it cannot currently be judged")
    elif health_by_id[best_id] == "all-stagnant":
        reasons.append("metrics stagnant — a decision is due, not more tuning")
    print(f"  Why: {'; '.join(reasons) if reasons else 'highest-ranked remaining track'}")
    if best.get("goal"):
        print(f"  Goal: {best.get('goal')}")
    else:
        print("  Goal: (none recorded — set one with `svz.py update ... --goal`)")
    action = task_next_action(best)
    if action:
        print(f"  Do: {action}")

    if active:
        print("\nIn progress right now — finish or terminate, then return here rather than descending further:")
        for task in active:
            task_id = str(task.get("id"))
            health = health_by_id[task_id]
            if health == "improving":
                verdict = "continuing is defensible (a metric is still improving)"
            elif health == "no-metric":
                verdict = "cannot be judged — record a metric or close it"
            else:
                verdict = "surface to strategy: record a decision (`svz.py decision ...`) or switch"
            marker = "" if task_id == best_id else "  <- not the recommended next step"
            print(f"  - {task_id}: {health} → {verdict}{marker}")

    runners = [task for task in ranked[1:3]]
    if runners:
        print("\nRunner-up:")
        for task in runners:
            print(f"  - {task.get('id')} — {task.get('title')}")

    print("\nThis is a recommendation, not a queue: re-run `review` after any track finishes")
    print("so the next call is recomputed from the new state, not resumed from the old plan.")


def review(args: argparse.Namespace) -> None:
    state = load_state()
    threshold = args.threshold
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for metric_entry in state.get("metrics", []):
        by_scope.setdefault(metric_entry.get("scope"), []).append(metric_entry)

    active, pending, closed = [], [], []
    for task in state.get("tasks", []):
        bucket = {"inprogress": active, "todo": pending}.get(str(task.get("status", "todo")), closed)
        bucket.append(task)

    print("== Active tracks needing a decision ==")
    if not active:
        print("  (none marked inprogress)")
    for task in active:
        print(f"- {task.get('id')}: {task.get('title')}")
        task_metrics = by_scope.get(task.get("id"), [])
        if not task_metrics:
            print("    no metric recorded — run `svz.py metric ...` before judging this track")
            continue
        for metric_entry in task_metrics:
            verdict, delta = classify_trend(metric_entry.get("history", []), threshold)
            delta_str = f"{delta:+.3f}" if delta is not None else "n/a"
            flag = "  <- cutoff candidate" if verdict == "stagnant" else ""
            print(f"    {metric_entry.get('label')}: {metric_entry.get('value')} (Δ {delta_str}, {verdict}){flag}")

    print("\n== Not started ==")
    if not pending:
        print("  (none)")
    for task in pending:
        note = f" — {task['notes']}" if task.get("notes") else ""
        print(f"- {task.get('id')}: {task.get('title')}{note}")

    print("\n== Closed (done / blocked) ==")
    if not closed:
        print("  (none)")
    for task in closed:
        note = f" — {task['notes']}" if task.get("notes") else ""
        print(f"- [{task.get('status')}] {task.get('id')}: {task.get('title')}{note}")

    propose(state, by_scope, threshold)

    print("\nSee docs/ITERATION_POLICY.md before switching tracks or recording a cutoff (`svz.py decision ...`).")


DOC_STATUSES = {"active", "future", "sidelined", "retired"}
DOC_STATUS_RE = re.compile(r"<!--\s*doc-status:\s*(active|future|sidelined|retired)\s*-->", re.IGNORECASE)
CANONICAL_GOAL_MARKER = "<!-- canonical-goal -->"
GOAL_TRIGGER_RE = re.compile(
    r"project goal|goal of this project|the goal is to|^\s*>?\s*\*{0,2}goal:\*{0,2}",
    re.IGNORECASE | re.MULTILINE,
)
# Deliberately broad and therefore imprecise: neither actual historical conflict this check was
# built to catch (PLAN.md's NER header, APPROACH_OVERVIEW.md's "Goal: map...") used consistent
# "goal" phrasing, so a trigger narrow enough to avoid ever matching a scoped local "Goal: fix X"
# label (common step-doc convention, e.g. docs/CANDIDATE_SCORING_AND_CONCORDANCE.md's per-step
# goals) would also miss real project-level restatements. Rather than silently narrowing the
# regex until it stops finding real problems, false positives are resolved explicitly per
# document with LOCAL_GOAL_EXEMPT_MARKER -- an auditable choice, not a quieter heuristic.
LOCAL_GOAL_EXEMPT_MARKER = "<!-- local-goal-ok -->"
# Auto-rendered by `render()`; a manual doc-status marker would be meaningless (and at risk of
# being clobbered) on a file nothing hand-edits.
CONFORMANCE_EXCLUDED_DOCS = {"docs/STATE.md"}


def parse_doc_status(text: str) -> str | None:
    match = DOC_STATUS_RE.search(text)
    return match.group(1).lower() if match else None


def has_canonical_goal_marker(text: str) -> bool:
    return CANONICAL_GOAL_MARKER in text


def contains_goal_assertion(text: str) -> bool:
    if LOCAL_GOAL_EXEMPT_MARKER in text:
        return False
    return bool(GOAL_TRIGGER_RE.search(text))


def split_plan_sections(text: str) -> list[tuple[str, str]]:
    """Split PLAN.md into (heading, section_text_including_heading) at each `## ` heading.

    Any text before the first `## ` heading (the file's own header/title) is returned as its
    own ("<preamble>", ...) entry so it is still checked.
    """
    lines = text.splitlines(keepends=True)
    sections: list[tuple[str, str]] = []
    current_heading = "<preamble>"
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections.append((current_heading, "".join(current_lines)))
            current_heading = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    sections.append((current_heading, "".join(current_lines)))
    return [(heading, body) for heading, body in sections if body.strip()]


def check_document(name: str, text: str) -> list[str]:
    """Conformance problems for one doc or doc-section: (1) no doc-status marker, (2) asserts a
    project goal while not both non-active and outside the canonical location."""
    problems: list[str] = []
    status = parse_doc_status(text)
    if status is None:
        problems.append(f"{name}: no doc-status marker (expected <!-- doc-status: {{{'|'.join(sorted(DOC_STATUSES))}}} -->)")
    if has_canonical_goal_marker(text):
        return problems
    if contains_goal_assertion(text) and status in (None, "active"):
        problems.append(f"{name}: asserts a project goal outside the canonical location while active")
    return problems


def doc_conformance_problems(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(".")
    problems: list[str] = []
    canonical_hits = 0

    candidates = [root / "README.md", root / "PLAN.md", *sorted((root / "docs").rglob("*.md"))]
    for path in candidates:
        if not path.exists():
            continue
        rel = str(path.relative_to(root)) if repo_root else str(path)
        if rel in CONFORMANCE_EXCLUDED_DOCS:
            continue
        text = path.read_text(encoding="utf-8")
        if rel == "PLAN.md":
            for heading, body in split_plan_sections(text):
                if has_canonical_goal_marker(body):
                    canonical_hits += 1
                problems.extend(check_document(f"PLAN.md § {heading}", body))
        else:
            if has_canonical_goal_marker(text):
                canonical_hits += 1
            problems.extend(check_document(rel, text))

    if canonical_hits != 1:
        problems.append(
            f"expected exactly one canonical goal marker ({CANONICAL_GOAL_MARKER}) across all docs, found {canonical_hits}"
        )
    return problems


def doctor(_: argparse.Namespace) -> None:
    state = load_state()
    problems: list[str] = []
    task_ids = [task.get("id") for task in state.get("tasks", [])]
    if len(task_ids) != len(set(task_ids)):
        problems.append("Duplicate task ids in docs/state.json")
    task_id_set = {str(task_id) for task_id in task_ids}
    for task in state.get("tasks", []):
        if task.get("status") not in VALID_STATUSES:
            problems.append(f"Invalid status for {task.get('id')}: {task.get('status')}")
        if task.get("cost") and task.get("cost") not in VALID_COSTS:
            problems.append(f"Invalid cost for {task.get('id')}: {task.get('cost')}")
        for block in task.get("blocks") or []:
            if str(block) not in task_id_set:
                problems.append(f"{task.get('id')} blocks unknown task id {block!r}")
    for metric_entry in state.get("metrics", []):
        scope = str(metric_entry.get("scope"))
        # Scopes may be a task id itself, or a finer-grained sub-id under it (e.g. "S1-D1c" under "S1").
        if scope not in task_id_set and not any(scope.startswith(f"{task_id}-") for task_id in task_id_set):
            problems.append(
                f"Metric {metric_entry.get('name')!r} has scope {metric_entry.get('scope')!r} "
                "that does not match any task id (or <task_id>-<subid> pattern)"
            )
    problems.extend(doc_conformance_problems())
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print("SvZ state looks valid")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage docs/state.json and render docs/STATE.md.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Print a compact state summary").set_defaults(func=status)
    subparsers.add_parser("render", help="Render docs/STATE.md from docs/state.json").set_defaults(func=render)
    subparsers.add_parser("doctor", help="Validate docs/state.json").set_defaults(func=doctor)

    update_parser = subparsers.add_parser("update", help="Set or create a task status")
    update_parser.add_argument("task_id")
    update_parser.add_argument("status", choices=sorted(VALID_STATUSES))
    update_parser.add_argument("--title")
    update_parser.add_argument("--notes")
    update_parser.add_argument("--next-action", dest="next_action", help="Concrete next step, surfaced by `review`")
    update_parser.add_argument("--goal", help="What would count as success for this track")
    update_parser.add_argument("--cost", choices=sorted(VALID_COSTS), help="Rough effort; cheap work outranks costly work")
    update_parser.add_argument("--blocks", nargs="*", help="Task ids this one is upstream of (drives leverage ranking)")
    update_parser.set_defaults(func=update)

    focus_parser = subparsers.add_parser("focus", help="Set the active focus text")
    focus_parser.add_argument("text")
    focus_parser.set_defaults(func=focus)

    metric_parser = subparsers.add_parser("metric", help="Record or update a metric (appends to its history)")
    metric_parser.add_argument("scope", help="Task id this metric belongs to")
    metric_parser.add_argument("name")
    metric_parser.add_argument("value")
    metric_parser.add_argument("--label")
    metric_parser.set_defaults(func=metric)

    decision_parser = subparsers.add_parser("decision", help="Append a decision log entry")
    decision_parser.add_argument("title")
    decision_parser.add_argument("--context", required=True)
    decision_parser.add_argument("--decision", required=True)
    decision_parser.add_argument("--reason", required=True)
    decision_parser.set_defaults(func=decision)

    query_parser = subparsers.add_parser("query", help="Print state JSON if a term appears in it")
    query_parser.add_argument("term")
    query_parser.set_defaults(func=query)

    review_parser = subparsers.add_parser(
        "review", help="Classify each track's latest metric trend to support a continue/switch/stop call"
    )
    review_parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_TREND_THRESHOLD,
        help=f"Relative delta magnitude below which a metric counts as stagnant (default {DEFAULT_TREND_THRESHOLD})",
    )
    review_parser.set_defaults(func=review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["status"])
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
