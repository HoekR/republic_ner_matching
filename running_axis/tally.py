"""Counts that carry their own population, so two of them can never be confused.

The motivating incident, from this model's own context. Asked how many dates the corpus has,
the honest answer was "1,240" *and* "1,059" *and* "1,594" *and* "535" -- all correct, each
counting something different:

* 1,594 distinct dates in the enriched edition,
* 1,240 distinct date labels carried by paragraphs on the axis,
* 1,059 dates that are both,
* 535 enriched dates carrying no axis label.

Nothing in the data said which was which, so they were quoted interchangeably and read as a
contradiction. The same failure produced three live gap counts for one ledger -- 120 from a
one-month run on disk, 947 cited in `PLAN.md` from some earlier full-window run, and a third
set that turned out to be fabricated -- because a bare integer does not say what window it
describes.

A bare integer is therefore not a reportable quantity here. A `Tally` names its unit, its
population and the window it covers, and the arithmetic refuses to mix them:

* adding tallies requires the same population and *disjoint* windows, which is what makes a
  year legitimately the sum of its months;
* subtracting or comparing across populations raises, and points at `against()`, which
  returns a `Comparison` that prints both population names -- so "1,240 vs 1,059" cannot be
  written down without showing that they count different things;
* a share is a `Ratio` holding both tallies, so it cannot be quoted without its denominator.

Populations are a closed registry with a prose definition each. A quantity whose population
is not registered cannot be tallied, and that refusal is the signal that the registry is
incomplete rather than that the number is unimportant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# --- windows ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """The date span a tally describes, as one or more disjoint closed intervals.

    Unions are representable because a year's tally is the sum of its months' tallies and the
    result has to be able to say so. ``Window.all()`` means the model's whole coverage, which
    is *not* the same as an unspecified window -- there is no unspecified window.
    """

    spans: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.spans:
            raise ValueError("a window needs at least one span")
        ordered = sorted(self.spans)
        for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:]):
            if next_start <= prev_end:
                raise ValueError(f"window spans overlap: {ordered}")
        for start, end in ordered:
            if end < start:
                raise ValueError(f"window span runs backwards: {(start, end)}")
        object.__setattr__(self, "spans", tuple(ordered))

    @classmethod
    def of(cls, start: str, end: str) -> "Window":
        return cls(((start, end),))

    @classmethod
    def all(cls) -> "Window":
        return cls((("1626-01-01", "1630-12-31"),))

    @property
    def start(self) -> str:
        return self.spans[0][0]

    @property
    def end(self) -> str:
        return self.spans[-1][1]

    def is_disjoint_from(self, other: "Window") -> bool:
        return all(
            mine_end < theirs_start or theirs_end < mine_start
            for mine_start, mine_end in self.spans
            for theirs_start, theirs_end in other.spans
        )

    def union(self, other: "Window") -> "Window":
        if not self.is_disjoint_from(other):
            raise ValueError(f"cannot union overlapping windows: {self} and {other}")
        return Window(self.spans + other.spans)

    def __str__(self) -> str:
        if len(self.spans) == 1:
            return f"{self.start}..{self.end}"
        return f"{self.start}..{self.end} ({len(self.spans)} spans)"


# --- populations -----------------------------------------------------------------------


@dataclass(frozen=True)
class Population:
    """What a tally counts: a unit, a prose definition, and how dates were attributed.

    ``attribution`` matters because the same unit over the same window gives different
    answers depending on it. The axis labels a paragraph with the date of the session its
    ``flat_id`` names, while the concordance may resolve that session to a different date --
    which is exactly why 66 dates holding 983 resolutions read as "no axis" while carrying a
    resolved session. A population that does not say which rule it used is ambiguous by
    construction.
    """

    name: str
    unit: str
    definition: str
    attribution: str = "n/a"
    subset_of: str | None = None
    complement: str | None = None
    """``subset_of`` names the population this one is contained in; ``complement`` names the
    population that is ``subset_of`` minus this one. Declaring them is what lets
    ``1,594 enriched_dates - 1,059 enriched_with_axis_label`` evaluate to
    ``535 enriched_without_axis_label`` while ``1,240 axis_date_labels - 1,059`` still
    raises. Without the declaration a subtraction cannot be known to be a partition, and
    guessing is how the counts got confused in the first place."""

    def __str__(self) -> str:
        suffix = "" if self.attribution == "n/a" else f"/{self.attribution}"
        return f"{self.name}[{self.unit}{suffix}]"


class PopulationRegistry:
    """The closed set of populations this model can count."""

    def __init__(self) -> None:
        self._populations: dict[str, Population] = {}

    def register(
        self,
        name: str,
        unit: str,
        definition: str,
        attribution: str = "n/a",
        subset_of: str | None = None,
        complement: str | None = None,
    ) -> Population:
        if name in self._populations:
            raise ValueError(f"population {name!r} already registered")
        if subset_of is not None and subset_of not in self._populations:
            raise KeyError(f"subset_of {subset_of!r} must be registered before {name!r}")
        population = Population(
            name=name,
            unit=unit,
            definition=definition,
            attribution=attribution,
            subset_of=subset_of,
            complement=complement,
        )
        self._populations[name] = population
        return population

    def get(self, name: str) -> Population:
        try:
            return self._populations[name]
        except KeyError as exc:
            known = ", ".join(sorted(self._populations)) or "none"
            raise KeyError(
                f"population {name!r} is not registered -- register it with its definition "
                f"before counting it. Known: {known}"
            ) from exc

    def __contains__(self, name: object) -> bool:
        return name in self._populations

    def names(self) -> list[str]:
        return sorted(self._populations)


POPULATIONS = PopulationRegistry()

# The four that were being quoted interchangeably, now distinguishable by name alone.
ENRICHED_DATES = POPULATIONS.register(
    "enriched_dates",
    "dates",
    "Distinct calendar dates present in the enriched edition (resolution_concordance_1626_1630).",
)
AXIS_DATE_LABELS = POPULATIONS.register(
    "axis_date_labels",
    "dates",
    "Distinct date labels carried by paragraphs on paragraph_axis_1626_1630. Includes labels "
    "outside the enriched edition's range, which runs to 1630-05-14 while the axis runs to "
    "1630-12-31.",
    attribution="axis_label",
)
ENRICHED_WITH_AXIS_LABEL = POPULATIONS.register(
    "enriched_with_axis_label",
    "dates",
    "Enriched dates for which at least one axis paragraph carries that date as its label.",
    attribution="axis_label",
    subset_of="enriched_dates",
    complement="enriched_without_axis_label",
)
ENRICHED_WITHOUT_AXIS_LABEL = POPULATIONS.register(
    "enriched_without_axis_label",
    "dates",
    "Enriched dates no axis paragraph labels. NOT the same as 'has no HTR': a date whose "
    "session the concordance resolved still lands here when that session carries a different "
    "date label.",
    attribution="axis_label",
    subset_of="enriched_dates",
    complement="enriched_with_axis_label",
)
AXIS_LABEL_NOT_ENRICHED = POPULATIONS.register(
    "axis_label_not_enriched",
    "dates",
    "Axis date labels that are not enriched dates, mostly beyond the enriched edition's end.",
    attribution="axis_label",
)
ENRICHED_WITH_RESOLVED_SESSION = POPULATIONS.register(
    "enriched_with_resolved_session",
    "dates",
    "Enriched dates the concordance resolves to an HTR session, regardless of what date "
    "label that session's paragraphs carry.",
    attribution="resolved_session",
)
ENRICHED_RESOLUTIONS = POPULATIONS.register(
    "enriched_resolutions",
    "resolutions",
    "Enriched resolutions (rows of resolution_concordance_1626_1630).",
)
AXIS_PARAGRAPHS = POPULATIONS.register(
    "axis_paragraphs",
    "paragraphs",
    "Paragraph records on paragraph_axis_1626_1630.",
)
AXIS_CHARACTERS = POPULATIONS.register(
    "axis_characters",
    "chars",
    "Characters of HTR text on the paragraph axis, summed over paragraphs.",
)


# --- tallies ---------------------------------------------------------------------------


class PopulationMismatch(TypeError):
    """Two tallies that do not count the same thing were combined."""


@dataclass(frozen=True)
class Tally:
    """One count, inseparable from what it counts and the window it covers."""

    population: Population
    window: Window
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError(f"negative tally: {self.value}")

    def _require_same_population(self, other: "Tally", operation: str) -> None:
        if self.population != other.population:
            raise PopulationMismatch(
                f"cannot {operation} {self.population} and {other.population}: they count "
                f"different populations. Use .against() for a comparison that names both."
            )

    def __add__(self, other: "Tally") -> "Tally":
        self._require_same_population(other, "add")
        if not self.window.is_disjoint_from(other.window):
            raise PopulationMismatch(
                f"cannot add tallies over overlapping windows ({self.window}, {other.window}): "
                "the same item would be counted twice."
            )
        return Tally(self.population, self.window.union(other.window), self.value + other.value)

    def __sub__(self, other: "Tally") -> "Tally":
        if self.window != other.window:
            raise PopulationMismatch(
                f"cannot subtract across different windows ({self.window}, {other.window})."
            )
        if self.population == other.population:
            return Tally(self.population, self.window, self.value - other.value)
        # A declared partition: whole - part = the part's registered complement.
        if other.population.subset_of == self.population.name and other.population.complement:
            return Tally(
                POPULATIONS.get(other.population.complement),
                self.window,
                self.value - other.value,
            )
        raise PopulationMismatch(
            f"cannot subtract {other.population} from {self.population}: not the same "
            f"population, and {other.population.name!r} is not declared a subset of "
            f"{self.population.name!r} with a complement. Use .against() for a comparison "
            "that names both, or declare the set relation when registering."
        )

    def against(self, other: "Tally") -> "Comparison":
        """Compare two tallies, naming both populations in the result."""
        return Comparison(left=self, right=other)

    def over(self, denominator: "Tally") -> "Ratio":
        return Ratio(numerator=self, denominator=denominator)

    def __str__(self) -> str:
        return f"{self.value:,} {self.population} over {self.window}"


@dataclass(frozen=True)
class Comparison:
    """Two tallies set side by side, which prints both populations.

    This is what "1,240 vs 1,059" has to become: the difference is only meaningful if the
    reader can see that one counts axis labels and the other counts enriched dates that have
    one, so the rendering refuses to show the numbers without the names.
    """

    left: Tally
    right: Tally

    @property
    def difference(self) -> int:
        return self.left.value - self.right.value

    def __str__(self) -> str:
        return (
            f"{self.left.value:,} {self.left.population} vs "
            f"{self.right.value:,} {self.right.population} "
            f"(difference {self.difference:+,}) over {self.left.window}"
        )


@dataclass(frozen=True)
class Ratio:
    """A share that cannot be quoted without its denominator."""

    numerator: Tally
    denominator: Tally

    def __post_init__(self) -> None:
        if self.numerator.window != self.denominator.window:
            raise PopulationMismatch(
                f"a ratio needs one window, got {self.numerator.window} and "
                f"{self.denominator.window}."
            )
        if self.numerator.population.unit != self.denominator.population.unit:
            raise PopulationMismatch(
                f"a ratio needs one unit, got {self.numerator.population.unit!r} and "
                f"{self.denominator.population.unit!r} -- a count of dates is not a share of "
                "resolutions."
            )

    @property
    def value(self) -> float:
        if self.denominator.value == 0:
            raise ZeroDivisionError(
                f"{self.denominator.population} is empty over {self.denominator.window}; "
                "an empty denominator is a finding, not a zero share."
            )
        return self.numerator.value / self.denominator.value

    def __str__(self) -> str:
        return (
            f"{self.numerator.value:,} of {self.denominator.value:,} "
            f"({self.value:.1%}) {self.numerator.population} of {self.denominator.population} "
            f"over {self.numerator.window}"
        )


def check_partition(whole: Tally, parts: Iterable[Tally]) -> None:
    """Assert that `parts` are declared subsets of `whole` and account for all of it.

    This turns "the numbers reconcile" from a sentence in a report into something that
    fails loudly when it stops being true.
    """
    items = list(parts)
    for part in items:
        if part.population.subset_of != whole.population.name:
            raise PopulationMismatch(
                f"{part.population} is not declared a subset of {whole.population}"
            )
        if part.window != whole.window:
            raise PopulationMismatch(
                f"{part.population} covers {part.window}, not {whole.window}"
            )
    accounted = sum(part.value for part in items)
    if accounted != whole.value:
        detail = " + ".join(f"{p.value:,} {p.population.name}" for p in items)
        raise PopulationMismatch(
            f"partition does not account for {whole.population}: {detail} = {accounted:,}, "
            f"but {whole.population.name} is {whole.value:,} over {whole.window}"
        )


def total(tallies: Iterable[Tally]) -> Tally:
    """Sum tallies of one population over disjoint windows. Raises on anything else."""
    items = list(tallies)
    if not items:
        raise ValueError("nothing to total")
    running = items[0]
    for item in items[1:]:
        running = running + item
    return running
