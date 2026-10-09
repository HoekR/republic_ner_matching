"""Node types for the three sequences. Stage 1 of `plans/the-two-deep-hits-melodic-avalanche.md`.

**Three identity families, six ordered chains.** The spine's "three sequences" (physical / HTR /
editorial) are identity families, not flat orders -- each decomposes into its own nested chain by
granularity, and granularity is a *different* partition from identity (user, 2026-10-08: the
writeup's three anchor levels -- session/resolution/paragraph -- are a granularity axis; physical/
HTR/editorial is an identity axis; they do not coincide). Concretely, six `NEXT`-ordered node types:

    physical:   Scan                                          (one chain per inventory)
    HTR:        Session -> HtrResolution -> Paragraph          (three nested chains)
    editorial:  SittingDay -> EnrichedResolution                (two nested chains)

`CONTAINS` nests a chain inside its parent (Session contains HtrResolution, HtrResolution contains
Paragraph, SittingDay contains EnrichedResolution); `NEXT` orders siblings within one parent (or,
for Scan and SittingDay, within one inventory / the whole corpus). `Entity` has no `NEXT` order of
its own -- it is the `MENTIONS` edge's target, built in Stage 2, not a sequence.

Every id is **derived from the archival identifier, never a counter** (`running_axis.spans.Span`'s
own `span_id` rule), so two builds of the same snapshot produce identical node ids and a result is
comparable across runs without a lookup table.

Reused rather than reimplemented: `running_axis.stream.parse_flat_id` for the `flat_id` grammar
(`session-{inv}-num-{session}-resolution-{resolution}`), the same regex `running_axis` itself keys
on.
"""

from __future__ import annotations

from dataclasses import dataclass

from running_axis.stream import FlatIdError, parse_flat_id


@dataclass(frozen=True)
class Scan:
    """One scan (a two-page spread) in one inventory's physical order. **Observed.**

    `scan_num` is the number in the scan's own filename
    (`NL-HaNA_1.01.02_{inventory}_{scan_num:04d}`), 1-indexed and contiguous within an inventory
    (`inventory_metadata.num_scans`) -- there is no missing-scan case to represent, because scan
    numbering is complete by construction (the scan track's own standing note: a digitisation gap
    is not observable from this data).
    """

    inventory: str
    scan_num: int

    @property
    def node_id(self) -> str:
        return f"scan:{self.inventory}:{self.scan_num}"


@dataclass(frozen=True)
class Session:
    """One HTR session, in its inventory's `session_num` order. Observed within the HTR sequence."""

    session_id: str
    inventory: str
    session_num: int

    @property
    def node_id(self) -> str:
        return f"session:{self.session_id}"

    @classmethod
    def from_session_id(cls, session_id: str) -> "Session":
        inventory, session_num, _ = parse_flat_id(f"{session_id}-resolution-0")
        return cls(session_id=session_id, inventory=inventory, session_num=session_num)


@dataclass(frozen=True)
class HtrResolution:
    """One flat HTR resolution, in its session's `resolution_num` order."""

    flat_id: str
    session_id: str
    inventory: str
    resolution_num: int

    @property
    def node_id(self) -> str:
        return f"htr_res:{self.flat_id}"

    @classmethod
    def from_flat_id(cls, flat_id: str) -> "HtrResolution":
        inventory, session_num, resolution_num = parse_flat_id(flat_id)
        return cls(
            flat_id=flat_id,
            session_id=f"session-{inventory}-num-{session_num}",
            inventory=inventory,
            resolution_num=resolution_num,
        )


@dataclass(frozen=True)
class Paragraph:
    """One paragraph-axis row, in its resolution's `para_index` order.

    `axis_id` (`{flat_id}#p{para_index}`) is the axis's own stable id, not invented here.
    """

    axis_id: str
    flat_id: str
    para_index: int

    @property
    def node_id(self) -> str:
        return f"para:{self.axis_id}"


@dataclass(frozen=True)
class SittingDay:
    """One enriched calendar date. Observed within the editorial sequence.

    Carries no `is_sidelined`/`is_nihil` flag of its own -- those are facts about what this date
    resolves to (a `PINNED_TO` target, Stage 2) or about its own content (`is_nihil_actum`, a
    property of the day, not of this node's identity), and the editorial sequence must stay
    independent of what the physical/HTR sequences later say about it.
    """

    date: str

    @property
    def node_id(self) -> str:
        return f"day:{self.date}"


@dataclass(frozen=True)
class EnrichedResolution:
    """One hand-written summary, in its day's `resolution_index` order."""

    date: str
    index: int

    @property
    def node_id(self) -> str:
        return f"enriched:{self.date}:{self.index}"


@dataclass(frozen=True)
class Entity:
    """One named entity (person/place/institution), the `MENTIONS` edge's target (Stage 2).

    No `NEXT` order of its own: an entity is not a position in a sequence, it is a label that two
    different sequences can independently attach to one of their own positions.
    """

    entity_id: str

    @property
    def node_id(self) -> str:
        return f"entity:{self.entity_id}"


__all__ = [
    "Scan",
    "Session",
    "HtrResolution",
    "Paragraph",
    "SittingDay",
    "EnrichedResolution",
    "Entity",
]
