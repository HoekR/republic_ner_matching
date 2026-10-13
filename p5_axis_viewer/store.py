"""Load P5 ledger days and join parent / successor paragraph text for display."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pandas as pd

# Console script entry points do not put the repo root on sys.path.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data_io import load
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.corpus_scope import in_scope, is_main_series
from scripts.s4_corpus_paragraph_predictions import axis_for_date

LEDGER = "s6c_p5_axis_successor_ledger"
PARENT_AXIS = "paragraph_axis_1626_1630"
SUCCESSOR_AXIS = "paragraph_axis_p5_predicted_v1"
CONCORDANCE = "resolution_concordance_1626_1630"

FilterMode = Literal["accepted", "rejected", "all", "suspect", "corpus"]

# Content gate: modern summary lexical hits inside early-modern HTR parent.
# Suspect when an accepted host's summaries barely appear in the parent paragraph
# (false-accept pathology — separated can rise while bindings are wrong).
CONTENT_MIN_TOKEN_LEN = 5
CONTENT_SUSPECT_MAX_HIT_RATE = 0.12
CONTENT_SUSPECT_MIN_HITS = 2
CONTENT_MIN_SUMMARY_TOKENS = 3
# Same-day content verdict (complement to hard_pin monotone — not a replacement).
# A run of k consecutive placed resolutions that match / fail decides the day.
CONTENT_RUN_K = 3
SESSION_DATE_STATUS = "session_date_status_1626_1630"

_STOP = frozenset(
    {
        "aan", "achter", "af", "al", "alle", "alles", "als", "ander", "andere",
        "daar", "dan", "dat", "de", "den", "der", "des", "deze", "die", "dit",
        "door", "een", "en", "er", "gaan", "geen", "haar", "had", "hebben",
        "heden", "hem", "het", "hier", "hij", "hoe", "hun", "ik", "in", "is",
        "je", "kan", "komen", "maar", "met", "na", "naar", "niet", "nog", "of",
        "om", "onder", "ook", "op", "over", "reeds", "te", "tegen", "ten", "ter",
        "tot", "uit", "van", "vanaf", "veel", "voor", "want", "was", "wat",
        "we", "werd", "werken", "wezen", "wie", "wij", "worden", "wordt", "zal",
        "ze", "zei", "zelf", "zich", "zij", "zijn", "zo", "zonder", "zou",
        # edition / formula glue that is not content
        "hhm", "haarer", "hoog", "mogende", "heeren", "staten", "generaal",
        "resolutie", "missive", "rekest", "verzoek", "verlenen", "ordonnantie",
        "brengen", "lezen", "schrijven", "leggen", "doen", "waren", "werd",
        "wordt", "zullen", "kunnen", "moeten", "heeft", "hebben", "waren",
        "enkele", "enkele", "verscheidene", "stukken", "aantal", "gedeelte",
    }
)


@lru_cache(maxsize=1)
def _ledger_rows() -> tuple[dict[str, Any], ...]:
    return tuple(load(LEDGER))


@lru_cache(maxsize=1)
def _parent_by_axis_id() -> dict[str, dict[str, Any]]:
    return {
        str(row["axis_id"]): row
        for row in load(PARENT_AXIS)
        if row.get("axis_id")
    }


@lru_cache(maxsize=1)
def _successor_rows() -> tuple[dict[str, Any], ...]:
    return tuple(load(SUCCESSOR_AXIS))


@lru_cache(maxsize=1)
def _concordance() -> pd.DataFrame:
    frame = load(CONCORDANCE)
    if not isinstance(frame, pd.DataFrame):
        frame = pd.DataFrame(frame)
    work = frame.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    if "resolved_session_date" in work.columns:
        work["resolved_session_date"] = (
            work["resolved_session_date"].astype(str).str.slice(0, 10)
        )
    # Scope bar + main series at entry (same as P5 persist).
    work = work.loc[work["enriched_date"].map(in_scope)].copy()
    if "inventory_id" in work.columns:
        work["inventory_id"] = work["inventory_id"].map(
            lambda value: str(int(float(value)))
            if value is not None and str(value).strip() not in {"", "nan"}
            else ""
        )
        work = work.loc[work["inventory_id"].map(is_main_series)].copy()
    return work


@lru_cache(maxsize=1)
def _ledger_by_date() -> dict[str, dict[str, Any]]:
    return {
        str(row["enriched_date"])[:10]: dict(row)
        for row in _ledger_rows()
        if row.get("record_type") == "day" and row.get("enriched_date")
    }


@lru_cache(maxsize=1)
def _axis_indexes() -> tuple[Any, Any, Any]:
    return load_axis_indexes()


def day_axis(date: str) -> list[dict[str, Any]]:
    """Resolved-session (else same-day) paragraph stream for a date — same as P4/P5."""
    axis_by_date, axis_by_session, session_by_date = _axis_indexes()
    return list(axis_for_date(str(date)[:10], axis_by_date, axis_by_session, session_by_date))


def calendar_day_axis(date: str) -> list[dict[str, Any]]:
    """Paragraphs keyed by calendar ``date`` only (main series) — ignores PINNED_TO pin.

    Use for same-day content checks when the resolved-session stream may be the wrong
    sitting (monotone-ok off-by-one). Secret inventories are dropped at entry.
    """
    axis_by_date, _axis_by_session, _session_by_date = _axis_indexes()
    rows = list(axis_by_date.get(str(date)[:10], []))
    out: list[dict[str, Any]] = []
    for row in rows:
        flat = str(row.get("flat_id") or row.get("session_id") or "")
        if flat and not is_main_series(flat):
            continue
        if not flat:
            # Undated / missing id — keep only if inventory field says main.
            inv = row.get("inventory_id")
            if inv is not None and str(inv).strip() not in {"", "nan"}:
                try:
                    if not is_main_series(str(int(float(inv)))):
                        continue
                except (TypeError, ValueError):
                    continue
        out.append(row)
    return out


@lru_cache(maxsize=1)
def _session_date_status() -> pd.DataFrame:
    frame = load(SESSION_DATE_STATUS)
    if not isinstance(frame, pd.DataFrame):
        frame = pd.DataFrame(frame)
    work = frame.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    if "inventory_id" in work.columns:
        work = work.loc[
            work["inventory_id"].map(
                lambda value: is_main_series(str(int(float(value))))
                if value is not None and str(value).strip() not in {"", "nan"}
                else False
            )
        ].copy()
    return work


def summary() -> dict[str, Any] | None:
    for row in _ledger_rows():
        if row.get("record_type") == "summary":
            return dict(row)
    return None


def _stub_day(date: str) -> dict[str, Any]:
    """Concordance sitting day with no P5 ledger row (explore-only)."""
    return {
        "record_type": "day",
        "enriched_date": str(date)[:10],
        "in_ledger": False,
        "day_accepted": False,
        "delta_vs_plain": 0,
        "separated_predicted": None,
        "separated_plain": None,
        "separated_uniform_successor": None,
        "n_cuts_gated": 0,
        "n_cuts_needed": 0,
        "n_hosts_accepted": 0,
        "n_colliding_hosts": 0,
        "n_paragraphs_before": None,
        "n_paragraphs_after": None,
        "n_extent_gt_max_predicted": None,
        "n_extent_gt_max_plain": None,
        "k_e": None,
        "host_cut_fill": [],
    }


def day_record(date: str) -> dict[str, Any]:
    """Ledger row when present; otherwise a corpus stub for exploration."""
    key = str(date)[:10]
    ledger = _ledger_by_date().get(key)
    if ledger is not None:
        row = dict(ledger)
        row["in_ledger"] = True
        return row
    return _stub_day(key)


def colliding_hosts_from_resolutions(
    date: str,
    resolutions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build host_cut_fill-shaped rows from concordance collisions (no P5 gate)."""
    rows = resolutions if resolutions is not None else day_resolutions(date)
    by_start: dict[int, list[dict[str, Any]]] = {}
    for res in rows:
        start = res.get("paragraph_start_index")
        if start is None:
            continue
        by_start.setdefault(int(start), []).append(res)
    axis = day_axis(date)
    hosts: list[dict[str, Any]] = []
    for para, members in sorted(by_start.items()):
        if len(members) < 2:
            continue
        record = axis[para] if 0 <= para < len(axis) else {}
        axis_id = str(record.get("axis_id") or members[0].get("parent_axis_id") or "")
        # If this host was split in P5, treat as accepted for piece display.
        pieces = successor_pieces_for_host(axis_id) if axis_id else []
        hosts.append(
            {
                "paragraph_start_index": para,
                "axis_id": axis_id,
                "n_share": len(members),
                "n_needed": len(members) - 1,
                "n_cuts_raw": max(0, len(pieces) - 1) if pieces else 0,
                "n_cuts_gated": max(0, len(pieces) - 1) if pieces else 0,
                "host_accepted": bool(pieces),
            }
        )
    return hosts


def list_days(*, mode: FilterMode = "accepted") -> list[dict[str, Any]]:
    """List days for the viewer.

    Ledger modes (``accepted`` / ``rejected`` / ``all`` / ``suspect``) stay on the
    P5 colliding-day ledger, sorted by Δ. ``corpus`` walks every in-scope
    main-series enriched date (chronological), merging ledger rows when present.
    """
    if mode == "corpus":
        dates = sorted(_concordance()["enriched_date"].unique())
        return [day_record(str(date)) for date in dates]

    days = [
        dict(row)
        for row in _ledger_rows()
        if row.get("record_type") == "day"
    ]
    for day in days:
        day["in_ledger"] = True
    if mode == "accepted":
        days = [d for d in days if d.get("day_accepted")]
    elif mode == "rejected":
        days = [d for d in days if not d.get("day_accepted")]
    elif mode == "suspect":
        suspect_days: list[dict[str, Any]] = []
        for day in days:
            if not day.get("day_accepted"):
                continue
            hosts = host_views(day)
            if any(h.get("content_suspect") and h.get("host_accepted") for h in hosts):
                suspect_days.append(day)
        days = suspect_days
    days.sort(
        key=lambda d: (
            -int(d.get("delta_vs_plain") or 0),
            str(d.get("enriched_date") or ""),
        )
    )
    return days


def day_index(days: list[dict[str, Any]], date: str) -> int:
    for idx, row in enumerate(days):
        if str(row.get("enriched_date")) == date:
            return idx
    raise KeyError(date)


def list_days_in_range(
    start: str,
    end: str,
    *,
    mode: FilterMode = "corpus",
) -> list[dict[str, Any]]:
    """Days with ``start ≤ enriched_date ≤ end`` (inclusive ISO strings)."""
    lo, hi = str(start)[:10], str(end)[:10]
    if lo > hi:
        lo, hi = hi, lo
    return [
        day
        for day in list_days(mode=mode)
        if lo <= str(day.get("enriched_date") or "")[:10] <= hi
    ]


def successor_pieces_for_host(axis_id: str) -> list[dict[str, Any]]:
    """Pieces whose ``axis_id`` is ``{parent_axis_id}#repara:…``."""
    prefix = f"{axis_id}#repara:"
    return [dict(row) for row in _successor_rows() if str(row.get("axis_id") or "").startswith(prefix)]


def _na_str(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    return text


def _normalize_text(text: str) -> str:
    lowered = str(text or "").lower()
    # light early-modern orthography collapse for substring hits
    return (
        lowered.replace("ue", "ve")
        .replace("uy", "ui")
        .replace("ae", "aa")
        .replace("ck", "k")
    )


def content_tokens(text: str) -> set[str]:
    """Distinctive tokens from a modern summary (names, places, numbers)."""
    import re

    norm = _normalize_text(text)
    raw = re.findall(r"[0-9]+|[a-zà-ÿ]{%d,}" % CONTENT_MIN_TOKEN_LEN, norm)
    kept: set[str] = set()
    for tok in raw:
        if tok.isdigit():
            if len(tok) >= 3:
                kept.add(tok)
        elif tok not in _STOP:
            kept.add(tok)
    return kept


def summary_parent_overlap(
    summaries: list[str],
    parent_text: str,
) -> dict[str, Any]:
    """Cheap content check: union of summary content tokens vs parent HTR.

    Returns hit_rate in ``[0, 1]``, ``hits``, ``n_tokens``, and ``suspect`` when
    evidence is enough and the rate/hits fall below threshold.
    """
    parent_norm = _normalize_text(parent_text)
    tokens: set[str] = set()
    for summary in summaries:
        tokens |= content_tokens(summary)
    if not parent_norm.strip() or not tokens:
        return {
            "hit_rate": 0.0,
            "hits": 0,
            "n_tokens": len(tokens),
            "suspect": False,
            "insufficient": True,
        }

    hits = sum(1 for tok in tokens if tok in parent_norm)
    rate = hits / len(tokens)
    insufficient = len(tokens) < CONTENT_MIN_SUMMARY_TOKENS
    suspect = (not insufficient) and (
        hits < CONTENT_SUSPECT_MIN_HITS or rate <= CONTENT_SUSPECT_MAX_HIT_RATE
    )
    return {
        "hit_rate": round(rate, 4),
        "hits": int(hits),
        "n_tokens": int(len(tokens)),
        "suspect": bool(suspect),
        "insufficient": bool(insufficient),
    }


def day_resolutions(date: str) -> list[dict[str, Any]]:
    """Enriched summaries for a sitting day, with collision + day-shift flags."""
    frame = _concordance()
    enriched = str(date)[:10]
    day = frame.loc[frame["enriched_date"] == enriched]
    if day.empty:
        return []
    ordered = day.sort_values("resolution_index")
    placed = ordered.dropna(subset=["paragraph_start_index"])
    share = (
        placed.groupby("paragraph_start_index").size()
        if not placed.empty
        else pd.Series(dtype=int)
    )
    axis = day_axis(enriched)
    rows: list[dict[str, Any]] = []
    for row in ordered.itertuples(index=False):
        start = row.paragraph_start_index
        start_i: int | None
        n_share = 1
        if start is None or (isinstance(start, float) and pd.isna(start)):
            start_i = None
        else:
            start_i = int(start)
            n_share = int(share.get(start_i, 1)) if len(share) else 1
        end = getattr(row, "paragraph_end_index", None)
        end_i: int | None = None
        if end is not None and not (isinstance(end, float) and pd.isna(end)):
            end_i = int(end)
        text = getattr(row, "text", None)
        session_date = _na_str(getattr(row, "resolved_session_date", None))
        if session_date:
            session_date = session_date[:10]
        day_shifted = bool(session_date and session_date != enriched)
        parent_text = ""
        parent_axis_id = None
        parent_flat_id = None
        if start_i is not None and 0 <= start_i < len(axis):
            parent_row = axis[start_i]
            parent_text = str(parent_row.get("text") or "")
            parent_axis_id = parent_row.get("axis_id")
            parent_flat_id = parent_row.get("flat_id")
        rows.append(
            {
                "resolution_index": int(row.resolution_index),
                "enriched_id": getattr(row, "enriched_id", None),
                "paragraph_start_index": start_i,
                "paragraph_end_index": end_i,
                "n_share": n_share,
                "colliding": n_share >= 2,
                "unsplit": start_i is not None and n_share == 1,
                "unplaced": start_i is None,
                "day_status": _na_str(getattr(row, "day_status", None)),
                "resolved_session_id": _na_str(getattr(row, "resolved_session_id", None)),
                "resolved_session_date": session_date,
                "day_shifted": day_shifted,
                "parent_text": parent_text,
                "parent_axis_id": parent_axis_id,
                "parent_flat_id": parent_flat_id,
                "text": (
                    ""
                    if text is None or (isinstance(text, float) and pd.isna(text))
                    else str(text)
                ),
            }
        )
    return rows


def _overlap_is_match(overlap: dict[str, Any]) -> bool:
    """True when lexical evidence is enough and not suspect."""
    return (not overlap.get("insufficient")) and (not overlap.get("suspect"))


def _overlap_is_fail(overlap: dict[str, Any], *, empty_parent: bool) -> bool:
    """Fail = empty parent with tokens, or enough evidence that looks wrong."""
    if empty_parent and int(overlap.get("n_tokens") or 0) >= CONTENT_MIN_SUMMARY_TOKENS:
        return True
    return bool(overlap.get("suspect")) and (not overlap.get("insufficient"))


def _longest_run(flags: list[bool | None], want: bool) -> int:
    best = 0
    cur = 0
    for flag in flags:
        if flag is True and want:
            cur += 1
            best = max(best, cur)
        elif flag is False and not want:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def content_run_against_text(
    summaries: list[str],
    parent_text: str,
    *,
    k: int = CONTENT_RUN_K,
) -> dict[str, Any]:
    """Score an ordered list of summaries against one parent text blob.

    Returns ``content_ok`` / ``content_fail`` / ``content_unknown`` from longest
    consecutive match/fail runs of length ``k``. Monotone/order is not consulted.
    """
    empty_parent = not str(parent_text or "").strip()
    outcomes: list[bool | None] = []
    per: list[dict[str, Any]] = []
    for summary in summaries:
        overlap = summary_parent_overlap([summary], parent_text)
        matched = _overlap_is_match(overlap)
        failed = _overlap_is_fail(overlap, empty_parent=empty_parent)
        if matched:
            outcomes.append(True)
            label = "match"
        elif failed:
            outcomes.append(False)
            label = "fail"
        else:
            outcomes.append(None)
            label = "unknown"
        per.append({**overlap, "label": label})
    match_run = _longest_run(outcomes, True)
    fail_run = _longest_run(outcomes, False)
    if fail_run >= k:
        verdict = "content_fail"
    elif match_run >= k:
        verdict = "content_ok"
    else:
        verdict = "content_unknown"
    return {
        "verdict": verdict,
        "k": k,
        "match_run": match_run,
        "fail_run": fail_run,
        "n_scored": len(summaries),
        "n_match": sum(1 for o in outcomes if o is True),
        "n_fail": sum(1 for o in outcomes if o is False),
        "n_unknown": sum(1 for o in outcomes if o is None),
        "per_resolution": per,
    }


def day_content_run_verdict(
    date: str,
    resolutions: list[dict[str, Any]] | None = None,
    *,
    k: int = CONTENT_RUN_K,
) -> dict[str, Any]:
    """Same-day content runs on pin stream vs calendar stream (main series).

    - **pin**: joined text from ``day_axis`` (follows PINNED_TO) — binding check.
    - **calendar**: joined text from ``calendar_day_axis`` — sitting-day archive check.

    Does not replace hard_pin monotone; surfaces false-good pins that stay in order.
    """
    enriched = str(date)[:10]
    rows = resolutions if resolutions is not None else day_resolutions(enriched)
    # Business rows only: skip pure nihil stubs with no placement ambition.
    summaries: list[str] = []
    for r in sorted(rows, key=lambda x: int(x.get("resolution_index") or 0)):
        text = str(r.get("text") or "").strip()
        if not text:
            continue
        status = str(r.get("day_status") or "")
        if status == "nihil_actum":
            continue
        summaries.append(text)

    pin_paras = day_axis(enriched)
    cal_paras = calendar_day_axis(enriched)
    pin_text = "\n".join(str(p.get("text") or "") for p in pin_paras)
    cal_text = "\n".join(str(p.get("text") or "") for p in cal_paras)

    pin_run = content_run_against_text(summaries, pin_text, k=k)
    cal_run = content_run_against_text(summaries, cal_text, k=k)

    # Day headline: pin binding drives the review flag; calendar is the twin signal.
    if pin_run["verdict"] == "content_fail":
        day_verdict = "content_fail"
    elif pin_run["verdict"] == "content_ok":
        day_verdict = "content_ok"
    else:
        day_verdict = "content_unknown"

    return {
        "day_verdict": day_verdict,
        "k": k,
        "n_summaries": len(summaries),
        "pin": {
            **{kk: vv for kk, vv in pin_run.items() if kk != "per_resolution"},
            "n_paragraphs": len(pin_paras),
        },
        "calendar": {
            **{kk: vv for kk, vv in cal_run.items() if kk != "per_resolution"},
            "n_paragraphs": len(cal_paras),
        },
        # Diagnostic: calendar ok + pin fail ⇒ wrong pin, right sitting day.
        "calendar_ok_pin_fail": (
            cal_run["verdict"] == "content_ok" and pin_run["verdict"] == "content_fail"
        ),
    }


def pin_trusted_mismatch(date: str, resolutions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Same-day: concordance pin vs session_date_status trusted/exact (no neighbour days)."""
    enriched = str(date)[:10]
    rows = resolutions if resolutions is not None else day_resolutions(enriched)
    pins = sorted(
        {
            str(r["resolved_session_id"])
            for r in rows
            if r.get("resolved_session_id")
        }
    )
    status = _session_date_status()
    hit = status.loc[status["enriched_date"] == enriched]
    trusted: list[str] = []
    exact: list[str] = []
    status_code = None
    if not hit.empty:
        row = hit.iloc[0]
        status_code = row.get("status_code")
        for col, bucket in (
            ("trusted_session_ids", trusted),
            ("exact_date_session_ids", exact),
        ):
            raw = row.get(col)
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            if isinstance(raw, str):
                bucket.append(raw)
            else:
                try:
                    bucket.extend(str(x) for x in list(raw) if x)
                except TypeError:
                    pass
    reference = sorted(set(exact) or set(trusted))
    mismatch = bool(pins) and bool(reference) and set(pins).isdisjoint(set(reference))
    return {
        "pin_sessions": pins,
        "trusted_sessions": sorted(set(trusted)),
        "exact_sessions": sorted(set(exact)),
        "status_code": None if status_code is None or (isinstance(status_code, float) and pd.isna(status_code)) else str(status_code),
        "mismatch": mismatch,
    }


def day_context(date: str, resolutions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Day-level session / shift summary for the meta strip."""
    rows = resolutions if resolutions is not None else day_resolutions(date)
    sessions = sorted(
        {
            r["resolved_session_id"]
            for r in rows
            if r.get("resolved_session_id")
        }
    )
    session_dates = sorted(
        {
            r["resolved_session_date"]
            for r in rows
            if r.get("resolved_session_date")
        }
    )
    n_shifted = sum(1 for r in rows if r.get("day_shifted"))
    content_run = day_content_run_verdict(date, rows)
    pin_trust = pin_trusted_mismatch(date, rows)
    return {
        "enriched_date": str(date)[:10],
        "resolved_session_ids": sessions,
        "resolved_session_dates": session_dates,
        "day_shifted_count": n_shifted,
        "n_unsplit": sum(1 for r in rows if r.get("unsplit")),
        "n_colliding": sum(1 for r in rows if r.get("colliding")),
        "n_unplaced": sum(1 for r in rows if r.get("unplaced")),
        "content_run": content_run,
        "pin_trusted": pin_trust,
    }


def _hover_snip(text: str, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _session_of_flat(flat_id: str | None) -> str | None:
    flat = str(flat_id or "")
    if "-resolution-" in flat:
        return flat.split("-resolution-", 1)[0]
    if flat.startswith("session-"):
        return flat
    return None


def tier_day_payload(date: str) -> dict[str, Any]:
    """Three same-day tiers + cross-tier edges for the tier viewer.

    Tiers (evidence streams for one sitting day — not neighbour days):
      editorial — enriched summaries
      pin_htr — paragraphs from ``day_axis`` (follows PINNED_TO)
      calendar_htr — paragraphs dated this calendar day (main series)

    Edges name the spine relation they illustrate; hover carries text snippets.
    """
    enriched = str(date)[:10]
    rows = day_resolutions(enriched)
    ctx = day_context(enriched, rows)
    pin_paras = day_axis(enriched)
    cal_paras = calendar_day_axis(enriched)
    pin_trust = ctx["pin_trusted"]
    trusted = set(pin_trust.get("exact_sessions") or []) | set(
        pin_trust.get("trusted_sessions") or []
    )
    pin_sessions = set(pin_trust.get("pin_sessions") or [])

    editorial: list[dict[str, Any]] = []
    for r in sorted(rows, key=lambda x: int(x.get("resolution_index") or 0)):
        idx = int(r.get("resolution_index") or 0)
        text = str(r.get("text") or "")
        editorial.append(
            {
                "id": f"e{idx}",
                "index": idx,
                "label": f"#{idx}",
                "para_start": r.get("paragraph_start_index"),
                "para_end": r.get("paragraph_end_index"),
                "session_id": r.get("resolved_session_id"),
                "text": text,
                "hover": _hover_snip(text),
                "unsplit": bool(r.get("unsplit")),
                "unplaced": bool(r.get("unplaced")),
            }
        )

    def _htr_nodes(paras: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for i, p in enumerate(paras):
            flat = str(p.get("flat_id") or "")
            sess = _session_of_flat(flat)
            text = str(p.get("text") or "")
            nodes.append(
                {
                    "id": f"{prefix}{i}",
                    "index": i,
                    "label": flat.split("-resolution-")[-1] if flat else f"p{i}",
                    "flat_id": flat or None,
                    "session_id": sess,
                    "axis_date": str(p.get("date") or "")[:10] or None,
                    "text": text,
                    "hover": _hover_snip(text),
                    "is_pin": bool(sess and sess in pin_sessions),
                    "is_trusted": bool(sess and sess in trusted),
                }
            )
        return nodes

    pin_nodes = _htr_nodes(pin_paras, "p")
    cal_nodes = _htr_nodes(cal_paras, "c")

    edges: list[dict[str, Any]] = []
    # ALIGNED_TO (inferred): editorial → pin paragraph by start index.
    for e in editorial:
        start = e.get("para_start")
        if start is None:
            continue
        try:
            si = int(start)
        except (TypeError, ValueError):
            continue
        if 0 <= si < len(pin_nodes):
            target = pin_nodes[si]
            ov = summary_parent_overlap([e["text"]], target["text"])
            edges.append(
                {
                    "from_lane": "editorial",
                    "from_id": e["id"],
                    "to_lane": "pin_htr",
                    "to_id": target["id"],
                    "kind": "ALIGNED_TO",
                    "inferred": True,
                    "hits": ov["hits"],
                    "suspect": ov["suspect"],
                    "hover": (
                        f"ALIGNED_TO (via PINNED_TO axis) · hits={ov['hits']} "
                        f"· {e['hover'][:80]} ↔ {target['hover'][:80]}"
                    ),
                }
            )
        # Best calendar paragraph (same-day content path — not the pin).
        if cal_nodes:
            best = None
            for c in cal_nodes:
                ov = summary_parent_overlap([e["text"]], c["text"])
                score = (ov["hits"], ov["hit_rate"])
                if best is None or score > best[0]:
                    best = (score, c, ov)
            if best and best[2]["hits"] >= CONTENT_SUSPECT_MIN_HITS:
                _score, c, ov = best
                edges.append(
                    {
                        "from_lane": "editorial",
                        "from_id": e["id"],
                        "to_lane": "calendar_htr",
                        "to_id": c["id"],
                        "kind": "content_match",
                        "inferred": False,
                        "hits": ov["hits"],
                        "suspect": ov["suspect"],
                        "hover": (
                            f"same-day content match · hits={ov['hits']} "
                            f"· {c.get('flat_id') or c['id']}"
                        ),
                    }
                )

    # PINNED_TO day→session (one edge per distinct pin).
    for sess in sorted(pin_sessions):
        edges.append(
            {
                "from_lane": "editorial",
                "from_id": editorial[0]["id"] if editorial else "day",
                "to_lane": "pin_htr",
                "to_id": next(
                    (n["id"] for n in pin_nodes if n.get("session_id") == sess),
                    pin_nodes[0]["id"] if pin_nodes else "pin",
                ),
                "kind": "PINNED_TO",
                "inferred": True,
                "session_id": sess,
                "hover": f"PINNED_TO → {sess} (inferred)",
            }
        )

    return {
        "enriched_date": enriched,
        "lanes": {
            "editorial": editorial,
            "pin_htr": pin_nodes,
            "calendar_htr": cal_nodes,
        },
        "edges": edges,
        "content_run": ctx["content_run"],
        "pin_trusted": pin_trust,
        "context": {
            "n_unsplit": ctx["n_unsplit"],
            "n_colliding": ctx["n_colliding"],
            "n_unplaced": ctx["n_unplaced"],
            "day_shifted_count": ctx["day_shifted_count"],
        },
    }


def day_sync_report_row(date: str) -> dict[str, Any]:
    """One flat report row for a sitting day (content run + pin≠trusted)."""
    enriched = str(date)[:10]
    rows = day_resolutions(enriched)
    ctx = day_context(enriched, rows)
    cr = ctx["content_run"]
    pt = ctx["pin_trusted"]
    return {
        "record_type": "day",
        "enriched_date": enriched,
        "n_resolutions": len(rows),
        "n_summaries_scored": cr.get("n_summaries"),
        "content_day_verdict": cr.get("day_verdict"),
        "content_pin_verdict": (cr.get("pin") or {}).get("verdict"),
        "content_calendar_verdict": (cr.get("calendar") or {}).get("verdict"),
        "content_pin_fail_run": (cr.get("pin") or {}).get("fail_run"),
        "content_pin_match_run": (cr.get("pin") or {}).get("match_run"),
        "content_cal_fail_run": (cr.get("calendar") or {}).get("fail_run"),
        "content_cal_match_run": (cr.get("calendar") or {}).get("match_run"),
        "calendar_ok_pin_fail": bool(cr.get("calendar_ok_pin_fail")),
        "pin_trusted_mismatch": bool(pt.get("mismatch")),
        "pin_sessions": pt.get("pin_sessions") or [],
        "trusted_sessions": pt.get("trusted_sessions") or [],
        "exact_sessions": pt.get("exact_sessions") or [],
        "status_code": pt.get("status_code"),
        "flag_review": bool(
            cr.get("day_verdict") == "content_fail"
            or cr.get("calendar_ok_pin_fail")
            or pt.get("mismatch")
        ),
    }


def attach_content_flags(hosts: list[dict[str, Any]]) -> dict[str, Any]:
    """Mutate host dicts with content overlap; return day-level suspect summary."""
    n_suspect = 0
    n_checked = 0
    for host in hosts:
        summaries = [str(s.get("text") or "") for s in (host.get("summaries") or [])]
        overlap = summary_parent_overlap(summaries, str(host.get("parent_text") or ""))
        host["content_hit_rate"] = overlap["hit_rate"]
        host["content_hits"] = overlap["hits"]
        host["content_n_tokens"] = overlap["n_tokens"]
        host["content_insufficient"] = overlap["insufficient"]
        # Only brand accepted hosts as suspect false-accepts.
        suspect = bool(host.get("host_accepted")) and bool(overlap["suspect"])
        host["content_suspect"] = suspect
        if not overlap["insufficient"] and host.get("host_accepted"):
            n_checked += 1
        if suspect:
            n_suspect += 1
    return {
        "n_content_suspect_hosts": n_suspect,
        "n_content_checked_hosts": n_checked,
        "day_suspect": n_suspect > 0,
    }


def host_views(
    day: dict[str, Any],
    resolutions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Per-host payload: colliding summaries + parent text + successor pieces."""
    parent = _parent_by_axis_id()
    date = str(day.get("enriched_date") or "")
    all_res = resolutions if resolutions is not None else day_resolutions(date)
    by_start: dict[int, list[dict[str, Any]]] = {}
    for res in all_res:
        start = res.get("paragraph_start_index")
        if start is None:
            continue
        by_start.setdefault(int(start), []).append(res)

    hosts = list(day.get("host_cut_fill") or [])
    if not hosts:
        hosts = colliding_hosts_from_resolutions(date, all_res)

    views: list[dict[str, Any]] = []
    hosts.sort(key=lambda h: (not bool(h.get("host_accepted")), int(h.get("paragraph_start_index") or 0)))
    for host in hosts:
        axis_id = str(host.get("axis_id") or "")
        parent_row = parent.get(axis_id)
        # Prefer live axis_for_date text when parent lookup misses (corpus stubs).
        if parent_row is None:
            para = int(host.get("paragraph_start_index") or 0)
            axis = day_axis(date)
            parent_row = axis[para] if 0 <= para < len(axis) else None
            if parent_row is not None and not axis_id:
                axis_id = str(parent_row.get("axis_id") or "")
        pieces = successor_pieces_for_host(axis_id) if axis_id else []
        # Ledger gate OR pieces present on successor axis.
        host_accepted = bool(host.get("host_accepted")) or bool(pieces)
        para = int(host.get("paragraph_start_index") or 0)
        views.append(
            {
                "paragraph_start_index": host.get("paragraph_start_index"),
                "axis_id": axis_id,
                "n_share": host.get("n_share"),
                "n_needed": host.get("n_needed"),
                "n_cuts_raw": host.get("n_cuts_raw"),
                "n_cuts_gated": host.get("n_cuts_gated"),
                "host_accepted": host_accepted,
                "parent_text": str(parent_row.get("text") or "") if parent_row else "",
                "parent_missing": parent_row is None,
                "parent_date": parent_row.get("date") if parent_row else None,
                "parent_flat_id": parent_row.get("flat_id") if parent_row else None,
                "summaries": by_start.get(para, []),
                "pieces": [
                    {
                        "axis_id": p.get("axis_id"),
                        "para_index": p.get("para_index"),
                        "parent_char_start": p.get("parent_char_start"),
                        "parent_char_end": p.get("parent_char_end"),
                        "text": p.get("text") or "",
                    }
                    for p in pieces
                ],
            }
        )
    attach_content_flags(views)
    return views


def unsplit_resolutions(
    day: dict[str, Any],
    resolutions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Placed but not colliding — explore without searching host cards."""
    date = str(day.get("enriched_date") or "")
    all_res = resolutions if resolutions is not None else day_resolutions(date)
    return [res for res in all_res if res.get("unsplit")]


def day_shifted_resolutions(
    day: dict[str, Any],
    resolutions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Resolutions whose resolved session date ≠ enriched date (PINNED_TO shift)."""
    date = str(day.get("enriched_date") or "")
    all_res = resolutions if resolutions is not None else day_resolutions(date)
    return [res for res in all_res if res.get("day_shifted")]


def unplaced_resolutions(
    day: dict[str, Any],
    resolutions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    date = str(day.get("enriched_date") or "")
    all_res = resolutions if resolutions is not None else day_resolutions(date)
    return [res for res in all_res if res.get("unplaced")]


def stats(mode: FilterMode) -> dict[str, int]:
    ledger_days = [r for r in _ledger_rows() if r.get("record_type") == "day"]
    accepted = sum(1 for d in ledger_days if d.get("day_accepted"))
    corpus_n = int(_concordance()["enriched_date"].nunique())
    return {
        "total": corpus_n if mode == "corpus" else len(ledger_days),
        "accepted": accepted,
        "rejected": len(ledger_days) - accepted,
        "showing": len(list_days(mode=mode)),
        "corpus": corpus_n,
        "ledger": len(ledger_days),
    }
