#!/usr/bin/env python3
"""Manage the lightweight project state dashboard (SvZ).

The machine source of truth is docs/state.json. docs/STATE.md is rendered from
that file so AI agents and humans can read a compact, visual dashboard.
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


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


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
        for metric in metrics:
            value = metric.get("value", "")
            label = metric.get("label") or metric.get("name") or "metric"
            scope = metric.get("scope")
            prefix = f"{scope} — " if scope else ""
            lines.append(f"- **{prefix}{label}:** {value}")
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
        for metric in state["metrics"]:
            scope = f"{metric.get('scope')}: " if metric.get("scope") else ""
            print(f"  - {scope}{metric.get('label') or metric.get('name')}: {metric.get('value')}")


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
    entry = {"scope": args.scope, "name": args.name, "label": args.label or args.name, "value": args.value}
    metrics = state.setdefault("metrics", [])
    for index, existing in enumerate(metrics):
        if existing.get("scope") == args.scope and existing.get("name") == args.name:
            metrics[index] = entry
            break
    else:
        metrics.append(entry)
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


def doctor(_: argparse.Namespace) -> None:
    state = load_state()
    problems: list[str] = []
    task_ids = [task.get("id") for task in state.get("tasks", [])]
    if len(task_ids) != len(set(task_ids)):
        problems.append("Duplicate task ids in docs/state.json")
    for task in state.get("tasks", []):
        if task.get("status") not in VALID_STATUSES:
            problems.append(f"Invalid status for {task.get('id')}: {task.get('status')}")
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
    update_parser.set_defaults(func=update)

    focus_parser = subparsers.add_parser("focus", help="Set the active focus text")
    focus_parser.add_argument("text")
    focus_parser.set_defaults(func=focus)

    metric_parser = subparsers.add_parser("metric", help="Record or update a metric")
    metric_parser.add_argument("scope")
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