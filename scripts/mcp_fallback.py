#!/usr/bin/env python3
"""Lightweight file-based fallback for workflow-mcp calls.

Usage examples:
  python scripts/mcp_fallback.py list_steps
  python scripts/mcp_fallback.py get_plan_status
  python scripts/mcp_fallback.py get_current_step
  python scripts/mcp_fallback.py get_step_guide 3a
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import textwrap

REPO = Path.cwd()
STEPS_DIR = REPO / "docs" / "steps"
STATE_FILES = [REPO / "STATE.md", REPO / "docs" / "STATE.md"]


def read_state() -> dict:
    out = {}
    for f in STATE_FILES:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("current_step:"):
                out["current_step"] = line.split(":", 1)[1].strip()
            if line.startswith("mcp_enabled:"):
                out["mcp_enabled"] = line.split(":", 1)[1].strip().lower() in ("true", "1", "yes")
    return out


def list_steps() -> list[Path]:
    if not STEPS_DIR.exists():
        return []
    return sorted(STEPS_DIR.glob("STEP*.md"), key=lambda p: p.name)


def step_title(path: Path) -> str:
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("#"):
                return ln.lstrip("# ").strip()
        return path.stem
    except Exception:
        return path.name


def cmd_list_steps(args):
    steps = list_steps()
    if not steps:
        print("No step files found in docs/steps/")
        return 1
    for p in steps:
        print(f"{p.name}\t- {step_title(p)}")
    return 0


def cmd_get_step_guide(args):
    step_id = args.step_id
    matches = [p for p in list_steps() if p.name.startswith(f"STEP{step_id}")]
    if not matches:
        # try matching by id anywhere in name
        matches = [p for p in list_steps() if f"STEP{step_id}" in p.name]
    if not matches:
        print(f"Step STEP{step_id} not found", file=sys.stderr)
        return 2
    content = matches[0].read_text(encoding="utf-8")
    print(content)
    return 0


def cmd_get_plan_status(args):
    state = read_state()
    steps = list_steps()
    print("Plan status (file-based fallback):")
    print(f"- state file current_step: {state.get('current_step', '(none)')}")
    print(f"- mcp_enabled: {state.get('mcp_enabled', False)}")
    print("- discovered steps:")
    for p in steps:
        print(f"  - {p.name}: {step_title(p)}")
    return 0


def cmd_get_current_step(args):
    state = read_state()
    cur = state.get("current_step")
    if cur:
        # try to find corresponding step file
        matches = [p for p in list_steps() if p.name.startswith(f"STEP{cur}")]
        if matches:
            p = matches[0]
            print(f"current_step: {cur}\n---\n{step_title(p)}\n\n{p.read_text(encoding='utf-8')}")
            return 0
        else:
            print(f"current_step: {cur} (step file not found)")
            return 1
    # fallback: choose first step
    steps = list_steps()
    if not steps:
        print("No steps found", file=sys.stderr)
        return 2
    p = steps[0]
    print(f"current_step: {p.name}\n---\n{step_title(p)}\n\n{p.read_text(encoding='utf-8')}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list_steps")
    sub.add_parser("get_plan_status")
    sub.add_parser("get_current_step")
    g = sub.add_parser("get_step_guide")
    g.add_argument("step_id", help="e.g. 3a or 4")
    args = parser.parse_args()
    if args.cmd == "list_steps":
        raise SystemExit(cmd_list_steps(args))
    if args.cmd == "get_plan_status":
        raise SystemExit(cmd_get_plan_status(args))
    if args.cmd == "get_current_step":
        raise SystemExit(cmd_get_current_step(args))
    if args.cmd == "get_step_guide":
        raise SystemExit(cmd_get_step_guide(args))
    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()