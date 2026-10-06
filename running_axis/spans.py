"""Typed spans over a continuous coordinate, with gaps as first-class objects.

Design borrowed from REPUBLIC's ``republic_attendancelist_models.MatchedText``
(``republicgit``, module ``republic/model/republic_attendancelist_models.py``): a continuous
text carries a list of typed fragments, and ``get_fragments()`` returns the text partitioned
into those fragments *plus explicit ``unmarked`` fragments for everything in between*. That
one property -- the partition is gapless, so an unexplained stretch is an object rather than
an absence -- is why this module exists. ``scripts/s6b_known_point_ledger.py`` currently drops
a day with no dated paragraph via a bare ``continue`` and files it under a fabricated
inventory named ``no_axis``; a representation that cannot express a hole cannot do that.

Reimplemented rather than copied, for the same reason as ``scripts/_republic_date_vocab.py``
and ``scripts/_republic_resolution_phrase_vocab.py``: ``republic-project`` pins
``python = "^3.8,<3.12"`` and ``fuzzy-search = "^2.6.0"`` against this project's 3.12.13 and
fuzzy_search 3.0.3, so it cannot be a dependency. The reimplementation also fixes defects in
the original that bear directly on the gapless property; each has a regression test in
``tests/test_running_axis_spans.py`` and is cited here so the divergence is deliberate and
auditable:

1. ``get_fragments()``'s trailing fragment sliced ``txt[end:begin]`` where ``begin`` is the
   *last span's* begin and so is ``<= end`` -- a reversed slice, yielding an empty ``pattern``
   while ``begin``/``end`` claimed a real range. Here the tail runs to ``length``.
2. It guarded gaps with ``if end < i.begin - 1``, which **drops a 1-character gap entirely**.
   Fatal for this representation. Here the guard is ``span.begin > cursor``.
3. Unmarked fragments recorded ``'begin': begin - 1`` while their text covered
   ``[end, i.begin)`` -- off by one against typed fragments. Here both use exact bounds.
4. ``set_span()`` appended the new span once *per* overlapping neighbour, duplicating it when
   it overlapped several. Here insertion happens exactly once.
5. ``set_span()`` tested ``set(range(cs.begin, cs.end)).issubset(span)`` with ``span`` a
   2-tuple, so containment was tested against the two endpoint *values* rather than the range
   and effectively never fired. Overlap policy here is explicit and tested.
6. ``TypedFragment.__init__`` hardcoded ``self.idnr = 0``, discarding the id it was passed, so
   ``get_span(idnr)`` could only ever retrieve id 0. Here ids round-trip.
7. ``nw_id = itertools.count()`` was class-level and process-local, so ids were unstable
   across runs -- unusable in a persisted snapshot. Here ids are derived from
   ``(type, begin, end)`` and are stable across loads.
9. ``TypedFragment.__lt__`` compared ``self.begin < other`` (int against object) and worked
   only via the reflected ``__gt__``. Here ordering is explicit.

(Defects 8 and 10 are in the delegate/colour code, which has no analogue here.)

Text is deliberately *not* held. Spans carry coordinates only; the text store is layered on
top (``running_axis.stream``), because gap arithmetic, bracket counting and monotonicity
checks need offsets alone -- 21,519 paragraphs of coordinate against 12.9 MB of text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Mapping

UNMARKED = "unmarked"

OverlapPolicy = Literal["raise", "replace", "keep"]


class OverlapError(ValueError):
    """An insertion would overlap existing spans in the same layer under policy ``raise``."""

    def __init__(self, new: tuple[int, int], conflicts: list["Span"]) -> None:
        detail = ", ".join(f"{s.span_id} [{s.begin},{s.end})" for s in conflicts)
        super().__init__(f"span [{new[0]},{new[1]}) overlaps: {detail}")
        self.conflicts = conflicts


@dataclass(frozen=True)
class Span:
    """A typed half-open interval ``[begin, end)`` on a layer's coordinate.

    ``span_id`` is derived from ``(type, begin, end)`` rather than a counter, so two loads of
    the same state produce the same ids and a snapshot is comparable across runs (defect 7).
    """

    begin: int
    end: int
    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.begin < 0 or self.end < self.begin:
            raise ValueError(f"invalid span bounds: [{self.begin},{self.end})")

    @property
    def span_id(self) -> str:
        return f"{self.type}:{self.begin}-{self.end}"

    @property
    def length(self) -> int:
        return self.end - self.begin

    def sort_key(self) -> tuple[int, int, str]:
        return (self.begin, self.end, self.type)

    def overlaps(self, begin: int, end: int) -> bool:
        """True when the half-open ranges intersect in at least one position.

        Zero-length spans (point anchors) touch nothing: a point at ``p`` does not intersect
        ``[p, p+1)`` for this purpose, so anchors can sit on a boundary without evicting the
        span they bound.
        """
        if self.length == 0 or end == begin:
            return False
        return self.begin < end and begin < self.end

    def contains(self, other: "Span") -> bool:
        return self.begin <= other.begin and other.end <= self.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "begin": self.begin,
            "end": self.end,
            "type": self.type,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "Span":
        return cls(
            begin=int(row["begin"]),
            end=int(row["end"]),
            type=str(row["type"]),
            payload=dict(row.get("payload") or {}),
        )


@dataclass(frozen=True)
class Fragment:
    """One tile of a layer's gapless partition. ``span_id`` is None for an unmarked gap."""

    begin: int
    end: int
    type: str
    span_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return self.end - self.begin

    @property
    def is_unmarked(self) -> bool:
        return self.type == UNMARKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "begin": self.begin,
            "end": self.end,
            "type": self.type,
            "span_id": self.span_id,
            "payload": dict(self.payload),
        }


class SpanLayer:
    """Non-overlapping typed spans over ``[0, length)``, partitioning it without holes.

    One layer per kind of claim, because the domain nests: a ``session`` layer's spans contain
    a ``resolution`` layer's spans contain an ``anchor`` layer's points. Enforcing
    non-overlap *within* a layer and saying nothing across layers is what lets the nesting be
    expressed without a flat no-overlap rule that the data would immediately violate.
    """

    def __init__(self, name: str, length: int) -> None:
        if length < 0:
            raise ValueError(f"negative layer length: {length}")
        self.name = name
        self.length = length
        self._spans: dict[str, Span] = {}

    def __len__(self) -> int:
        return len(self._spans)

    def __iter__(self) -> Iterator[Span]:
        return iter(self.sorted_spans())

    def sorted_spans(self) -> list[Span]:
        return sorted(self._spans.values(), key=Span.sort_key)

    def get(self, span_id: str) -> Span:
        try:
            return self._spans[span_id]
        except KeyError as exc:
            raise KeyError(f"no span {span_id!r} in layer {self.name!r}") from exc

    def conflicts(self, begin: int, end: int) -> list[Span]:
        return [span for span in self.sorted_spans() if span.overlaps(begin, end)]

    def add(
        self,
        begin: int,
        end: int,
        type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        on_overlap: OverlapPolicy = "raise",
    ) -> str:
        """Insert a span and return its id. Inserted exactly once (defect 4).

        ``on_overlap`` is explicit rather than inferred, because the original's containment
        test never fired and so its intent was unrecoverable (defect 5):

        * ``raise``   -- refuse, listing the conflicts. The default: a placement that collides
          is a finding, not something to resolve silently.
        * ``replace`` -- evict every overlapping span, then insert.
        * ``keep``    -- leave the existing spans alone and return the first conflict's id.
        """
        if end > self.length:
            raise ValueError(f"span [{begin},{end}) exceeds layer length {self.length}")
        span = Span(begin=begin, end=end, type=type, payload=dict(payload or {}))
        existing = self.conflicts(begin, end)
        if existing:
            if on_overlap == "raise":
                raise OverlapError((begin, end), existing)
            if on_overlap == "keep":
                return existing[0].span_id
            for conflict in existing:
                del self._spans[conflict.span_id]
        self._spans[span.span_id] = span
        return span.span_id

    def remove(self, span_id: str) -> Span:
        span = self.get(span_id)
        del self._spans[span_id]
        return span

    def fragments(self) -> list[Fragment]:
        """The layer as a gapless, non-overlapping tiling of ``[0, length)``.

        Every position is covered exactly once: typed spans where they sit, ``unmarked``
        fragments everywhere else. This is the whole point of the module -- see defects 1-3.
        """
        out: list[Fragment] = []
        cursor = 0
        for span in self.sorted_spans():
            if span.begin > cursor:
                out.append(Fragment(cursor, span.begin, UNMARKED))
            out.append(
                Fragment(span.begin, span.end, span.type, span.span_id, dict(span.payload))
            )
            cursor = max(cursor, span.end)
        if cursor < self.length:
            out.append(Fragment(cursor, self.length, UNMARKED))
        return out

    def unmarked(self) -> list[Fragment]:
        """The gaps alone -- what this layer still does not explain."""
        return [fragment for fragment in self.fragments() if fragment.is_unmarked]

    def unmarked_length(self) -> int:
        return sum(fragment.length for fragment in self.unmarked())

    def types(self) -> dict[str, int]:
        """Span counts by type, enumerated from state rather than declared up front."""
        counts: dict[str, int] = {}
        for span in self._spans.values():
            counts[span.type] = counts.get(span.type, 0) + 1
        return counts

    def clipped_to(self, begin: int, end: int) -> "SpanLayer":
        """A view of this layer restricted to ``[begin, end)``, with straddling spans clipped.

        Clipping *narrows*, following the convention the hard-period annotation already set
        (``date_start``/``date_end`` slots clip paragraphs outside the bracket --
        ``docs/DECISIONS.md`` 2026-10-05). Each clipped span records
        ``payload["clipped"] = True`` plus its original bounds, so a window's counts can
        always be split into fully-inside against clipped-at-edge and are never silently
        inflated or deflated by the window's own boundaries.
        """
        if begin < 0 or end > self.length or end < begin:
            raise ValueError(f"clip range [{begin},{end}) outside layer [0,{self.length})")
        view = SpanLayer(self.name, end - begin)
        for span in self.sorted_spans():
            lo, hi = max(span.begin, begin), min(span.end, end)
            if hi <= lo and not (span.length == 0 and begin <= span.begin < end):
                continue
            payload = dict(span.payload)
            clipped = span.begin < begin or span.end > end
            if clipped:
                payload["clipped"] = True
                payload["original_begin"] = span.begin
                payload["original_end"] = span.end
            view.add(lo - begin, hi - begin, span.type, payload, on_overlap="replace")
        return view

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "length": self.length,
            "spans": [span.to_dict() for span in self.sorted_spans()],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpanLayer":
        layer = cls(str(data["layer"]), int(data["length"]))
        for row in data.get("spans") or []:
            span = Span.from_dict(row)
            layer._spans[span.span_id] = span
        return layer
