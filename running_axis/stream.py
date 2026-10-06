"""The running axis: one continuous coordinate per inventory, with text loaded lazily.

Why this exists. `scripts/s6b_known_point_ledger.py` groups the paragraph axis by each
record's `date` field and skips any date with no records
(`day_stats.append({... "inventory": "no_axis", "no_axis": True}); continue`). For
October 1628 that discards 16 of 31 days and files them under an inventory named `no_axis`,
although inventory 3187's register runs continuously through them -- session numbers 1..305
with only 30 absent from the axis. A day "without an axis" only means no paragraph carries
that date *label*; the archival stream has no hole there.

So the coordinate here is the inventory, ordered by `(session_num, resolution_num,
para_index)` parsed out of `flat_id` (`session-3187-num-114-resolution-1`), and the date is
an attribute of a span rather than the partition key. `char_start` accumulates across the
whole inventory instead of restarting per day the way
`scripts.s6a_char_axis_evaluation.char_starts` does -- that function stays as it is, for the
day-sliced callers that depend on it.

Lazy text, and why not a derived text file. Measured on this corpus: 21,519 paragraph
records of coordinate against 12,929,911 characters of text (2.2-2.9 MB per inventory). Gap
arithmetic, bracket counting and monotonicity checks never touch the text. The plan had
considered writing one concatenated `.txt` per inventory and mmap-ing it, which would make
`char_start` a physical file offset, but that is a second copy of the text that can drift
from its source -- and dispersed, silently-diverging derivations are the problem this module
was built to remove. Instead the index records each record's *byte* offset in the axis jsonl
during a single streaming pass that keeps lengths and discards text, and text is fetched on
demand by seeking to that offset. One small JSON parse per access, no duplicate artifact, one
source of truth.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from data_io import resolve

AXIS_DATASET = "paragraph_axis_1626_1630"

# session-3187-num-114-resolution-1
FLAT_ID_RE = re.compile(r"^session-(?P<inventory>\d+)-num-(?P<session>\d+)-resolution-(?P<resolution>\d+)$")


class FlatIdError(ValueError):
    """A flat id that does not name an inventory, session and resolution."""


@dataclass(frozen=True)
class ParagraphRef:
    """One paragraph's place in its inventory's stream. Carries no text.

    `char_start`/`char_len` are in characters, on the inventory-wide coordinate.
    `byte_offset` is where this record's line starts in the axis jsonl, used only to fetch
    the text on demand.
    """

    inventory: str
    session_num: int
    resolution_num: int
    para_index: int
    stream_index: int
    char_start: int
    char_len: int
    flat_id: str
    axis_id: str
    date_label: str | None
    byte_offset: int

    @property
    def char_end(self) -> int:
        return self.char_start + self.char_len

    @property
    def session_id(self) -> str:
        return f"session-{self.inventory}-num-{self.session_num}"


def parse_flat_id(flat_id: str) -> tuple[str, int, int]:
    match = FLAT_ID_RE.match(str(flat_id))
    if not match:
        raise FlatIdError(f"cannot parse flat_id {flat_id!r}")
    return (
        match["inventory"],
        int(match["session"]),
        int(match["resolution"]),
    )


def _axis_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else Path(resolve(AXIS_DATASET))


def index_axis(path: str | Path | None = None) -> list[dict[str, object]]:
    """Stream the axis jsonl once, keeping coordinates and byte offsets, discarding text.

    Returned rows are unordered raw records; `InventoryStream.build` sorts them. Kept
    separate so the single expensive pass over the file is reusable and testable.
    """
    axis_path = _axis_path(path)
    rows: list[dict[str, object]] = []
    with axis_path.open("rb") as handle:
        offset = 0
        for raw in handle:
            length = len(raw)
            record = json.loads(raw)
            flat_id = str(record["flat_id"])
            inventory, session_num, resolution_num = parse_flat_id(flat_id)
            rows.append(
                {
                    "inventory": inventory,
                    "session_num": session_num,
                    "resolution_num": resolution_num,
                    "para_index": int(record.get("para_index") or 0),
                    "char_len": len(record.get("text") or ""),
                    "flat_id": flat_id,
                    "axis_id": str(record.get("axis_id") or ""),
                    "date_label": (str(record["date"]) if record.get("date") else None),
                    "byte_offset": offset,
                }
            )
            offset += length
    return rows


class InventoryStream:
    """One inventory's paragraphs as a continuous character coordinate.

    Order is `(session_num, resolution_num, para_index)`, which is archive order: Step 1 of
    `plans/COLLISION_AVOIDANCE_TRACK.md` found zero non-monotone steps across 3185-3189 for
    content-verified landmarks, so flat order is physical order and this coordinate is not an
    invention of the pipeline.
    """

    def __init__(self, inventory: str, refs: Sequence[ParagraphRef], axis_path: Path) -> None:
        self.inventory = inventory
        self.refs: tuple[ParagraphRef, ...] = tuple(refs)
        self._axis_path = axis_path
        self._starts = [ref.char_start for ref in self.refs]
        self._text_cache: dict[int, str] = {}

    def __len__(self) -> int:
        return len(self.refs)

    def __iter__(self) -> Iterator[ParagraphRef]:
        return iter(self.refs)

    @property
    def char_length(self) -> int:
        return self.refs[-1].char_end if self.refs else 0

    @property
    def session_numbers(self) -> list[int]:
        return sorted({ref.session_num for ref in self.refs})

    def absent_session_numbers(self) -> list[int]:
        """Session numbers inside this inventory's range that the axis has no paragraph for.

        Reported rather than skipped: a missing number is a session the archive numbered and
        the axis does not carry, which is a fact about coverage, not an absence of text.
        """
        present = self.session_numbers
        if not present:
            return []
        return [num for num in range(present[0], present[-1] + 1) if num not in set(present)]

    def date_labels(self) -> list[str]:
        return sorted({ref.date_label for ref in self.refs if ref.date_label})

    def sessions(self) -> dict[str, tuple[int, int]]:
        """`session_id` -> its half-open character span on this stream."""
        spans: dict[str, tuple[int, int]] = {}
        for ref in self.refs:
            start, end = spans.get(ref.session_id, (ref.char_start, ref.char_end))
            spans[ref.session_id] = (min(start, ref.char_start), max(end, ref.char_end))
        return spans

    def ref_at(self, position: int) -> ParagraphRef:
        """The paragraph containing `position`."""
        if not self.refs or not 0 <= position < self.char_length:
            raise IndexError(
                f"position {position} outside inventory {self.inventory} [0,{self.char_length})"
            )
        return self.refs[max(0, bisect_right(self._starts, position) - 1)]

    def refs_overlapping(self, begin: int, end: int) -> list[ParagraphRef]:
        return [ref for ref in self.refs if ref.char_start < end and begin < ref.char_end]

    def text_of(self, ref: ParagraphRef) -> str:
        """Fetch one paragraph's text, seeking to its line in the axis jsonl. Memoised."""
        cached = self._text_cache.get(ref.byte_offset)
        if cached is not None:
            return cached
        with self._axis_path.open("rb") as handle:
            handle.seek(ref.byte_offset)
            record = json.loads(handle.readline())
        text = str(record.get("text") or "")
        if len(text) != ref.char_len:
            raise RuntimeError(
                f"axis changed under the index: {ref.flat_id} indexed at {ref.char_len} "
                f"characters, file now has {len(text)}. Rebuild the index."
            )
        self._text_cache[ref.byte_offset] = text
        return text

    def text(self, begin: int | None = None, end: int | None = None) -> str:
        """Text for a character range on this stream, assembled from the paragraphs it spans."""
        lo = 0 if begin is None else begin
        hi = self.char_length if end is None else end
        if lo < 0 or hi > self.char_length or hi < lo:
            raise IndexError(f"range [{lo},{hi}) outside [0,{self.char_length})")
        parts: list[str] = []
        for ref in self.refs_overlapping(lo, hi):
            chunk = self.text_of(ref)
            parts.append(chunk[max(0, lo - ref.char_start) : max(0, hi - ref.char_start)])
        return "".join(parts)

    @classmethod
    def build(
        cls, inventory: str, rows: Iterable[dict[str, object]], axis_path: Path
    ) -> "InventoryStream":
        ordered = sorted(
            rows,
            key=lambda row: (
                int(row["session_num"]),
                int(row["resolution_num"]),
                int(row["para_index"]),
            ),
        )
        refs: list[ParagraphRef] = []
        cursor = 0
        for stream_index, row in enumerate(ordered):
            char_len = int(row["char_len"])
            refs.append(
                ParagraphRef(
                    inventory=inventory,
                    session_num=int(row["session_num"]),
                    resolution_num=int(row["resolution_num"]),
                    para_index=int(row["para_index"]),
                    stream_index=stream_index,
                    char_start=cursor,
                    char_len=char_len,
                    flat_id=str(row["flat_id"]),
                    axis_id=str(row["axis_id"]),
                    date_label=row["date_label"],  # type: ignore[arg-type]
                    byte_offset=int(row["byte_offset"]),
                )
            )
            cursor += char_len
        return cls(inventory, refs, axis_path)


def build_streams(path: str | Path | None = None) -> dict[str, InventoryStream]:
    """Every inventory's stream, from one pass over the axis."""
    axis_path = _axis_path(path)
    rows = index_axis(axis_path)
    by_inventory: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_inventory.setdefault(str(row["inventory"]), []).append(row)
    return {
        inventory: InventoryStream.build(inventory, inventory_rows, axis_path)
        for inventory, inventory_rows in sorted(by_inventory.items())
    }
