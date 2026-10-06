"""`RunningAxis` -- the archival stream as one stateful object, queryable per time span.

What this replaces. `scripts/s6b_known_point_ledger.py` groups the paragraph axis by each
record's `date` field and skips any date with no records, filing it under a fabricated
inventory named `no_axis`. Corpus-wide that discards 535 enriched dates holding 5,590
resolutions -- of which **66 dates / 983 resolutions already have a session the concordance
resolved**, dropped only because that session's paragraphs carry a different date label.
`axis_for_date` (scripts/s4_corpus_paragraph_predictions.py) exists to prefer the resolved
session over calendar-date grouping; the ledger simply never calls it. So here a date is an
*attribute* of a session span, recorded under both attributions at once, and a date with no
label is still addressable.

Why a class. Placing and shifting anchors are mutations that have to keep the stream
monotone. Recomputed from files each time, nothing holds that invariant and every run
re-derives the sequence from dispersed sources -- which is how three different gap counts
came to be in circulation for one ledger (120 on disk from a one-month window, 947 cited in
PLAN.md from an earlier full run, and a third set that was fabricated). The model loads once
and every window is a *view* of that one state, so a month and a corpus figure are the same
object sliced twice and cannot contradict each other.

Every quantity it reports is a `running_axis.tally.Tally`, never a bare integer, so no number
leaves here without naming its population and its window.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Iterator, Mapping

from running_axis.stream import InventoryStream, build_streams
from running_axis.tally import (
    AXIS_CHARACTERS,
    AXIS_DATE_LABELS,
    AXIS_PARAGRAPHS,
    AXIS_SESSIONS,
    ENRICHED_DATES,
    ENRICHED_RESOLUTIONS,
    ENRICHED_WITH_AXIS_LABEL,
    ENRICHED_WITH_RESOLVED_SESSION,
    ENRICHED_WITHOUT_AXIS_LABEL,
    POPULATIONS,
    Tally,
    Window,
    check_partition,
)

# Attributions. The same date can be attached to a session two ways, and conflating them is
# the defect this model exists to remove.
AXIS_LABEL = "axis_label"
RESOLVED_SESSION = "resolved_session"

# Dates whose sitting consumes no HTR session, so their absence is not a gap. The rule is
# session_offset_eval.py's and is reused rather than restated.
NIHIL_STATUS = "nihil_actum"


class MonotonicityError(ValueError):
    """A mutation would put the stream out of archive order."""


@dataclass(frozen=True)
class SessionSpan:
    """One HTR session's extent on its inventory's coordinate, with every date claiming it."""

    session_id: str
    inventory: str
    session_num: int
    char_begin: int
    char_end: int
    paragraph_count: int
    label_dates: tuple[str, ...] = ()
    resolved_dates: tuple[str, ...] = ()

    @property
    def char_length(self) -> int:
        return self.char_end - self.char_begin

    @property
    def is_claimed(self) -> bool:
        return bool(self.resolved_dates)

    @property
    def is_shared(self) -> bool:
        """Claimed by more than one date -- an anchor carrying two days' business."""
        return len(self.resolved_dates) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "inventory": self.inventory,
            "session_num": self.session_num,
            "char_begin": self.char_begin,
            "char_end": self.char_end,
            "paragraph_count": self.paragraph_count,
            "label_dates": list(self.label_dates),
            "resolved_dates": list(self.resolved_dates),
        }


@dataclass(frozen=True)
class DateState:
    """One enriched date: what claims it has, and why it may have none.

    `candidate_inventory` is NOT where the text is. It comes from the concordance's
    `inventory_id`, which descends from `session_date_status_1626_1630` -- a table carrying
    **3 candidate inventories per date** (4 for 134 dates; 4,916 rows for 1,594 dates), one
    row per candidate. `s6b_known_point_ledger.inventory_of` warns about exactly this and
    reads the inventory off the flat id instead, "because picking one of those rows is
    arbitrary".

    The trap is worst on precisely the dates one most wants to locate. A `missing_htr` date
    has no resolved session by definition, so its candidate was never confirmed against any
    HTR -- and the candidates always include the main series while the surviving pick tends
    to be a secret inventory (1626-01-05: candidates 3185/4562/4861, pick 4861). Grouping
    unplaced dates by this field therefore "discovers" that dates without HTR belong to the
    inventories without HTR, which is a tautology. Use `inventory`, which is None unless a
    resolved session makes it a fact.
    """

    date: str
    k_e: int
    status: str
    candidate_inventory: str | None
    resolved_session_id: str | None
    has_axis_label: bool
    resolved_inventory: str | None = None

    @property
    def inventory(self) -> str | None:
        """The inventory the text is actually in, or None when nothing establishes it."""
        return self.resolved_inventory

    @property
    def is_nihil(self) -> bool:
        return self.status == NIHIL_STATUS

    @property
    def is_pinned(self) -> bool:
        return bool(self.resolved_session_id)

    @property
    def addressability(self) -> str:
        """Why this date is or is not locatable -- the closed taxonomy, one value per date.

        `dropped_by_label_grouping` is the ledger defect made visible: the date *is* pinned
        to a session, and only the grouping rule loses it -- 66 dates / 983 resolutions.

        `no_session` is the genuinely unplaced class, and what it is *not* took two withdrawn
        hypotheses to establish (docs/DECISIONS.md 2026-10-06). It is not displacement into
        unsegmented imaged pages: the 86 scans that looked orphaned all belong to the left
        bracketing session, because `metadata.page_ids` names only the page a resolution
        starts on. It is not under-transcription in this corpus' snapshot: the ES/axis
        character ratio is 0.99 median over 1,316 sessions. And it is not the secret series,
        however much grouping by `candidate_inventory` suggests otherwise -- see that field.
        Measured split of its 4,482 resolutions: 634 on XML-flagged secret dates, 313 present
        in ES and absent here, 3,535 absent upstream as well.
        """
        if self.has_axis_label:
            return "labelled"
        if self.is_pinned:
            return "dropped_by_label_grouping"
        if self.is_nihil:
            return "nihil_actum"
        return "no_session"


# Closed, and the closure is the point: a date that fits none of these is a signal that the
# taxonomy is incomplete, not that the date is unimportant.
ADDRESSABILITY = ("labelled", "dropped_by_label_grouping", "nihil_actum", "no_session")

for _name, _definition in {
    "labelled": "Enriched dates at least one axis paragraph labels with that date.",
    "dropped_by_label_grouping": (
        "Enriched dates with a concordance-resolved session whose paragraphs carry a "
        "different date label. Locatable, and discarded only by grouping on the label."
    ),
    "nihil_actum": "Enriched dates whose sitting consumes no HTR session; absence is correct.",
    "no_session": (
        "Enriched dates with neither an axis label nor a resolved session: 344 dates / 4,482 "
        "resolutions corpus-wide. Measured 2026-10-06, and NOT the secret series despite how "
        "it looks when grouped by candidate_inventory: of the 323 XML-flagged secret dates "
        "(enriched_resolution_secret_flags) 264 are labelled, i.e. placed with HTR, so secrecy "
        "does not imply missing text. Setting the flagged dates aside leaves 298 dates / 3,848 "
        "resolutions, which split against the ES full_resolutions index on "
        "metadata.session_date into 26 dates / 313 resolutions ES holds and this corpus does "
        "not (recoverable) and 272 dates / 3,535 resolutions absent upstream too. So 4,482 = "
        "634 secret + 313 recoverable + 3,535 absent everywhere. None of these dates has an "
        "authoritative inventory, by construction: an unplaced date has no session to read one "
        "off."
    ),
}.items():
    POPULATIONS.register(
        f"dates_{_name}",
        "dates",
        _definition,
        attribution=AXIS_LABEL if _name in {"labelled", "dropped_by_label_grouping"} else "n/a",
        subset_of="enriched_dates",
    )
    POPULATIONS.register(
        f"resolutions_{_name}",
        "resolutions",
        _definition.replace("Enriched dates", "Enriched resolutions on dates"),
        subset_of="enriched_resolutions",
    )


class RunningAxis:
    """The whole stream plus every date's claim on it. Load once; take views."""

    def __init__(
        self,
        streams: Mapping[str, InventoryStream],
        sessions: Mapping[str, SessionSpan],
        dates: Mapping[str, DateState],
    ) -> None:
        self.streams = dict(streams)
        self.sessions = dict(sessions)
        self.dates = dict(dates)

    # --- construction ------------------------------------------------------------------

    @classmethod
    def load(cls, axis_path: str | None = None) -> "RunningAxis":
        from data_io import load as load_dataset

        streams = build_streams(axis_path)

        label_dates: dict[str, set[str]] = {}
        spans: dict[str, tuple[str, int, int, int, int]] = {}
        for inventory, stream in streams.items():
            counts: dict[str, int] = {}
            for ref in stream:
                counts[ref.session_id] = counts.get(ref.session_id, 0) + 1
                if ref.date_label:
                    label_dates.setdefault(ref.session_id, set()).add(ref.date_label)
            for session_id, (begin, end) in stream.sessions().items():
                num = int(session_id.rsplit("-num-", 1)[1])
                spans[session_id] = (inventory, num, begin, end, counts[session_id])

        concordance = load_dataset("resolution_concordance_1626_1630")
        per_date = (
            concordance.groupby("enriched_date")
            .agg(
                k_e=("enriched_id", "size"),
                status=("status", "first"),
                inventory_id=("inventory_id", "first"),
                resolved_session_id=("resolved_session_id", "first"),
            )
            .reset_index()
        )

        resolved_dates: dict[str, set[str]] = {}
        dates: dict[str, DateState] = {}
        labelled_dates = {date for value in label_dates.values() for date in value}
        for row in per_date.itertuples(index=False):
            date = str(row.enriched_date)
            session_id = (
                str(row.resolved_session_id)
                if row.resolved_session_id and str(row.resolved_session_id) != "nan"
                else None
            )
            if session_id:
                resolved_dates.setdefault(session_id, set()).add(date)
            dates[date] = DateState(
                date=date,
                k_e=int(row.k_e),
                status=str(row.status),
                candidate_inventory=(
                    None if row.inventory_id is None else str(row.inventory_id)
                ),
                resolved_session_id=session_id,
                has_axis_label=date in labelled_dates,
                # Authoritative only via the session's flat id; filled in below once the
                # session spans exist.
                resolved_inventory=None,
            )

        sessions = {
            session_id: SessionSpan(
                session_id=session_id,
                inventory=inventory,
                session_num=num,
                char_begin=begin,
                char_end=end,
                paragraph_count=count,
                label_dates=tuple(sorted(label_dates.get(session_id, ()))),
                resolved_dates=tuple(sorted(resolved_dates.get(session_id, ()))),
            )
            for session_id, (inventory, num, begin, end, count) in spans.items()
        }
        # Now that session spans exist, the pinned dates can carry a real inventory.
        for date, state in list(dates.items()):
            if state.resolved_session_id and state.resolved_session_id in sessions:
                dates[date] = replace(
                    state,
                    resolved_inventory=sessions[state.resolved_session_id].inventory,
                )
        return cls(streams, sessions, dates)

    # --- coverage and views ------------------------------------------------------------

    @property
    def coverage(self) -> Window:
        """The span this model actually holds. Not the same as 'unspecified'."""
        known = sorted(self.dates) + [
            date for session in self.sessions.values() for date in session.label_dates
        ]
        if not known:
            raise ValueError("an empty RunningAxis has no coverage")
        return Window.of(min(known), max(known))

    def covers(self, start: str, end: str) -> bool:
        window = self.coverage
        return window.start <= start and end <= window.end

    def view(self, start: str, end: str) -> "RunningAxisView":
        """State restricted to a span. Raises outside coverage rather than returning zeros."""
        if end < start:
            raise ValueError(f"window runs backwards: {start}..{end}")
        if not self.covers(start, end):
            raise KeyError(
                f"{start}..{end} is outside this model's coverage ({self.coverage}). "
                "An uncovered span means no data is held here, which is not the same as "
                "nothing being there."
            )
        return RunningAxisView(self, Window.of(start, end))

    state_for = view

    # --- mutations ---------------------------------------------------------------------

    def place_anchor(self, date: str, session_id: str) -> None:
        """Pin a date to a session (step 3a). Refuses to break archive order."""
        if date not in self.dates:
            raise KeyError(f"unknown enriched date {date!r}")
        if session_id not in self.sessions:
            raise KeyError(f"unknown session {session_id!r}")
        self._check_monotone(date, session_id)
        state = self.dates[date]
        self.dates[date] = replace(
            state,
            resolved_session_id=session_id,
            resolved_inventory=self.sessions[session_id].inventory,
        )
        session = self.sessions[session_id]
        self.sessions[session_id] = SessionSpan(
            **{
                **session.to_dict(),
                "label_dates": session.label_dates,
                "resolved_dates": tuple(sorted(set(session.resolved_dates) | {date})),
            }
        )

    def shift_anchor(self, date: str, to_session_id: str) -> None:
        """Move a date's pin to another session (step 3b)."""
        state = self.dates.get(date)
        if state is None:
            raise KeyError(f"unknown enriched date {date!r}")
        previous = state.resolved_session_id
        if previous:
            old = self.sessions[previous]
            self.sessions[previous] = SessionSpan(
                **{
                    **old.to_dict(),
                    "label_dates": old.label_dates,
                    "resolved_dates": tuple(d for d in old.resolved_dates if d != date),
                }
            )
        try:
            self.place_anchor(date, to_session_id)
        except MonotonicityError:
            if previous:  # put it back rather than leave the model half-moved
                self.place_anchor(date, previous)
            raise

    def _check_monotone(self, date: str, session_id: str) -> None:
        """Dates pinned inside one inventory must run in the same order as its sessions."""
        target = self.sessions[session_id]
        for other_date, state in self.dates.items():
            if other_date == date or not state.resolved_session_id:
                continue
            other = self.sessions.get(state.resolved_session_id)
            if other is None or other.inventory != target.inventory:
                continue
            if other.session_id == target.session_id:
                continue  # a shared session is legitimate, not an inversion
            if (other_date < date) != (other.session_num < target.session_num):
                raise MonotonicityError(
                    f"pinning {date} to {session_id} (num {target.session_num}) inverts "
                    f"{other_date} at {other.session_id} (num {other.session_num}) in "
                    f"inventory {target.inventory}"
                )

    # --- serialisation -----------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """State as records, so a run's numbers are answerable from the artifact."""
        window = self.coverage
        # Every figure here spans the model's whole coverage, so it is nested under a key
        # that says so. A window-scoped count belongs in the report, never beside these.
        meta = {
            "record_type": "meta",
            "model": "running_axis",
            "coverage": {"start": window.start, "end": window.end},
            "coverage_totals": {
                "inventories": sorted(self.streams),
                "paragraphs": sum(len(s) for s in self.streams.values()),
                "characters": sum(s.char_length for s in self.streams.values()),
                "sessions": len(self.sessions),
                "enriched_dates": len(self.dates),
            },
        }
        return [
            meta,
            *(
                {"record_type": "session", **session.to_dict()}
                for session in sorted(self.sessions.values(), key=lambda s: (s.inventory, s.session_num))
            ),
            *(
                {
                    "record_type": "date",
                    "date": state.date,
                    "k_e": state.k_e,
                    "status": state.status,
                    "inventory": state.inventory,
                    "candidate_inventory": state.candidate_inventory,
                    "resolved_session_id": state.resolved_session_id,
                    "has_axis_label": state.has_axis_label,
                    "addressability": state.addressability,
                }
                for state in sorted(self.dates.values(), key=lambda d: d.date)
            ),
        ]


class RunningAxisView:
    """One window's slice of a `RunningAxis`. Reports tallies that name that window."""

    def __init__(self, axis: RunningAxis, window: Window) -> None:
        self.axis = axis
        self.window = window

    def _in_window(self, date: str) -> bool:
        return any(start <= date <= end for start, end in self.window.spans)

    @property
    def dates(self) -> list[DateState]:
        return [state for date, state in sorted(self.axis.dates.items()) if self._in_window(date)]

    @property
    def sessions(self) -> list[SessionSpan]:
        """Sessions a date in this window claims, or whose own label falls in it."""
        wanted = set()
        for state in self.dates:
            if state.resolved_session_id:
                wanted.add(state.resolved_session_id)
        for session in self.axis.sessions.values():
            if any(self._in_window(date) for date in session.label_dates):
                wanted.add(session.session_id)
        return [self.axis.sessions[s] for s in sorted(wanted)]

    def tally(self, population_name: str, value: int) -> Tally:
        return Tally(POPULATIONS.get(population_name), self.window, value)

    def report(self) -> dict[str, Tally]:
        """Every figure as a tally, with the addressability partition machine-checked."""
        dates = self.dates
        by_class = {name: [d for d in dates if d.addressability == name] for name in ADDRESSABILITY}

        out: dict[str, Tally] = {
            "enriched_dates": self.tally("enriched_dates", len(dates)),
            "enriched_resolutions": self.tally(
                "enriched_resolutions", sum(d.k_e for d in dates)
            ),
            # Window-scoped, not the corpus total: a reader comparing this against a
            # coverage-wide session count must see which is which.
            "axis_sessions": self.tally("axis_sessions", len(self.sessions)),
        }
        for name, members in by_class.items():
            out[f"dates_{name}"] = self.tally(f"dates_{name}", len(members))
            out[f"resolutions_{name}"] = self.tally(
                f"resolutions_{name}", sum(d.k_e for d in members)
            )

        # If these ever stop adding up, that is a defect and not a rounding note.
        check_partition(
            out["enriched_dates"], [out[f"dates_{name}"] for name in ADDRESSABILITY]
        )
        check_partition(
            out["enriched_resolutions"],
            [out[f"resolutions_{name}"] for name in ADDRESSABILITY],
        )
        return out

    def __repr__(self) -> str:
        return f"<RunningAxisView {self.window} dates={len(self.dates)}>"
