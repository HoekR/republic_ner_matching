"""Serialise the running axis, and render the serialised form as a ribbon.

The visualisation is driven off the *serialised* spans rather than off live objects, which is
REPUBLIC's own arrangement (`MatchedText.to_dict()` feeding `serialize()` /
`visualize_as_html`): the rows below are plain JSON, so the same payload can go into a
notebook, a report, or a file without the renderer reaching back into the model. One
consequence worth keeping: a picture can never show something the serialised state does not
contain, so if a gap is invisible here it is because the state really has none.

What a ribbon shows. One horizontal strip per inventory, laid out on that inventory's
character coordinate, each session coloured by the *addressability* of the dates claiming it
and the stretches no session covers left visibly empty. That makes the defect this package
was built for legible at a glance: in October 1628 inventory 3187 runs continuously, yet
`s6b_known_point_ledger` files 16 of its 31 days under a fabricated `no_axis` inventory --
and three of those days own 34k, 46k and 37k characters of it.

No plotting dependency: the output is a self-contained SVG string, so it renders in a
notebook, a browser, or a markdown file without matplotlib or a kernel.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# Colour-blind-safe, and ordered so the two classes that matter most are the most saturated.
# `dropped_by_label_grouping` is deliberately the loudest: it is the recoverable one.
ADDRESSABILITY_COLOURS = {
    "labelled": "#4878d0",
    "dropped_by_label_grouping": "#ee854a",
    "nihil_actum": "#8c8c8c",
    "no_session": "#d65f5f",
    "unclaimed": "#e8e8e8",
}

# A session claimed by several dates is drawn in the colour of its most consequential claim
# with a marked border, not in a colour of its own. Colouring sharing instead of
# addressability hid the thing the ribbon exists to show: in October 1628 all three sessions
# carrying a discarded date are shared or not independently of that fact, and two of them
# host a labelled date as well, so a single "shared" fill erased two of the three.
FILL_PRIORITY = ("dropped_by_label_grouping", "no_session", "nihil_actum", "labelled")
SHARED_STROKE = "#1a7f37"


@dataclass(frozen=True)
class RibbonSegment:
    """One stretch of an inventory's coordinate, ready to serialise or draw."""

    inventory: str
    char_begin: int
    char_end: int
    kind: str
    session_id: str | None = None
    dates: tuple[str, ...] = ()
    label: str = ""
    shared: bool = False

    @property
    def char_length(self) -> int:
        return self.char_end - self.char_begin

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory": self.inventory,
            "char_begin": self.char_begin,
            "char_end": self.char_end,
            "char_length": self.char_length,
            "kind": self.kind,
            "session_id": self.session_id,
            "dates": list(self.dates),
            "label": self.label,
            "shared": self.shared,
        }


def ribbon_segments(view: Any) -> list[RibbonSegment]:
    """Serialise a `RunningAxisView` into gapless per-inventory segments.

    Gaplessness is the property inherited from `spans.fragments()`: between two sessions the
    unclaimed stretch is emitted as its own `unclaimed` segment rather than skipped, so the
    ribbon cannot quietly close a hole the data has.
    """
    axis = view.axis
    sessions = view.sessions
    addressability = {state.date: state.addressability for state in axis.dates.values()}

    by_inventory: dict[str, list[Any]] = {}
    for session in sessions:
        by_inventory.setdefault(session.inventory, []).append(session)

    out: list[RibbonSegment] = []
    for inventory, members in sorted(by_inventory.items()):
        members = sorted(members, key=lambda s: s.char_begin)
        cursor = members[0].char_begin
        for session in members:
            if session.char_begin > cursor:
                out.append(
                    RibbonSegment(inventory, cursor, session.char_begin, "unclaimed",
                                  label="no session covers this stretch")
                )
            claims = session.resolved_dates or session.label_dates
            classes = [addressability.get(date, "labelled") for date in claims]
            kind = next((c for c in FILL_PRIORITY if c in classes), "unclaimed")
            claim_detail = ", ".join(
                f"{date} ({addressability.get(date, 'labelled')})" for date in claims
            ) or "no claim"
            out.append(
                RibbonSegment(
                    inventory=inventory,
                    char_begin=session.char_begin,
                    char_end=session.char_end,
                    kind=kind,
                    session_id=session.session_id,
                    dates=claims,
                    shared=session.is_shared,
                    label=(
                        f"{session.session_id} | {session.char_length:,} chars"
                        f" | axis label {','.join(session.label_dates) or '-'}"
                        f" | claims: {claim_detail}"
                        + (" | SHARED" if session.is_shared else "")
                    ),
                )
            )
            cursor = max(cursor, session.char_end)
    return out


def to_json(segments: Sequence[RibbonSegment], **extra: Any) -> str:
    """The serialised payload a renderer consumes. Plain JSON, no model objects."""
    return json.dumps({"segments": [s.to_dict() for s in segments], **extra}, indent=1)


def render_svg(
    segments: Sequence[RibbonSegment],
    *,
    title: str = "",
    width: int = 960,
    row_height: int = 26,
    gap: int = 8,
) -> str:
    """A self-contained SVG ribbon. Takes serialised segments, returns a string."""
    by_inventory: dict[str, list[RibbonSegment]] = {}
    for segment in segments:
        by_inventory.setdefault(segment.inventory, []).append(segment)
    if not by_inventory:
        return "<p>no segments in this window</p>"

    label_w = 56
    track_w = width - label_w - 8
    rows = sorted(by_inventory)
    height = len(rows) * (row_height + gap) + (34 if title else 10)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'font-family="system-ui,sans-serif" font-size="11">'
    ]
    if title:
        parts.append(f'<text x="0" y="14" font-size="12" font-weight="600">{html.escape(title)}</text>')

    y = 26 if title else 4
    for inventory in rows:
        members = sorted(by_inventory[inventory], key=lambda s: s.char_begin)
        lo = min(s.char_begin for s in members)
        hi = max(s.char_end for s in members)
        span = max(hi - lo, 1)
        parts.append(
            f'<text x="0" y="{y + row_height - 9}" fill="#444">{html.escape(inventory)}</text>'
        )
        for segment in members:
            if segment.char_length <= 0:
                continue
            x = label_w + (segment.char_begin - lo) / span * track_w
            w = max(segment.char_length / span * track_w, 0.7)
            colour = ADDRESSABILITY_COLOURS.get(segment.kind, "#cccccc")
            stroke, stroke_w = ("#fff", 0.4)
            if segment.shared:
                stroke, stroke_w = (SHARED_STROKE, 1.6)
            parts.append(
                f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="{row_height}" '
                f'fill="{colour}" stroke="{stroke}" stroke-width="{stroke_w}">'
                f"<title>{html.escape(segment.label or segment.kind)}</title></rect>"
            )
        parts.append(
            f'<text x="{label_w + track_w + 4}" y="{y + row_height - 9}" fill="#888">'
            f'{span/1000:.0f}k</text>'
        )
        y += row_height + gap
    parts.append("</svg>")
    return "".join(parts)


def render_legend() -> str:
    shared_note = (
        f'<span style="display:inline-flex;align-items:center;margin-right:12px">'
        f'<span style="width:11px;height:11px;background:#fff;display:inline-block;'
        f'margin-right:4px;border:2px solid {SHARED_STROKE}"></span>'
        f'<span style="font:11px system-ui,sans-serif">shared (border)</span></span>'
    )
    swatches = shared_note + "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:12px">'
        f'<span style="width:11px;height:11px;background:{colour};display:inline-block;'
        f'margin-right:4px;border:1px solid #fff"></span>'
        f'<span style="font:11px system-ui,sans-serif">{html.escape(name)}</span></span>'
        for name, colour in ADDRESSABILITY_COLOURS.items()
    )
    return f'<div style="margin:6px 0">{swatches}</div>'


def render_html(view: Any, *, title: str = "", width: int = 960) -> str:
    """Convenience: serialise a view and render it, legend included."""
    segments = ribbon_segments(view)
    return render_legend() + render_svg(segments, title=title or str(view.window), width=width)
