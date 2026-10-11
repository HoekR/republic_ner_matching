"""Date-blind entity displacement: unpinned SittingDays → main-series sessions → gaps.

**User, 2026-10-09:** there is no `missing_htr` mass except small mistakes — it is displaced
HTR. Bring those sittings into the gaps (however large) so anchors can tackle them. Use the
**saved graph** (`load_graph`), not a parallel concordance path. Secret inventories 4562/4861
stay out (`is_main_series` only). Mid-gap / cohabitant hits are the valuable class (split or
shorten a calendar bracket). Short receipt openings
(``ontfangen een missive/brief … houdende advertentie … geen resolutie``) from the retired
short-resolution track are landmarks inside HTR blocks; phrase lists live in
`align_short_resolutions.py`.

Population: in-scope `SittingDay` nodes with **no** main-series `PINNED_TO` (default), or
``--population no_dated_as`` for heading-miss days. Nihil-actum dates are skipped. Probe:
distinctive person/place surfaces from `enriched_resolutions` +
`enriched_person_name_variants`, searched date-blind into main-series session text from
`paragraph_axis` (paragraph nodes on the graph carry no text). Optional ``--window INV:LO:HI``
restricts candidates to sessions on those scans.

Hit ⇒ provisional ``DISPLACED_IN`` edge (`SittingDay → Session`, `observed=False`) and a gap
bracket record (nearest pinned sessions on that inventory's `NEXT` chain). Miss ⇒ residue.

Does **not** rewrite production `PINNED_TO`. ``--write`` appends ``DISPLACED_IN`` edges onto the
saved graph and persists nodes/edges (same datasets).

Validation cases (from the explanatory-coverage track):
  - ``1626-03-28`` must hit ``session-3185-num-56`` (displaced into a neighbour).
  - ``1628-05-15`` is a known true-absence check when names miss across a window.

Usage:
    uv run python -m sequence_graph.displace --propose
    uv run python -m sequence_graph.displace --propose --write
    uv run python -m sequence_graph.displace --validate
"""

from __future__ import annotations

import argparse
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Any

import networkx as nx

from data_io import load, save_semi_structured
from scripts.corpus_scope import is_main_series, scope_meta
from sequence_graph.build import NEXT
from sequence_graph.correspondence import DATED_AS, OBSERVED_ON, PINNED_TO, Evidence
from sequence_graph.persist import edge_records, load_graph, node_records

DISPLACED_IN = "DISPLACED_IN"
PROPOSALS_DATASET = "displaced_sitting_proposals"
MIN_SURFACE_LEN = 5
MIN_HIT_SCORE = 3.0
MIN_MARGIN = 1.0  # best - second session score
VALIDATION_HIT = ("1626-03-28", "session-3185-num-56")
VALIDATION_ABSENCE = "1628-05-15"


def _nihil_dates() -> set[str]:
    conc = load("resolution_concordance_1626_1630")
    return set(
        conc.loc[conc["status"].astype(str) == "nihil_actum", "enriched_date"]
        .astype(str)
        .str.slice(0, 10)
    )


def _variants() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in load("enriched_person_name_variants"):
        if row.get("record_type") != "person":
            continue
        forms = [
            s["surface"].lower()
            for s in (row.get("surface_forms") or [])
            if s.get("kind") == "name" and len(s.get("surface") or "") >= MIN_SURFACE_LEN
        ]
        out[str(row["person_id"])] = forms
    return out


def _enriched_by_date() -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if date:
            by[date].append(er)
    return by


def day_surfaces(
    date: str,
    enr_by: dict[str, list[dict[str, Any]]],
    variants: dict[str, list[str]],
) -> dict[str, float]:
    """Surface → IDF-ish weight for one enriched day (persons + places)."""
    # Corpus DF approximated by how many dates mention the surface (filled by caller optionally).
    weights: dict[str, float] = {}
    for er in enr_by.get(date, []):
        for pid in (
            list(er.get("persons") or [])
            + list(er.get("president_ids") or [])
            + list(er.get("deputy_ids") or [])
        ):
            for surface in variants.get(str(pid), []):
                weights[surface] = max(weights.get(surface, 0.0), 1.0)
        for place in er.get("places") or []:
            if place and len(str(place)) >= MIN_SURFACE_LEN:
                key = str(place).lower()
                weights[key] = max(weights.get(key, 0.0), 1.5)
    return weights


def apply_idf(day_weights: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Reweight surfaces by log inverse date-frequency across the probe population."""
    df: Counter[str] = Counter()
    for weights in day_weights.values():
        df.update(weights.keys())
    n = max(len(day_weights), 1)
    out: dict[str, dict[str, float]] = {}
    for date, weights in day_weights.items():
        out[date] = {
            s: w * (math.log((n + 1) / (df[s] + 1)) + 1.0) for s, w in weights.items()
        }
    return out


def unpinned_sitting_days(graph: nx.MultiDiGraph, nihil: set[str]) -> list[str]:
    """Dates of SittingDays with no main-series PINNED_TO, excluding nihil."""
    dates: list[str] = []
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "SittingDay":
            continue
        date = data["obj"].date
        if date in nihil:
            continue
        pins = [
            v
            for _u, v, ed in graph.out_edges(node_id, data=True)
            if ed.get("kind") == PINNED_TO
        ]
        if any(is_main_series(graph.nodes[v]["obj"].session_id) for v in pins):
            continue
        dates.append(date)
    return sorted(dates)


def main_session_texts(graph: nx.MultiDiGraph) -> dict[str, str]:
    """session_id → concatenated HTR paragraph text (main series on the graph only)."""
    axis = load("paragraph_axis_1626_1630")
    by_session: dict[str, list[str]] = defaultdict(list)
    for row in axis:
        flat = str(row.get("flat_id") or "")
        session = re.sub(r"-resolution-\d+$", "", flat)
        if not session or not is_main_series(session):
            continue
        if f"session:{session}" not in graph:
            continue
        text = str(row.get("text") or "")
        if text:
            by_session[session].append(text)
    return {sid: "\n".join(parts).lower() for sid, parts in by_session.items()}


def build_surface_index(session_texts: dict[str, str], vocabulary: set[str]) -> dict[str, set[str]]:
    """surface → sessions containing it (substring). Vocabulary-limited for speed."""
    index: dict[str, set[str]] = defaultdict(set)
    # Longer surfaces first reduces accidental short-token noise when building per-day scores
    for surface in sorted(vocabulary, key=len, reverse=True):
        if len(surface) < MIN_SURFACE_LEN:
            continue
        for sid, text in session_texts.items():
            if surface in text:
                index[surface].add(sid)
    return index


def score_sessions(
    weights: dict[str, float],
    index: dict[str, set[str]],
    *,
    allowlist: set[str] | None = None,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for surface, weight in weights.items():
        for sid in index.get(surface, ()):
            if allowlist is not None and sid not in allowlist:
                continue
            scores[sid] += weight
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def sessions_on_scan_window(
    graph: nx.MultiDiGraph, inventory: str, scan_lo: int, scan_hi: int
) -> set[str]:
    """Main-series sessions with OBSERVED_ON inside [scan_lo, scan_hi] on ``inventory``."""
    out: set[str] = set()
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "Session":
            continue
        sess = data["obj"]
        if sess.inventory != inventory or not is_main_series(sess.session_id):
            continue
        for _u, v, ed in graph.out_edges(node_id, data=True):
            if ed.get("kind") != OBSERVED_ON:
                continue
            if graph.nodes[v].get("kind") != "Scan":
                continue
            scan = graph.nodes[v]["obj"]
            if scan.inventory == inventory and scan_lo <= int(scan.scan_num) <= scan_hi:
                out.add(sess.session_id)
                break
    return out


def dates_without_dated_as(graph: nx.MultiDiGraph, nihil: set[str]) -> list[str]:
    """SittingDays that have enriched business potential but no DATED_AS scan anywhere.

    Includes days that already carry a (inferred) PINNED_TO — the heading channel is what
    failed. Nihil skipped.
    """
    dates: list[str] = []
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "SittingDay":
            continue
        date = data["obj"].date
        if date in nihil:
            continue
        has_dated = any(
            ed.get("kind") == DATED_AS for _u, _v, ed in graph.in_edges(node_id, data=True)
        )
        if not has_dated:
            dates.append(date)
    return sorted(dates)


def gap_bracket(
    graph: nx.MultiDiGraph, session_id: str
) -> dict[str, Any]:
    """Nearest main-series sessions with production PINNED_TO on either side (NEXT chain).

    ``placement``:
      * ``interior`` — hit is strictly between two pinned anchors (splits / shortens the gap).
        Most valuable: a mid-gap sitting that was invisible to DATED_AS.
      * ``endpoint`` — hit itself already carries a production PINNED_TO.
      * ``open_end`` — only one side has a pinned neighbour.
      * ``unanchored`` — no pinned neighbour either side.
    """
    node = f"session:{session_id}"
    if node not in graph:
        return {
            "hit_session": session_id,
            "lo_session": None,
            "hi_session": None,
            "placement": "unanchored",
        }

    inventory = graph.nodes[node]["obj"].inventory

    def has_production_pin(session_node: str) -> bool:
        for _u, _v, key, ed in graph.in_edges(session_node, keys=True, data=True):
            if ed.get("kind") == PINNED_TO and key == PINNED_TO:
                return True
        return False

    def walk(start: str, direction: str) -> str | None:
        current = start
        seen: set[str] = set()
        while current not in seen:
            seen.add(current)
            if direction == "prev":
                nbrs = [
                    u
                    for u, _v, ed in graph.in_edges(current, data=True)
                    if ed.get("kind") == NEXT and graph.nodes[u]["obj"].inventory == inventory
                ]
            else:
                nbrs = [
                    v
                    for _u, v, ed in graph.out_edges(current, data=True)
                    if ed.get("kind") == NEXT and graph.nodes[v]["obj"].inventory == inventory
                ]
            if not nbrs:
                return None
            current = nbrs[0]
            if has_production_pin(current):
                return graph.nodes[current]["obj"].session_id
        return None

    lo = walk(node, "prev")
    hi = walk(node, "next")
    itself = has_production_pin(node)
    pin_dates = sorted(
        {
            graph.nodes[u]["obj"].date
            for u, _v, key, ed in graph.in_edges(node, keys=True, data=True)
            if ed.get("kind") == PINNED_TO
            and key == PINNED_TO
            and graph.nodes[u].get("kind") == "SittingDay"
        }
    )
    if itself:
        # Default; propose() may upgrade to ``cohabitant`` when the probe date is
        # not among pin_dates (embedded second calendar day inside a pinned block —
        # the Saturday-in-num-56 class; high value for splitting calendar gaps).
        placement = "endpoint"
    elif lo and hi:
        placement = "interior"
    elif lo or hi:
        placement = "open_end"
    else:
        placement = "unanchored"
    return {
        "hit_session": session_id,
        "inventory": inventory,
        "lo_session": lo,
        "hi_session": hi,
        "hit_itself_pinned": itself,
        "pin_dates": pin_dates,
        "placement": placement,
    }


def propose(
    graph: nx.MultiDiGraph | None = None,
    *,
    population: str = "unpinned",
    session_allowlist: set[str] | None = None,
    window: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Propose DISPLACED_IN hits.

    ``population``:
      * ``unpinned`` — SittingDays with no main-series PINNED_TO (default; date-blind).
      * ``no_dated_as`` — SittingDays with zero DATED_AS anywhere (heading miss / parser gap).
        May already carry an inferred PINNED_TO; those are still probed so a windowed hit
        can split or shorten a sync gap.

    ``session_allowlist``: if set, entity scores only compete inside that session set
    (physical scan window — "somewhere between the neighbouring dated scans").
    """
    graph = graph or load_graph()
    nihil = _nihil_dates()
    if population == "unpinned":
        dates = unpinned_sitting_days(graph, nihil)
    elif population == "no_dated_as":
        dates = dates_without_dated_as(graph, nihil)
    else:
        raise ValueError(population)
    variants = _variants()
    enr_by = _enriched_by_date()

    raw_weights = {d: day_surfaces(d, enr_by, variants) for d in dates}
    day_weights = apply_idf(raw_weights)
    vocabulary = {s for w in day_weights.values() for s in w}
    session_texts = main_session_texts(graph)
    index = build_surface_index(session_texts, vocabulary)

    rows: list[dict[str, Any]] = []
    for date in dates:
        weights = day_weights[date]
        k_e = len(enr_by.get(date, []))
        ranked = score_sessions(weights, index, allowlist=session_allowlist)
        best = ranked[0] if ranked else None
        second = ranked[1] if len(ranked) > 1 else None
        score = best[1] if best else 0.0
        margin = (best[1] - second[1]) if best and second else (best[1] if best else 0.0)
        hit = bool(
            best
            and score >= MIN_HIT_SCORE
            and margin >= MIN_MARGIN
            and len(weights) > 0
        )
        bracket = gap_bracket(graph, best[0]) if hit and best else None
        placement = (bracket or {}).get("placement")
        pin_dates = (bracket or {}).get("pin_dates") or []
        if (
            hit
            and placement == "endpoint"
            and pin_dates
            and date not in pin_dates
        ):
            # Second (or nth) calendar day living inside an already-pinned HTR block.
            placement = "cohabitant"
            if bracket is not None:
                bracket = {**bracket, "placement": placement}
        rows.append({
            "record_type": "proposal",
            "population": population,
            "date": date,
            "k_e": k_e,
            "n_surfaces": len(weights),
            "verdict": "displaced" if hit else ("no_discriminative_surfaces" if not weights else "residue"),
            "hit_session": best[0] if hit and best else None,
            "score": float(score) if hit else float(score),
            "margin": float(margin) if hit else float(margin),
            "runner_up": second[0] if second else None,
            "runner_up_score": float(second[1]) if second else None,
            "bracket": bracket,
            "placement": placement,
            "pin_dates": pin_dates if hit else None,
            # Interior / cohabitant hits split or shorten calendar gaps.
            "gate_eligible": bool(hit and population == "unpinned"),
            "window": window,
            "n_candidate_sessions": len(session_allowlist) if session_allowlist is not None else None,
        })
    return rows


def gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(r["verdict"] for r in rows)
    displaced = [r for r in rows if r["verdict"] == "displaced"]
    placements = Counter(r.get("placement") or "unset" for r in displaced)
    k_e = sum(r["k_e"] for r in displaced)
    high_value = {"interior", "cohabitant"}
    k_e_interior = sum(r["k_e"] for r in displaced if r.get("placement") in high_value)
    # gap charges: group by (lo, hi, inventory)
    gaps: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in displaced:
        b = r["bracket"] or {}
        key = (b.get("inventory"), b.get("lo_session"), b.get("hi_session"))
        slot = gaps.setdefault(
            key,
            {
                "inventory": b.get("inventory"),
                "lo_session": b.get("lo_session"),
                "hi_session": b.get("hi_session"),
                "n_sittings": 0,
                "k_e": 0,
                "n_interior": 0,
                "k_e_interior": 0,
                "hit_sessions": [],
                "dates": [],
            },
        )
        slot["n_sittings"] += 1
        slot["k_e"] += r["k_e"]
        if r.get("placement") in ("interior", "cohabitant"):
            slot["n_interior"] += 1
            slot["k_e_interior"] += r["k_e"]
        slot["hit_sessions"].append(r["hit_session"])
        slot["dates"].append(r["date"])

    val_date, val_session = VALIDATION_HIT
    val_row = next((r for r in rows if r["date"] == val_date), None)
    absence = next((r for r in rows if r["date"] == VALIDATION_ABSENCE), None)
    held_out_ok = bool(
        val_row
        and val_row["verdict"] == "displaced"
        and val_row["hit_session"] == val_session
    )

    return {
        "record_type": "gate",
        "channel": DISPLACED_IN,
        "n_unpinned_non_nihil": len(rows),
        "verdicts": dict(verdicts),
        "n_displaced": len(displaced),
        "k_e_displaced": k_e,
        "placements": dict(placements),
        "n_interior": placements.get("interior", 0),
        "n_cohabitant": placements.get("cohabitant", 0),
        "k_e_interior": k_e_interior,
        "n_gap_brackets": len(gaps),
        "gap_brackets": sorted(
            gaps.values(),
            key=lambda g: (-g.get("k_e_interior", 0), -g["k_e"], g["inventory"] or "", g["lo_session"] or ""),
        ),
        "validation_hit_date": val_date,
        "validation_hit_session": val_session,
        "validation_hit_ok": held_out_ok,
        "validation_hit_row": val_row,
        "validation_absence_date": VALIDATION_ABSENCE,
        "validation_absence_verdict": absence["verdict"] if absence else None,
        "min_hit_score": MIN_HIT_SCORE,
        "min_margin": MIN_MARGIN,
        "review_policy": (
            "DISPLACED_IN is provisional — not production PINNED_TO; "
            "brings sittings into gap brackets for anchor work; 4562/4861 out"
        ),
        **scope_meta(),
    }


def write_displaced_edges(graph: nx.MultiDiGraph, rows: list[dict[str, Any]]) -> int:
    """Append DISPLACED_IN edges for gate-eligible proposals. Returns edge count written."""
    n = 0
    for row in rows:
        if not row.get("gate_eligible") or not row.get("hit_session"):
            continue
        u = f"day:{row['date']}"
        v = f"session:{row['hit_session']}"
        if u not in graph or v not in graph:
            continue
        key = f"{DISPLACED_IN}:{row['hit_session']}"
        graph.add_edge(
            u,
            v,
            key=key,
            kind=DISPLACED_IN,
            evidence=Evidence(
                channel="entity_displace_date_blind",
                source="enriched_person_name_variants+enriched_resolutions+paragraph_axis",
                observed=False,
                confidence=None,
                detail={
                    "score": row["score"],
                    "margin": row["margin"],
                    "k_e": row["k_e"],
                    "bracket": row["bracket"],
                },
            ),
        )
        n += 1
    return n


def save_proposals(
    rows: list[dict[str, Any]], gate: dict[str, Any], *, write_graph: bool = False
) -> dict[str, Any]:
    payload = [gate, *rows]
    save_semi_structured(
        payload,
        logical_name=PROPOSALS_DATASET,
        script=__file__,
        description=(
            "Date-blind entity displacement proposals from the saved sequence_graph: "
            "SittingDays with no main-series PINNED_TO searched into 3185-3189 session text. "
            "First record is gate aggregates + gap_brackets (k_e charged into lo..hi pinned "
            "session brackets). DISPLACED_IN edges optional via --write; never rewrites PINNED_TO. "
            "4562/4861 excluded."
        ),
        parent_sources=[
            "sequence_graph_nodes",
            "sequence_graph_edges",
            "enriched_resolutions_1626_1630",
            "enriched_person_name_variants",
            "paragraph_axis_1626_1630",
        ],
    )
    if write_graph:
        graph = load_graph()
        # drop prior DISPLACED_IN then rewrite
        drop = [
            (u, v, k)
            for u, v, k, d in graph.edges(keys=True, data=True)
            if d.get("kind") == DISPLACED_IN
        ]
        graph.remove_edges_from(drop)
        n = write_displaced_edges(graph, rows)
        save_semi_structured(
            node_records(graph),
            logical_name="sequence_graph_nodes",
            script=__file__,
        )
        save_semi_structured(
            edge_records(graph),
            logical_name="sequence_graph_edges",
            script=__file__,
        )
        gate["edges_written"] = n
    return gate


def validate(graph: nx.MultiDiGraph | None = None) -> bool:
    graph = graph or load_graph()
    rows = propose(graph)
    gate = gate_summary(rows)
    print(
        f"validation hit {VALIDATION_HIT[0]} -> {VALIDATION_HIT[1]}: "
        f"{'PASS' if gate['validation_hit_ok'] else 'FAIL'}"
    )
    if gate.get("validation_hit_row"):
        r = gate["validation_hit_row"]
        print(f"  verdict={r['verdict']} hit={r['hit_session']} score={r['score']:.2f}")
    print(
        f"validation absence {VALIDATION_ABSENCE}: "
        f"verdict={gate['validation_absence_verdict']}"
    )
    return bool(gate["validation_hit_ok"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--propose", action="store_true")
    parser.add_argument("--write", action="store_true", help="persist DISPLACED_IN on saved graph")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--population",
        choices=("unpinned", "no_dated_as"),
        default="unpinned",
        help="unpinned=no main-series PINNED_TO; no_dated_as=heading channel empty (gap split)",
    )
    parser.add_argument(
        "--window",
        metavar="INV:LO:HI",
        default=None,
        help="Restrict candidate sessions to OBSERVED_ON scans in inventory INV, scan LO..HI",
    )
    parser.add_argument(
        "--show-dates",
        nargs="*",
        default=None,
        help="Print these dates' rows even if residue (e.g. 1626-03-28 1626-03-31 1626-04-01)",
    )
    args = parser.parse_args()
    if not (args.propose or args.validate):
        parser.print_help()
        return

    graph = load_graph()
    if args.validate and not args.propose:
        ok = validate(graph)
        raise SystemExit(0 if ok else 1)

    allowlist: set[str] | None = None
    window_meta: dict[str, Any] | None = None
    if args.window:
        inv, lo_s, hi_s = args.window.split(":")
        allowlist = sessions_on_scan_window(graph, inv, int(lo_s), int(hi_s))
        window_meta = {
            "inventory": inv,
            "scan_lo": int(lo_s),
            "scan_hi": int(hi_s),
            "n_sessions": len(allowlist),
            "sessions": sorted(allowlist),
        }
        print(
            f"physical window {inv} scans {lo_s}-{hi_s}: "
            f"{len(allowlist)} candidate sessions"
        )

    rows = propose(
        graph,
        population=args.population,
        session_allowlist=allowlist,
        window=window_meta,
    )
    gate = gate_summary(rows)
    gate["population"] = args.population
    gate["window"] = window_meta
    # Only persist the default unpinned corpus-wide run as the gate dataset;
    # windowed / no_dated_as probes print and optionally write a sidecar name later.
    if args.population == "unpinned" and args.window is None:
        gate = save_proposals(rows, gate, write_graph=args.write)
        print(
            f"saved {PROPOSALS_DATASET}: unpinned={gate['n_unpinned_non_nihil']} "
            f"displaced={gate['n_displaced']} k_e={gate['k_e_displaced']} "
            f"interior={gate['n_interior']} k_e_interior={gate['k_e_interior']} "
            f"gap_brackets={gate['n_gap_brackets']}"
        )
    else:
        print(
            f"probe population={args.population} n={len(rows)} "
            f"displaced={gate['n_displaced']} k_e={gate['k_e_displaced']} "
            f"interior={gate['n_interior']} k_e_interior={gate['k_e_interior']} "
            f"(not written — use default --propose for dataset)"
        )
    print(
        f"  validation_hit_ok={gate['validation_hit_ok']} "
        f"absence={gate['validation_absence_verdict']}"
    )
    print("  verdicts:", gate["verdicts"])
    print("  placements:", gate["placements"])
    if args.write and args.population == "unpinned" and args.window is None:
        print(f"  DISPLACED_IN edges written: {gate.get('edges_written')}")
    high = [r for r in rows if r.get("placement") in ("interior", "cohabitant")]
    if high:
        print(
            f"  high-value hits ({len(high)}: interior mid-NEXT + cohabitant "
            f"second-date-in-pinned-block):"
        )
        for r in sorted(high, key=lambda x: (-x["k_e"], -x["score"]))[:12]:
            b = r.get("bracket") or {}
            print(
                f"    [{r.get('placement')}] {r['date']} → {r['hit_session']} "
                f"(pins={r.get('pin_dates')}; "
                f"{b.get('lo_session')} .. {b.get('hi_session')}) "
                f"score={r['score']:.2f} k_e={r['k_e']}"
            )
    print("  top gap brackets by interior k_e then total k_e:")
    for slot in gate["gap_brackets"][:8]:
        print(
            f"    {slot['inventory']} {slot['lo_session']} .. {slot['hi_session']}: "
            f"{slot['n_sittings']} sittings / {slot['k_e']} k_e "
            f"(interior {slot.get('n_interior', 0)} / {slot.get('k_e_interior', 0)} k_e) "
            f"hits={Counter(slot['hit_sessions']).most_common(3)}"
        )
    show = args.show_dates or (
        ["1626-03-28", "1626-03-31", "1626-04-01"] if args.window or args.population == "no_dated_as" else []
    )
    if show:
        by = {r["date"]: r for r in rows}
        print("  focus dates:")
        for d in show:
            r = by.get(d)
            if not r:
                print(f"    {d}: not in population")
                continue
            print(
                f"    {d}: verdict={r['verdict']} placement={r.get('placement')} "
                f"hit={r['hit_session']} score={r['score']:.2f} margin={r['margin']:.2f} "
                f"runner={r['runner_up']} k_e={r['k_e']} surfaces={r['n_surfaces']}"
            )


if __name__ == "__main__":
    main()
