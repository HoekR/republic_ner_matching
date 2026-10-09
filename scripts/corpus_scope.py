#!/usr/bin/env python3
"""The corpus scope bar: **nothing after the XML baseline's last date exists for this project.**

**Rule (user, 2026-09-25, restated as FULL STOP 2026-10-08):** the enriched edition ends
**1630-05-14**. Do not reconsider dates after it. Do not take scans or HTR text after it into
account. Not as a population, not as a denominator, not as a diagnostic, not as a side finding.

This module exists because the rule was already written down and I broke it anyway. It was
recorded in `plans/COLLISION_AVOIDANCE_TRACK.md` (line 28) and enforced by
`session_offset_eval.restrict_to_enriched_span` -- but that helper takes a DataFrame with
`session_date`/`inventory_id`/`flat_num` columns, so work on any other shape (the scan-sequence
track keys `(inventory, scan, date)` tuples) silently bypassed it and 47 days of
1630-05-29..1630-12-09 came back as a "finding" about unaccounted pages. One shape-agnostic
primitive, used by everything, is the fix; a second convention is not.

**Why the bar is real and not a convenience.** The HTR axis runs to 1630-12-31 and carries 184
sessions past the edition's end (180 in 3189, 4 in 4562). An HTR session past the end has no
sitting the edition could ever record, so there is nothing to align it to, no `k_e` to compare it
against, and any correspondence offered to it is invented. Counting such material in a denominator
understates every rate; reporting its lack of a counterpart as a gap manufactures a finding.

Usage -- the end date is DERIVED from the baseline, never hardcoded:

    from scripts.corpus_scope import enriched_end, in_scope, split_by_scope

    if not in_scope(date):      # a single date
        continue
    kept, dropped = split_by_scope(frame, "date")   # a frame
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, TypeVar

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load

BASELINE_DATASET = "enriched_resolutions_1626_1630"

# The rule's own text, so a dataset's `meta` can carry it verbatim instead of paraphrasing it.
SCOPE_RULE = (
    "The enriched XML edition ends 1630-05-14 (user, 2026-09-25, restated FULL STOP "
    "2026-10-08): dates after it are not reconsidered and scans or HTR text after it are not "
    "taken into account -- not as a population, a denominator, a diagnostic or a side finding. "
    "The HTR axis runs to 1630-12-31, so material past the bar exists on disk and must be "
    "dropped explicitly; see scripts/corpus_scope.py."
)

# Asserted, not relied on: the derived value must equal the date the rule names. If the baseline
# ever changes, this fails loudly rather than silently moving the bar.
EXPECTED_END = "1630-05-14"


@lru_cache(maxsize=1)
def enriched_end() -> pd.Period:
    """The XML baseline's last date, read from the baseline itself (`pd.Period`, never Timestamp)."""
    dates = {
        str(record.get("date"))[:10]
        for record in load(BASELINE_DATASET)
    }
    real = sorted(d for d in dates if d[:1].isdigit())
    if not real:
        raise RuntimeError(f"{BASELINE_DATASET} yielded no parseable dates")
    end = real[-1]
    if end != EXPECTED_END:
        raise AssertionError(
            f"corpus scope bar moved: {BASELINE_DATASET} now ends {end}, rule names "
            f"{EXPECTED_END}. This is not a thing to silently accept -- confirm with the user "
            f"before changing EXPECTED_END."
        )
    return pd.Period(end, freq="D")


def in_scope(date: str | pd.Period | None) -> bool:
    """True iff `date` is on or before the baseline's last date. `None`/unparseable is out."""
    if date is None:
        return False
    text = str(date)[:10]
    if not text[:1].isdigit():
        return False
    return text <= str(enriched_end())


T = TypeVar("T")


def drop_out_of_scope(items: Iterable[T], key) -> tuple[list[T], list[T]]:
    """Split any iterable by `in_scope(key(item))`. Returns (kept, dropped)."""
    kept: list[T] = []
    dropped: list[T] = []
    for item in items:
        (kept if in_scope(key(item)) else dropped).append(item)
    return kept, dropped


def split_by_scope(frame: pd.DataFrame, date_column: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a frame on a date column. Returns (in_scope, out_of_scope), both copies."""
    mask = frame[date_column].map(in_scope)
    return frame.loc[mask].copy(), frame.loc[~mask].copy()


def scope_meta() -> dict[str, str]:
    """The block every dataset touching dated HTR material should carry in its `meta` row."""
    return {"corpus_scope_rule": SCOPE_RULE, "corpus_scope_last_date": str(enriched_end())}


# --------------------------------------------------------------------------------------------
# The sequence is the main register. The secret series is sidelined.
# --------------------------------------------------------------------------------------------
# User, 2026-10-08: *"leave 4562 out of it! it is something different. Sideline them, they do not
# enter into the sequence as yet"*. Promoted here from a per-script constant for the same reason
# the scope bar was: it existed as `PATHOLOGICAL_INVENTORIES` in `measure_scans_per_day`, was
# imported by name, and got breached anyway by a new measurement that had its own idea of a
# denominator. A rule that is not executable at the point data enters a script is a rule that
# gets broken.

MAIN_SERIES: frozenset[str] = frozenset({"3185", "3186", "3187", "3188", "3189"})
"""The ordinary resolution registers 1626-1630. These are *the* sequence."""

SIDELINED_INVENTORIES: frozenset[str] = frozenset({"4562", "4861"})
"""The secret series. Sidelined from the sequence, not down-weighted inside it.

The reason is editorial rather than statistical, which is why a threshold would be the wrong
instrument: they are not part of the main register's running order yet. Two measured traps make
including them actively misleading rather than merely noisy:

1. **Their anchors are 700 days apart** (8 anchors across the whole period on adjacent scans), so
   any date-window test they enter succeeds trivially -- `sequence_reconciliation` had them
   "reconciling" at 70% against the main series' 43% purely on window width.
2. **Every unplaced date is filed under them by a tautology.** All 344 in-scope dates with no
   resolved session (4,482 `k_e`) carry candidate inventory 4562 or 4861 and none carries a main
   series one -- because `DateState.candidate_inventory` holds 3-4 candidates per date and the
   surviving pick tends to be a secret inventory. `DateState`'s own docstring names this: grouping
   unplaced dates by that field "discovers" that dates without HTR belong to the inventories
   without HTR. **So sidelining these inventories sidelines the unplaced mass without resolving
   it, and a main-series `n_e == 0` is that artefact rather than a mapping result.** Any claim
   about main-series coverage must say which of the two it means.
"""


def inventory_of(identifier: str) -> str | None:
    """The inventory in a `session-3185-num-12` or `NL-HaNA_1.01.02_3185_0190` style identifier."""
    text = str(identifier)
    for part in text.replace("_", "-").split("-"):
        if part.isdigit() and len(part) == 4:
            return part
    return None


def is_sidelined(identifier: str | None) -> bool:
    """True for the secret series. A missing or unreadable inventory is **not** sidelined.

    Fails *open* here, deliberately opposite to `in_scope`: the scope bar drops what it cannot
    date because including post-bar material corrupts a result, whereas silently sidelining
    something unidentifiable would hide main-series work.
    """
    if identifier is None:
        return False
    return inventory_of(identifier) in SIDELINED_INVENTORIES


def is_main_series(identifier: str | None) -> bool:
    """True only when the identifier names one of 3185-3189. Unreadable ids are not main series."""
    if identifier is None:
        return False
    return inventory_of(identifier) in MAIN_SERIES


def split_main_series(frame: pd.DataFrame, column: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split on an inventory or id column. Returns (main_series, sidelined_or_other), both copies."""
    mask = frame[column].map(is_main_series)
    return frame.loc[mask].copy(), frame.loc[~mask].copy()


def drop_sidelined(items: Iterable[T], key) -> tuple[list[T], list[T]]:
    """Split any iterable by stated provenance. Returns (kept, sidelined).

    Call this where data ENTERS a script, exactly like `drop_out_of_scope`. `key(item)` must yield
    something that *states* the inventory -- a `session_id`, `flat_id`, `scan_id` or an explicit
    inventory field. **Never pass `candidate_inventory`**: it holds 3-4 guesses per date and
    filing by it is the tautology documented on `SIDELINED_INVENTORIES`.
    """
    kept: list[T] = []
    gone: list[T] = []
    for item in items:
        (gone if is_sidelined(key(item)) else kept).append(item)
    return kept, gone


def _sidelined_hits_in_value(value: Any, path: str) -> list[tuple[str, str]]:
    """Recurse into a record, testing only STRINGS, each parsed as an identifier.

    Never a substring match on a serialised form -- that is what let a first version of this
    guard "pass" with sidelined material still present: it serialised each row to JSON and
    searched for the literal text ``"4562"``, which matches inside `14562` (a character count)
    and `0.4562` (a probability) as readily as inside a real session id. A number cannot state an
    inventory, so only `str` values are ever tested, and each is tested through `is_sidelined` /
    `inventory_of` -- the same parser used everywhere else -- rather than text containment.
    """
    hits: list[tuple[str, str]] = []
    if isinstance(value, str):
        if is_sidelined(value):
            hits.append((path, value))
    elif isinstance(value, Mapping):
        for key, sub in value.items():
            hits.extend(_sidelined_hits_in_value(sub, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, (list, tuple)):
        for i, sub in enumerate(value):
            hits.extend(_sidelined_hits_in_value(sub, f"{path}[{i}]"))
    return hits


def assert_no_sidelined(
    records: pd.DataFrame | Iterable[Mapping[str, Any]], column: str | None = None
) -> None:
    """Fail loudly if sidelined material reached a result. The guard, not a second filter.

    Walks every record **recursively**, testing only string fields as identifiers -- see
    `_sidelined_hits_in_value` for why that is not optional. `column` narrows the walk to one
    field (the common case: a `session_id`/`inventory` column); omit it to sweep every field,
    which is what a dataset-level check over heterogeneous records needs.
    """
    if isinstance(records, pd.DataFrame):
        cols = [column] if column is not None else list(records.columns)
        rows: Iterable[Mapping[str, Any]] = (
            {c: row[c] for c in cols} for row in records.to_dict(orient="records")
        )
    else:
        rows = (
            ({column: row.get(column)} if column is not None else row)
            for row in records
        )

    hits: list[tuple[str, str]] = []
    for i, row in enumerate(rows):
        for path, value in _sidelined_hits_in_value(row, ""):
            hits.append((f"row {i}{'.' + path if path else ''}", value))
            if len(hits) >= 5:
                break
        if len(hits) >= 5:
            break

    if hits:
        detail = "; ".join(f"{path}={value!r}" for path, value in hits)
        raise AssertionError(
            f"sidelined material reached a result (showing up to 5): {detail}. The secret "
            f"series is sidelined from the sequence (user, 2026-10-08); drop it where data "
            f"enters the script, not here."
        )


@lru_cache(maxsize=1)
def sidelined_dates() -> frozenset[str]:
    """Enriched dates whose **resolved** session states a sidelined inventory.

    This is the only sound way to sideline on the edition side, because the enriched XML has no
    physical grounding at all -- `Stgen.dtd` has no folio, page, scan or inventory element -- so an
    enriched resolution has no inventory of its own. A *resolved* session is a fact and may be
    read; `candidate_inventory` is not and may not. Measured 2026-10-08: 34 dates, 398 `k_e`.

    The complement matters as much: the 344 dates with no resolved session (4,482 `k_e`) are
    **not** sidelined, because nothing states their inventory. They stay in the sequence as
    unplaced mass of unknown provenance.
    """
    from running_axis.axis import RunningAxis  # local: avoids a package import cycle

    axis = RunningAxis.load()
    return frozenset(
        state.date
        for state in axis.dates.values()
        if state.resolved_session_id and is_sidelined(state.resolved_session_id)
    )


@lru_cache(maxsize=1)
def suspicious_secret_dates() -> frozenset[str]:
    """Main-series dates the XML itself marks `secreet_resolutie`, flagged rather than sidelined.

    Decision (user, 2026-10-08): sideline by **ledger**, not by secrecy. A date whose resolved
    session states a main-series inventory (3185-3189) but whose enriched resolution carries the
    XML's own secret-resolution marker is a genuine cross-cut, measured at 73 of 100 XML-secret
    dates (18 are on the sidelined ledger 4562, 9 have no resolved session at all). It stays in
    the sequence -- its paper is demonstrably in the ordinary register -- but is marked suspicious
    so it is never silently indistinguishable from an unremarkable main-series date.
    """
    from running_axis.axis import RunningAxis  # local: avoids a package import cycle

    secret = {
        str(row["date"])[:10]
        for row in load("enriched_resolution_secret_flags")
        if isinstance(row, dict) and row.get("date") and row.get("secreet_resolutie")
    }
    axis = RunningAxis.load()
    return frozenset(
        state.date
        for state in axis.dates.values()
        if state.date in secret
        and state.resolved_session_id
        and is_main_series(state.resolved_session_id)
    )


def series_meta() -> dict[str, Any]:
    """The block a dataset should carry when it restricts to, or splits on, the main series."""
    return {
        "main_series": sorted(MAIN_SERIES),
        "sidelined_inventories": sorted(SIDELINED_INVENTORIES),
        "sidelining_rule": (
            "The secret series (4562/4861) is sidelined from the sequence, not down-weighted in "
            "it (user, 2026-10-08). Their anchors sit 700 days apart so any date-window test they "
            "enter succeeds trivially, and every unplaced date is filed under them by the "
            "candidate-inventory tautology, so a main-series n_e == 0 is that artefact and not a "
            "mapping result."
        ),
        "suspicious_secret_dates_count": len(suspicious_secret_dates()),
        "suspicious_secret_dates_rule": (
            "Sideline by LEDGER, not by secrecy (user, 2026-10-08). A main-series date carrying "
            "the XML's own secreet_resolutie marker is flagged suspicious, not sidelined -- its "
            "paper is demonstrably in the ordinary register. See suspicious_secret_dates()."
        ),
    }


if __name__ == "__main__":
    print(f"enriched baseline ends {enriched_end()}")
    print(SCOPE_RULE)
