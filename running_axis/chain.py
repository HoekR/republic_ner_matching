"""Gap accounting and session brackets over `RunningAxis` state.

Two structures that are easy to conflate and are not the same thing:

* **Gaps** (`s6b_known_point_ledger`) are *resolution-level, within a day*. Between two
  consecutive known points on one day's chain, `right.enriched_index - left.enriched_index
  - 1` resolutions must fall. A gap of 0 is already determined, 1-2 nearly so, >=3 open.
* **Brackets** (`scripts/session_offset_eval.py`) are *session-level, within an inventory*.
  Between two consecutive resolved pins, some number of unresolved sittings (`n_e`) compete
  for some number of unclaimed sessions (`n_h`), and `n_e == n_h` forces the pairing by
  monotonicity alone.

Both semantics are lifted from those scripts rather than restated, so the model's accounting
can be checked against theirs digit for digit. The one deliberate difference is the output:
every total here is a `Tally`, so no figure escapes without naming its population and window
-- which is what let three different gap counts circulate for one ledger.

Gaps are computed from a chain the caller supplies. The model does not re-derive production
anchors: `s6b_known_point_ledger` computes those live per day through `align_session`, and
duplicating that here would be a second implementation of the thing whose numbers we want to
reproduce. Feeding it the ledger's own chain is the stronger check anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from running_axis.tally import POPULATIONS, Tally, Window

# `scripts/s6b_known_point_ledger.py:84`
NEARLY_DETERMINED = 2
BUCKETS = ("determined", "nearly_determined", "open")

# `scripts/session_offset_eval.py` bracket classes, in its own precedence order.
BRACKET_CLASSES = (
    "non_monotone",
    "tight",
    "surplus_no_sitting",
    "outside_enriched_span",
    "deficit_no_session",
    "determined",
    "deficit",
    "surplus",
)

for _bucket, _definition in {
    "determined": "Gaps between known points holding 0 unplaced resolutions; already settled.",
    "nearly_determined": (
        "Gaps holding 1-2 unplaced resolutions, pinned almost completely by their endpoints "
        "plus counting."
    ),
    "open": "Gaps holding 3 or more unplaced resolutions; where the real work is.",
}.items():
    POPULATIONS.register(f"gaps_{_bucket}", "gaps", _definition)
    POPULATIONS.register(
        f"gap_resolutions_{_bucket}",
        "resolutions",
        _definition.replace("Gaps", "Resolutions in gaps"),
    )
    POPULATIONS.register(
        f"gap_chars_{_bucket}", "chars", _definition.replace("Gaps", "Characters spanned by gaps")
    )
POPULATIONS.register("gaps_total", "gaps", "All gaps between consecutive known points.")


def bucket_of(resolutions_in_gap: int) -> str:
    """Name a gap's difficulty class. `s6b_known_point_ledger.bucket_of`, unchanged."""
    if resolutions_in_gap == 0:
        return "determined"
    return "nearly_determined" if resolutions_in_gap <= NEARLY_DETERMINED else "open"


@dataclass(frozen=True)
class KnownPoint:
    """A position on one day's chain that something already pins."""

    enriched_index: int
    char_position: int
    kinds: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "KnownPoint":
        return cls(
            enriched_index=int(row["enriched_index"]),
            char_position=int(row["char_position"]),
            kinds=tuple(row.get("kinds") or ()),
        )


@dataclass(frozen=True)
class Gap:
    """One interval between consecutive known points, and what must fall inside it."""

    left: KnownPoint
    right: KnownPoint

    @property
    def resolutions_in_gap(self) -> int:
        return self.right.enriched_index - self.left.enriched_index - 1

    @property
    def char_span(self) -> int:
        return self.right.char_position - self.left.char_position

    @property
    def bucket(self) -> str:
        return bucket_of(self.resolutions_in_gap)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_kinds": list(self.left.kinds),
            "right_kinds": list(self.right.kinds),
            "left_enriched_index": self.left.enriched_index,
            "right_enriched_index": self.right.enriched_index,
            "resolutions_in_gap": self.resolutions_in_gap,
            "char_span": self.char_span,
        }


def gaps_from_chain(chain: Sequence[KnownPoint | Mapping[str, Any]]) -> list[Gap]:
    """One gap per adjacent pair, in chain order. `gaps_of` semantics."""
    points = [p if isinstance(p, KnownPoint) else KnownPoint.from_dict(p) for p in chain]
    return [Gap(left, right) for left, right in zip(points, points[1:])]


class GapLedger:
    """Gap buckets over any set of days, reported as tallies.

    Mirrors `s6b_known_point_ledger.aggregate`'s deliberate choice to report gap counts
    **and** resolution-weighted counts side by side, and to emit both disagreeing shares
    together: a gap of size 0 contributes a row but no work, so `settled_share_by_gap` reads
    far more favourably than `open_share_by_resolution` and neither may be quoted alone.
    """

    def __init__(self, window: Window) -> None:
        self.window = window
        self._gaps: list[Gap] = []

    def add_day(self, chain: Sequence[KnownPoint | Mapping[str, Any]]) -> None:
        self._gaps.extend(gaps_from_chain(chain))

    @property
    def gaps(self) -> list[Gap]:
        return list(self._gaps)

    def _tally(self, population: str, value: int) -> Tally:
        return Tally(POPULATIONS.get(population), self.window, value)

    def report(self) -> dict[str, Tally]:
        out = {"gaps_total": self._tally("gaps_total", len(self._gaps))}
        for bucket in BUCKETS:
            members = [g for g in self._gaps if g.bucket == bucket]
            out[f"gaps_{bucket}"] = self._tally(f"gaps_{bucket}", len(members))
            out[f"gap_resolutions_{bucket}"] = self._tally(
                f"gap_resolutions_{bucket}", sum(g.resolutions_in_gap for g in members)
            )
            out[f"gap_chars_{bucket}"] = self._tally(
                f"gap_chars_{bucket}", sum(g.char_span for g in members)
            )
        return out

    def shares(self) -> dict[str, float]:
        """The two shares that disagree, always returned together."""
        report = self.report()
        total_gaps = report["gaps_total"].value
        settled = report["gaps_determined"].value + report["gaps_nearly_determined"].value
        unplaced = sum(report[f"gap_resolutions_{b}"].value for b in BUCKETS)
        return {
            "settled_share_by_gap": settled / total_gaps if total_gaps else 0.0,
            "open_share_by_resolution": (
                report["gap_resolutions_open"].value / unplaced if unplaced else 0.0
            ),
        }


@dataclass(frozen=True)
class Bracket:
    """An interval between two resolved pins in one inventory's session order.

    `n_e` unresolved sittings compete for `n_h` unclaimed sessions. `session_offset_eval`'s
    classes and precedence, including its two caveats: a bracket whose pins run backwards is
    `non_monotone` and takes no classification, because forcing a pairing across an inverted
    pin would invent an ordering the data does not support; and a head/tail surplus is
    `outside_enriched_span` rather than evidence of an unmatched session, since the enriched
    edition stops at 1630-05-14 while the axis runs to 1630-12-31.
    """

    inventory: str
    kind: str
    bracket_class: str
    left_pin_date: str | None
    right_pin_date: str | None
    unresolved_dates: tuple[str, ...]
    unclaimed_sessions: tuple[str, ...]
    unresolved_k_e: int
    rests_on_candidate_inventory: bool = False
    """True when any unresolved date in this bracket was grouped by its *candidate*
    inventory rather than a confirmed one. An unresolved sitting has no resolved session, so
    nothing establishes which inventory its text is in; the concordance's `inventory_id`
    descends from a table holding 3-4 candidates per date. `session_offset_eval` groups this
    way too, so the flag marks a shared limitation rather than a divergence -- but a bracket
    carrying it cannot support a claim about *where* its unplaced resolutions are."""

    @property
    def n_e(self) -> int:
        return len(self.unresolved_dates)

    @property
    def n_h(self) -> int:
        return len(self.unclaimed_sessions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "bracket",
            "inventory": self.inventory,
            "kind": self.kind,
            "bracket_class": self.bracket_class,
            "left_pin_date": self.left_pin_date,
            "right_pin_date": self.right_pin_date,
            "n_unresolved_sittings": self.n_e,
            "n_unclaimed_sessions": self.n_h,
            "unresolved_k_e": self.unresolved_k_e,
            "unresolved_dates": list(self.unresolved_dates),
            "unclaimed_sessions": list(self.unclaimed_sessions),
            "rests_on_candidate_inventory": self.rests_on_candidate_inventory,
        }


def _classify(kind: str, n_e: int, n_h: int, non_monotone: bool) -> str:
    """`session_offset_eval.build_brackets`'s precedence, lifted unchanged."""
    if non_monotone:
        return "non_monotone"
    if n_e == 0 and n_h == 0:
        return "tight"
    if n_e == 0:
        return "surplus_no_sitting" if kind == "interior" else "outside_enriched_span"
    if n_h == 0:
        return "deficit_no_session"
    if n_e == n_h:
        return "determined"
    return "deficit" if n_e > n_h else "surplus"


def build_brackets(axis: Any, *, nihil_status: str = "nihil_actum") -> list[Bracket]:
    """Brackets per inventory from a `RunningAxis`'s pins and sessions.

    Nihil-actum dates are dropped before ranking, which is the hard skip constraint: a nihil
    sitting consumes no HTR session, so counting it would shift every later position by one.
    """
    brackets: list[Bracket] = []
    counted: set[str] = set()

    by_inventory: dict[str, list[Any]] = {}
    on_candidate: set[str] = set()
    for state in axis.dates.values():
        if state.status == nihil_status:
            continue
        # A pinned date's inventory is a fact, read off its session's flat id. An unpinned
        # one has only a candidate, and grouping by it is what makes "the unplaced mass is
        # in the secret inventories" a tautology rather than a finding -- the candidates
        # always include the main series, and the surviving pick tends to be a secret
        # inventory precisely because those are the ones with little HTR.
        inventory = state.inventory
        if inventory is None:
            inventory = state.candidate_inventory
            if inventory is not None:
                on_candidate.add(state.date)
        if inventory is None:
            continue
        by_inventory.setdefault(str(inventory), []).append(state)

    sessions_by_inventory: dict[str, list[Any]] = {}
    for session in axis.sessions.values():
        sessions_by_inventory.setdefault(session.inventory, []).append(session)

    for inventory, states in sorted(by_inventory.items()):
        rows = sorted(states, key=lambda s: s.date)
        sessions = sorted(
            sessions_by_inventory.get(inventory, []), key=lambda s: s.session_num
        )
        claimed = {s.resolved_session_id for s in rows if s.resolved_session_id}
        ordinal = {s.session_id: i for i, s in enumerate(sessions)}

        pins = [i for i, row in enumerate(rows) if row.resolved_session_id]
        edges: list[tuple[int | None, int | None]] = []
        if not pins:
            edges.append((None, None))
        else:
            edges.append((None, pins[0]))
            edges.extend(zip(pins, pins[1:]))
            edges.append((pins[-1], None))

        for left, right in edges:
            left_row = rows[left] if left is not None else None
            right_row = rows[right] if right is not None else None
            left_ord = ordinal.get(left_row.resolved_session_id) if left_row else None
            right_ord = ordinal.get(right_row.resolved_session_id) if right_row else None

            inner = rows[(left + 1) if left is not None else 0 : right if right is not None else len(rows)]
            unresolved = [row for row in inner if not row.resolved_session_id]

            low = -1 if left_ord is None else left_ord
            high = len(sessions) if right_ord is None else right_ord
            non_monotone = (
                left_ord is not None and right_ord is not None and right_ord < left_ord
            )
            free = (
                []
                if non_monotone
                else [
                    s
                    for s in sessions
                    if low < ordinal[s.session_id] < high
                    and s.session_id not in claimed
                    and s.session_id not in counted
                ]
            )
            counted.update(s.session_id for s in free)

            kind = (
                "interior"
                if left is not None and right is not None
                else "head"
                if left is None and right is not None
                else "tail"
                if right is None and left is not None
                else "whole_inventory"
            )
            brackets.append(
                Bracket(
                    inventory=inventory,
                    kind=kind,
                    bracket_class=_classify(kind, len(unresolved), len(free), non_monotone),
                    left_pin_date=left_row.date if left_row else None,
                    right_pin_date=right_row.date if right_row else None,
                    unresolved_dates=tuple(row.date for row in unresolved),
                    unclaimed_sessions=tuple(s.session_id for s in free),
                    unresolved_k_e=sum(row.k_e for row in unresolved),
                    rests_on_candidate_inventory=any(
                        row.date in on_candidate for row in unresolved
                    ),
                )
            )
    return brackets
