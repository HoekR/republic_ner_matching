#!/usr/bin/env python3
"""Group C, rebuilt as a **typed, period-filtered formula searcher** (PLAN.md Track P, P1
follow-up, user sign-off 2026-10-05).

Why the channel is being replaced rather than rescored
------------------------------------------------------
P1 (`s6c_group_c_interior_offset_calibration.py`) established two things about the old channel.
The candidate *set* carries the cut (nearest-candidate displacement 120.4 chars vs a
count-matched null of 246.7, ratio 0.49, day-clustered p=0.0030), but the channel's own
*ranking* cannot find it (351.7 vs 448.7, ratio 0.78, day-clustered 18/27 days p=0.061 --
direction only). The whole nearest-to-ranked gap is selection: the ranking picks its own
closest-to-gold candidate just 33 of 57 times.

The diagnosis (user-led, PLAN.md) is that this is not a scoring problem. The old inventory was
built by n-gram frequency *over known openings* with no background frequency ever consulted, so
it conflates real formulas, truncated prefixes of real formulas, and free prefixes that formulas
share with ordinary prose. Frequency cannot separate them: `in deliberatie geleyt synde,` is a
gold-confirmed formula with count 5, while `de heeren van` -- categorically never an opening
formula -- has count 10. And the inventory is fit to the wrong population: it covers 85.4% of
`paragraph_boundary` cuts but only 61.2% of `mid_paragraph` ones, because it was derived from
tier-1 anchored resolutions, which are overwhelmingly paragraph-initial. Openings that HTR lumped
into a paragraph are linguistically different.

The division of labour this module implements (user, 2026-10-05)
---------------------------------------------------------------
**REPUBLIC for structure and class, our own material for early-period realisation.**

1. **Admissibility.** An empirical n-gram is a candidate formula only if it *attaches* to a
   sanctioned REPUBLIC frame -- prefix-anchored, orthography-folded, token-level fuzzy. Frequency
   plays no part. This is what purges `de heeren van`, and it purges it for a stated reason rather
   than a threshold: the strongest thing it attaches to is `prefix_phrases`' `de Heeren`, labelled
   `person_name_prefix`. REPUBLIC's constituent classes (name prefixes, organisation titles,
   person roles, locations, document types, body verbs) are carried as **negative** evidence --
   the material a resolution is made of, never the thing that opens one.
2. **Class.** Inherited from the *form* the n-gram attaches to, not from the entry: `Is
   goetgevonden` carries `In deliberatie geleijt sijnde` as a variant, so the entry cannot type
   its own members. `is goetgevonden ende verstaen` attaches further into `decision_phrases`'
   `is goedgevonden ende verstaan` (4 tokens) than into the opening `Is goetgevonden` (2), so it
   types as decision; bare `is goetgevonden` covers the opening form completely and types as
   intake. One rule, both cases, no list.
3. **Period filter.** Only frames whose `start_year`/`end_year` span 1626-1630 are sanctioning.
   44 of REPUBLIC's 99 opening frames are printed-era (1637+) and are excluded, which is the
   point: they are the ones whose orthography our HTR cannot match anyway.
4. **The participial construction as a pattern, not a phrase list.** 35.8% of gold
   `mid_paragraph` cuts open with `Synde`/`Syn` + participle (+ `ter Vergaderinge`) + object, or
   its inversion `<participle> synde` -- *Synde gecommuniceert seeckere missive*, *Gelesen synde
   de requeste van*, *Nochmael geresumeert synde t'versouck*. A frequency list cannot hold a
   productive construction; it captured the bare stem `synde` (count 740) instead, which is why
   that stem was a live member of the old channel. The participle's own class is derived from
   REPUBLIC occurrence too, so `WAAR op gedelibereert zijnde` stays decision-class.
5. **`max_start_offset` honoured, translated rather than copied.** In REPUBLIC it filters matches
   by absolute offset within an already-segmented unit; applied that way here it would reject
   every interior candidate, which is the entire question Track P exists to ask. The faithful
   translation: a frame with `max_start_offset = m` found at offset `f` asserts its resolution
   began at some `s` with `f - m <= s <= f`. So `m` is a **window the cut is snapped back
   through**, to the nearest preceding clause start. For the 52 of 55 in-period frames with
   `m = 2` this is a no-op; the three wide ones (350/150/40) genuinely cannot pin a cut on their
   own and now say so.
6. **Ordering rule applied.** Intake-class formulas precede decision-class ones (97.0%
   corpus-wide, 3,529 of 3,637 paragraphs containing both), and a decision formula opens a
   resolution only where no intake formula is available (96.7%, 1,097 of 1,134). So a
   decision-class candidate is suppressed when any intake-class match precedes it -- including a
   match at offset 0, which belongs to the paragraph's own opening resolution and is exactly what
   makes the following decision formula interior rather than initial.

The worked example, which needs no tuning: `1629-09-22` paragraph 4, gold cut at 1639, four old
candidates. `2888 "de heeren van"` purged at step 1; `1200`/`1669 "is goetgevonden ende verstaen"`
type as decision at step 2 and `1669` is suppressed at step 6 by the intake formula at 1640;
`1640 "in deliberatie geleyt synde,"` is intake and wins -- 1 character from gold. The old
similarity ranking picked `2888` (sim 1.000, a short generic phrase matching exactly) and was
1,249 chars wrong.

Deliberately NOT used: the clause-terminator signal as a *filter*. Gold cuts are preceded by a
terminator 72.6% of the time against 54.9% for decoy candidates -- too weak to reject on, since it
would throw away a quarter of true cuts. It is used only as a *snap target inside an already-
narrowed `max_start_offset` window*, which is the locality principle this project keeps
rediscovering: weak channels are resolvers inside a narrowed gap, never detectors on their own.

Free parameters: three, all in the token alignment, none fitted to gold, each with its motivating
case stated where it is defined -- `TOKEN_SIMILARITY` (0.72: the fuzzy searcher's own
`levenshtein_threshold` of 0.85 is too strict per *token*, because orthographic variation is
per-token and compounds over a phrase, `geaduyseert`/`geadviseert`), `MAX_CANDIDATE_SKIP` (2) and
`MAX_LEAD_SKIP` (1). Everything else -- the period bounds, the offsets, the class partition, the
ordering rule -- comes from REPUBLIC or from a rule measured corpus-wide. No weight is fitted to
gold, and nothing here was tuned against the 73 cuts P1 scores on.

This module is a *channel*, not an evaluation: it places nothing and writes no dataset. Its
consumer is P1 re-run unchanged (`--channel typed`), so the measurement is fixed and only the
channel moves.

Usage (inspect one paragraph, which is how the worked example above is checked):
    PYTHONPATH=. uv run python -m scripts.s6c_group_c_typed_formula_channel \\
        --explain 1629-09-22 --paragraph 4
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, Iterable, NamedTuple

from data_io import load
from scripts._republic_resolution_phrase_vocab import (
    CONSTITUENT_PHRASES,
    DECISION_FRAMES,
    OPENING_FRAMES,
)
from scripts.s4_paragraph_axis_baseline import PHRASE_SEARCH_CONFIG

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

S2_PHRASE_DATASET = "s2_anchor_phrase_inventory"
S4_PHRASE_DATASET = "s4_opening_phrase_candidates"

PERIOD_START = 1626
PERIOD_END = 1630

INTAKE = "intake"
DECISION = "decision"
CONSTITUENT = "constituent"
UNCLASSIFIED = "unclassified"

# Token-level fuzzy threshold. See the module docstring: the searcher's phrase-level 0.85 is too
# strict per token because 17th-century orthographic variation is per-token and compounds.
TOKEN_SIMILARITY = 0.72
# How many of the n-gram's own tokens may sit between two consecutive frame tokens. 2, because
# `syn in de vergaderinge gecompareert` realises `Sijn ter Vergaderinge gecompareert` with `in de`
# standing where `ter` stands.
MAX_CANDIDATE_SKIP = 2
# How far into the n-gram the frame may start. 1, because a formula may carry one leading adverb
# (`noch ontfangen een missive van` realises `Ontfangen een missive vanden`) but a formula that
# starts three tokens in is not what opens the resolution.
MAX_LEAD_SKIP = 1

# Tokens that carry no formula identity on their own. Two jobs: an n-gram must align at least one
# token *outside* this set to attach to a frame at all -- which is what keeps bare `is` / `synde`
# / `opt`, live members of the old channel, from inheriting a class they do not earn -- and a
# frame's own function words may be skipped when the n-gram writes something else in their place.
# Folded below (`FUNCTION_WORDS`) so it compares against folded tokens rather than raw spellings.
_FUNCTION_WORDS_RAW = (
    "de", "den", "der", "des", "het", "t", "d", "een", "eene", "van", "vande", "vanden",
    "vander", "ende", "en", "is", "sijn", "syn", "zijn", "sijnde", "synde", "zijnde", "te",
    "ter", "ten", "tot", "op", "opt", "opte", "opde", "aen", "aende", "aenden", "in", "inde",
    "by", "bij", "byden", "met", "voor", "dat", "die", "dye", "haer", "hare", "selve", "noch",
    "als", "om", "of", "ofte", "sal", "soo", "sijnen", "wert", "worden", "zyn", "zynde",
    "alhier", "mede", "voorts", "wederom", "nochmael", "item", "oock",
)

# Clause terminators as they appear in this HTR, including the 17th-century virgule.
CLAUSE_TERMINATORS = ".,;:/|"

# The participial construction (PLAN.md 2026-10-05, 35.8% of gold mid_paragraph cuts). Written as
# two patterns over folded text because it is productive: a phrase list cannot hold it, which is
# why the old frequency inventory captured the bare stem `synde` (count 740) instead.
#
# The two auxiliaries are deliberately different. The *inverted* construction (`Gelesen synde de
# requeste van`, `Nochmael geresumeert synde t'versouck`) takes the present participle `zijnde`
# and only that: allowing the finite `syn`/`zijn` there matches `geschreven in syn[e]...`, where
# `syn` is the possessive pronoun and there is no participial clause at all. The *forward*
# construction does take the finite plural (`Syn wederom ter Vergaderinge gecompareert`), so it
# admits both -- the looser of the two patterns, and the one to look at first if the pattern
# facet underperforms.
AUXILIARY_PARTICIPLE = r"(?:synde|sijnde|zijnde|sinde|zynde)"
AUXILIARY_FINITE = rf"(?:{AUXILIARY_PARTICIPLE}|syn|sijn|zijn)"
# A past participle: a prefixed stem with a participial ending. The ending matters -- it is what
# keeps nouns like `versouck` (ends -k) out of the pattern while admitting `geleyt`, `gelesen`,
# `gecommuniceert`, `geresumeert`, `gecompareert`, `gerapporteert`.
PARTICIPLE = r"(?:ge|ver|be|ont|her|aen|over|uyt|in)[a-z]{3,}(?:t|d|en|rt)"
# Interposed material between auxiliary and participle: `Syn wederom ter Vergaderinge gecompareert`.
FILLER = r"(?:\s+[a-z']{1,14}){0,3}"
PARTICIPIAL_PATTERNS = (
    ("forward", re.compile(rf"\b{AUXILIARY_FINITE}\b{FILLER}\s+\b{PARTICIPLE}\b")),
    ("inverted", re.compile(rf"\b{PARTICIPLE}\b{FILLER}\s+\b{AUXILIARY_PARTICIPLE}\b")),
)


# --------------------------------------------------------------- orthographic normalisation


_FOLDINGS = (
    ("ij", "y"),
    ("ck", "k"),
    ("gh", "g"),
    ("ae", "a"),
    ("ue", "u"),
    ("uy", "ui"),
    ("y", "i"),
    ("z", "s"),
    ("v", "u"),
    ("ph", "f"),
)


@lru_cache(maxsize=65536)
def fold(token: str) -> str:
    """Fold 17th-century / printed-era orthographic variation onto one spelling.

    Not a lemmatiser and not reversible -- it exists so that `geaduyseert` and `geadviseert`, or
    `versouck` and `verzoeck`, compare as the same token. `v`->`u` is included because this period
    writes `u` for intervocalic `v` (`geaduyseert`); it is applied after `uy`->`ui` so the two do
    not interfere.
    """
    text = unicodedata.normalize("NFKD", token.lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "", text)
    for source, target in _FOLDINGS:
        text = text.replace(source, target)
    return text


def fold_tokens(phrase: str) -> tuple[str, ...]:
    return tuple(folded for folded in (fold(token) for token in phrase.split()) if folded)


FUNCTION_WORDS = frozenset(fold(word) for word in _FUNCTION_WORDS_RAW)


def fold_text_preserving_offsets(text: str) -> str:
    """Lowercase, punctuation -> space, **one output character per input character**.

    Offsets in the result must be offsets in `text`, because the participial pattern matches here
    and then reads terminators and snaps clause starts in the original. So this does not use
    `unicodedata.normalize`, which is not length-preserving, and it leaves any character whose
    `lower()` is not a single character alone.
    """
    characters = []
    for char in text:
        lowered = char.lower()
        if len(lowered) != 1:
            lowered = char
        if lowered.isascii() and (lowered.isalnum() or lowered.isspace() or lowered == "'"):
            characters.append(lowered)
        else:
            characters.append(" ")
    return "".join(characters)


@lru_cache(maxsize=1 << 20)
def tokens_similar(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > max(3, min(len(left), len(right))):
        return False
    return SequenceMatcher(None, left, right).ratio() >= TOKEN_SIMILARITY


# ------------------------------------------------------------------------ frame attachment


@dataclass(frozen=True)
class Frame:
    """One sanctioning REPUBLIC form, flattened out of its entry.

    Flattened per *form* rather than per entry because variants are not prefix-extensions of the
    head phrase and so cannot share its matching behaviour -- `Wederom in deliberatie geleijt
    zijnde` is a variant of `Ter Vergaderinge van haer Ho: Mo: in deliberatie gebracht`.
    """

    form: str
    head: str
    formula_class: str
    max_start_offset: int
    source_list: str
    folded: tuple[str, ...]


@dataclass(frozen=True)
class Attachment:
    frame: Frame
    aligned_tokens: int
    coverage: float
    mean_similarity: float

    @property
    def rank(self) -> tuple[int, float, float]:
        """More of a sanctioned formula realised beats a closer match on less of one.

        `aligned_tokens` first, because it measures how much of the formula the n-gram actually
        is; `coverage` second, so a complete short form (`Is goetgevonden`, 2/2) outranks a
        truncated long one (`is goedgevonden ende verstaan`, 2/4) at equal alignment; similarity
        only breaks remaining ties.
        """
        return (self.aligned_tokens, self.coverage, self.mean_similarity)


def in_period(entry: dict[str, Any]) -> bool:
    start, end = entry.get("start_year"), entry.get("end_year")
    if start is None or end is None:
        return True  # REPUBLIC gives decision frames no range; treat as period-neutral.
    return start <= PERIOD_END and end >= PERIOD_START


def build_frames() -> list[Frame]:
    """Every sanctioning form: in-period openings, decisions, and the constituent negatives."""
    frames: list[Frame] = []
    for entry in OPENING_FRAMES:
        if not in_period(entry):
            continue
        for form in entry["forms"]:
            folded = fold_tokens(form)
            if folded:
                frames.append(
                    Frame(form, entry["phrase"], INTAKE, int(entry["max_start_offset"]),
                          "proposition_opening_phrases", folded)
                )
    for entry in DECISION_FRAMES:
        for form in entry["forms"]:
            folded = fold_tokens(form)
            if folded:
                # REPUBLIC curates no offset for decisions; they are clause-initial where they
                # open at all, so they take the openings' dominant value.
                frames.append(Frame(form, entry["phrase"], DECISION, 2, "decision_phrases", folded))
    for entry in CONSTITUENT_PHRASES:
        for form in entry["forms"]:
            folded = fold_tokens(form)
            if folded:
                frames.append(
                    Frame(form, entry["phrase"], CONSTITUENT, 0, entry["source_list"], folded)
                )
    return frames


def align_form(candidate: tuple[str, ...], form: tuple[str, ...]) -> tuple[int, float, bool]:
    """`(aligned_tokens, mean_similarity, aligned_a_content_token)`: how much of `form`, read from
    its own start, the n-gram realises.

    Three constraints, each put there by a case rather than by tuning:

    * **The form is read from its start, not matched anywhere inside it.** These are *openings*:
      what begins the resolution must begin the formula. Dropping this is what lets `de heeren
      van` reach into `Die heeren Gedepden. vande Provincien rapporteren` and come out typed as an
      intake formula; with it, that n-gram aligns 2 tokens there against a complete 2-of-2 match
      on `prefix_phrases`' `de Heeren`, and the coverage tie-break purges it correctly.
    * **The n-gram may skip up to `MAX_CANDIDATE_SKIP` of its own tokens between two frame
      tokens,** because surface realisation varies inside the formula: `syn in de vergaderinge
      gecompareert` writes `in de` where `Sijn ter Vergaderinge gecompareert` writes `ter`.
    * **The frame may start up to `MAX_LEAD_SKIP` tokens into the n-gram,** because a formula
      takes a leading adverb: `noch ontfangen een missive van` realises `Ontfangen een missive
      vanden` in full, and is one of the formulas PLAN.md names as missed by the old stem test.

    A frame token the n-gram does not realise is fatal unless it is a function word, which may be
    skipped -- `ter` above. A content token of the frame going unrealised ends the alignment,
    which is what keeps the alignment from wandering down a long frame.
    """
    aligned = 0
    total = 0.0
    content = False
    next_candidate = 0
    first_alignment: int | None = None
    for form_token in form:
        hit = None
        for skip in range(MAX_CANDIDATE_SKIP + 1):
            index = next_candidate + skip
            if index >= len(candidate):
                break
            if tokens_similar(candidate[index], form_token):
                hit = index
                break
        if hit is None:
            if form_token in FUNCTION_WORDS:
                continue
            break
        if first_alignment is None:
            first_alignment = hit
            if hit > MAX_LEAD_SKIP:
                return 0, 0.0, False
        aligned += 1
        total += (
            1.0
            if candidate[hit] == form_token
            else SequenceMatcher(None, candidate[hit], form_token).ratio()
        )
        content = content or candidate[hit] not in FUNCTION_WORDS
        next_candidate = hit + 1
    return aligned, (total / aligned if aligned else 0.0), content


def attach(phrase: str, frames: Iterable[Frame]) -> Attachment | None:
    """The strongest frame this phrase realises, or None if it realises no formula at all.

    None covers both "attaches to nothing" and "attaches only to function words" -- the two ways
    the old inventory admitted material that carries no opening evidence.
    """
    folded = fold_tokens(phrase)
    if not folded:
        return None
    best: Attachment | None = None
    for frame in frames:
        aligned, similarity, content = align_form(folded, frame.folded)
        if not aligned or not content:
            continue
        attachment = Attachment(frame, aligned, aligned / len(frame.folded), similarity)
        if best is None or attachment.rank > best.rank:
            best = attachment
    return best


# ------------------------------------------------------------------------------- the channel


class Candidate(NamedTuple):
    """One interior position a Group C channel proposes as a resolution opening.

    `(offset, similarity, phrase)` lead, because those are the three fields P1's nulls and
    reporting use and the old channel's tuples carried; the typing follows. Both channels in this
    module emit this type, which is what lets P1 select a channel without its population, its
    nulls or its facets changing.
    """

    offset: int
    similarity: float
    phrase: str
    formula_class: str = UNCLASSIFIED
    frame: str = ""
    source: str = ""
    specificity: int = 0

    @property
    def rank(self) -> tuple[int, int, int, float, int]:
        """The channel's own preference order, declared from the structure, not fitted.

        Class first (the ordering rule's own direction), then phrase evidence over pattern
        evidence (the more specific observation), then how much of a sanctioned formula the match
        realises, then similarity, then the earlier position.
        """
        class_priority = 0 if self.formula_class != DECISION else 1
        source_priority = 0 if self.source != "pattern" else 1
        return (-class_priority, -source_priority, self.specificity, self.similarity, -self.offset)


@dataclass(frozen=True)
class PhraseSpec:
    formula_class: str
    frame: str
    max_start_offset: int
    specificity: int
    source: str


def empirical_phrases() -> list[str]:
    """Our own n-grams: `s2`'s top-20 openings and `s4`'s count-ranked candidates.

    Taken **unfiltered** -- no word-count floor, no frequency cut. Admissibility is the frame
    attachment below, and the point of this rebuild is that `>= 3 words` is the wrong filter
    (`de heeren van` sails through it) while frequency is the wrong signal entirely.
    """
    s2 = [entry["phrase"] for entry in load(S2_PHRASE_DATASET)["opening_phrases_top_20"]]
    s4 = [entry["phrase"] for entry in load(S4_PHRASE_DATASET)[0]["candidates"]]
    return sorted(set(s2) | set(s4))


def clause_start(text: str, offset: int, window: int) -> int:
    """Snap `offset` back to the clause start within `window` characters, else leave it.

    This is `max_start_offset` translated: a frame with offset budget `m` matched at `f` asserts
    its resolution started in `[f - m, f]`, and the only structural landmark inside that window is
    the end of the preceding clause. Used as a snap target only, never as a filter -- the
    terminator signal is too weak to reject on (72.6% vs 54.9%).
    """
    if window <= 0:
        return offset
    low = max(0, offset - window)
    best = offset
    for index in range(offset - 1, low - 1, -1):
        if text[index] in CLAUSE_TERMINATORS:
            candidate = index + 1
            while candidate < offset and text[candidate].isspace():
                candidate += 1
            best = candidate
            break
    return best


class TypedFormulaChannel:
    """Group C as a typed, period-filtered formula searcher.

    Interface is the pair P1 consumes -- `candidates(axis_id, text)` and `pick(candidates)` -- so
    the harness, its population and its nulls stay untouched.
    """

    label = "typed formula searcher (REPUBLIC frames for class, our forms as variants)"

    def __init__(
        self, *, use_pattern: bool = True, use_ordering: bool = True, legacy_rank: bool = False
    ) -> None:
        self.frames = build_frames()
        self.use_pattern = use_pattern
        self.use_ordering = use_ordering
        self.legacy_rank = legacy_rank
        self.specs: dict[str, PhraseSpec] = {}
        self.purged: dict[str, str] = {}
        self._admit_empirical()
        self._admit_republic()
        self.searcher = FuzzyPhraseSearcher(sorted(self.specs), config=PHRASE_SEARCH_CONFIG)
        self.participle_classes = self._participle_classes()

    # -- admission ---------------------------------------------------------------------

    def _admit_empirical(self) -> None:
        for phrase in empirical_phrases():
            attachment = attach(phrase, self.frames)
            if attachment is None:
                self.purged[phrase] = "attaches to no sanctioned frame"
                continue
            if attachment.frame.formula_class == CONSTITUENT:
                self.purged[phrase] = f"{attachment.frame.source_list}: {attachment.frame.form!r}"
                continue
            self._record(
                phrase,
                PhraseSpec(
                    attachment.frame.formula_class,
                    attachment.frame.head,
                    attachment.frame.max_start_offset,
                    attachment.aligned_tokens,
                    "empirical",
                ),
            )

    def _admit_republic(self) -> None:
        """REPUBLIC's own in-period forms, carried alongside ours.

        They are in printed orthography and will mostly not fire on this HTR -- that is the
        measured weakness the empirical forms exist to cover -- but they cost nothing and type
        themselves.
        """
        for frame in self.frames:
            if frame.formula_class == CONSTITUENT:
                continue
            self._record(
                frame.form.strip(),
                PhraseSpec(
                    frame.formula_class, frame.head, frame.max_start_offset,
                    len(frame.folded), "republic",
                ),
            )

    def _record(self, phrase: str, spec: PhraseSpec) -> None:
        phrase = phrase.strip()
        if not phrase:
            return
        existing = self.specs.get(phrase)
        if existing is None or (spec.specificity, spec.source == "republic") > (
            existing.specificity, existing.source == "republic"
        ):
            self.specs[phrase] = spec

    def _participle_classes(self) -> dict[str, str]:
        """Participle -> class, derived from REPUBLIC occurrence rather than hand-listed.

        A participle appearing in a decision form types the construction as decision, which is how
        `WAAR op gedelibereert zijnde` stays a decision while `Gelesen synde de requeste van` is
        an intake. A participle REPUBLIC does not know stays `intake`: the *construction* is
        sanctioned even where the early-period participle is not, which is this module's whole
        division of labour.
        """
        classes: dict[str, str] = {}
        for frame in self.frames:
            if frame.formula_class == CONSTITUENT:
                continue
            for token in frame.folded:
                if re.fullmatch(PARTICIPLE, token):
                    if frame.formula_class == DECISION:
                        classes[token] = DECISION
                    else:
                        classes.setdefault(token, INTAKE)
        return classes

    # -- matching ----------------------------------------------------------------------

    def _phrase_matches(self, axis_id: str, text: str) -> list[Candidate]:
        matches = self.searcher.find_matches({"id": axis_id, "text": text})
        found: list[Candidate] = []
        for match in matches:
            phrase = match.phrase.phrase_string
            spec = self.specs.get(phrase)
            if spec is None:
                continue
            offset = clause_start(text, int(match.offset), spec.max_start_offset)
            found.append(
                Candidate(
                    offset, float(match.levenshtein_similarity), phrase, spec.formula_class,
                    spec.frame, spec.source, spec.specificity,
                )
            )
        return found

    def _pattern_matches(self, text: str) -> list[Candidate]:
        """The participial construction, snapped to its clause start.

        Snapped without an offset budget, because a participial clause opens at its clause
        boundary by construction: the pre-field material the pattern cannot see (`in deliberatie`,
        `Nochmael`, `Wederom`) sits inside the same clause. That is a claim about the grammar, not
        a tuned window, so it costs no free parameter.

        A match whose own span crosses a clause terminator is rejected, because then the two
        halves are not one construction. This is what it rules out, observed on `1629-09-22`
        paragraph 4: `gedelibereert synde, is goetgevonden ende verstaen` was matched by the
        forward pattern as `synde ... goetgevonden` and typed intake, when the `synde` in fact
        closes the preceding inverted clause and `is goetgevonden ende verstaen` is the decision.
        """
        folded = fold_text_preserving_offsets(text)
        found: list[Candidate] = []
        for name, pattern in PARTICIPIAL_PATTERNS:
            for match in pattern.finditer(folded):
                surface = match.group(0)
                span = text[match.start() : match.end()]
                if any(char in CLAUSE_TERMINATORS for char in span):
                    continue
                participle = next(
                    (fold(token) for token in surface.split() if re.fullmatch(PARTICIPLE, token)),
                    None,
                )
                formula_class = self.participle_classes.get(participle or "", INTAKE)
                offset = clause_start(text, match.start(), len(text))
                found.append(
                    Candidate(
                        offset, 1.0, f"<participial:{name}> {surface}", formula_class,
                        f"participial construction ({name})", "pattern",
                        len(surface.split()),
                    )
                )
        return found

    def _apply_ordering(self, found: list[Candidate]) -> list[Candidate]:
        """Suppress decision-class candidates that an intake-class match precedes.

        Measured rules (PLAN.md 2026-10-05): intake precedes decision in 97.0% of paragraphs
        holding both, and a decision formula opens a resolution only where no intake formula is
        available (96.7%). Offset-0 matches participate here even though they are never returned
        as candidates -- the paragraph's own opening is precisely the intake that makes a following
        decision formula interior rather than initial.
        """
        first_intake = min(
            (candidate.offset for candidate in found if candidate.formula_class == INTAKE),
            default=None,
        )
        if first_intake is None:
            return found
        return [
            candidate
            for candidate in found
            if candidate.formula_class == INTAKE or candidate.offset <= first_intake
        ]

    def candidates(self, axis_id: str, text: str) -> list[Candidate]:
        """Distinct interior offsets, strongest match per offset, in text order.

        Same contract and the same deduplication key as the old channel's `interior_candidates`,
        so P1's count-matched null stays comparable: one opening reported by three nested phrases
        is one candidate, not three. Interior means `0 < offset < len(text)` -- an offset-0 match
        is the paragraph's own opening, which every consumer already has from the paragraph
        boundary and which cannot divide it.

        Order of operations matters, and getting it wrong was a real bug here. An offset's class
        is settled **first**, by whichever match realises most of a sanctioned formula there --
        class-blind, so the shorter form cannot outvote the longer one. Only then does the
        ordering rule run. Resolving class by preference instead let REPUBLIC's 2-token
        `Is goetgevonden` (labelled `proposition_opening` in its own list) type offset 1669 of
        `1629-09-22` paragraph 4 as an intake and shield it from suppression, when the text there
        is `is goetgevonden ende verstaen datmen` -- the 4-token decision formula.
        """
        found = self._phrase_matches(axis_id, text)
        if self.use_pattern:
            found.extend(self._pattern_matches(text))
        found = self._resolve_classes(found)
        if self.use_ordering:
            found = self._apply_ordering(found)
        return [
            candidate for candidate in sorted(found) if 0 < candidate.offset < len(text)
        ]

    @staticmethod
    def _resolve_classes(found: list[Candidate]) -> list[Candidate]:
        """One candidate per offset: the match realising most of a sanctioned formula there.

        Class-blind by design -- see `candidates`. Similarity breaks ties, and a phrase match
        breaks a remaining tie against a pattern match as the more specific observation.
        """
        best: dict[int, Candidate] = {}
        for candidate in found:
            incumbent = best.get(candidate.offset)
            key = (candidate.specificity, candidate.similarity, candidate.source != "pattern")
            if incumbent is None or key > (
                incumbent.specificity, incumbent.similarity, incumbent.source != "pattern"
            ):
                best[candidate.offset] = candidate
        return list(best.values())

    def pick(self, candidates: list[Candidate]) -> Candidate:
        """The candidate the channel itself would choose, with no reference to gold.

        Typing and ordering do the work here, not the score -- which is the whole correction. The
        old channel's `max` on `(similarity, length)` picked `de heeren van` at similarity 1.000
        over the real formula 1,249 characters away, because similarity rewards exact matches on
        throwaway strings over approximate matches on real ones.

        `legacy_rank` keeps the typed candidate *set* and reverts to that similarity ranking,
        which is the ablation that separates "the rebuild found better candidates" from "the
        rebuild chooses better among them".
        """
        if self.legacy_rank:
            return max(
                candidates,
                key=lambda candidate: (candidate.similarity, len(candidate.phrase), -candidate.offset),
            )
        return max(candidates, key=lambda candidate: candidate.rank)


class LegacyPhraseChannel:
    """Group C exactly as it was defined before this rebuild -- the control arm.

    Moved here verbatim from `s6c_group_c_interior_offset_calibration.interior_candidates` and
    `ranked_pick` so both channels present one interface and P1 can switch between them without
    the harness knowing which it holds. Behaviour is unchanged, which the recorded P1 numbers
    regression-check: `--channel legacy --min-words 1` must still report ranked ratio 1.01 /
    39-of-69, and `--min-words 3` ranked 0.78, nearest 0.49, assignment 0.45.

    `build_combined_c_searcher` takes `s2_anchor_phrase_inventory`'s top 20 **unfiltered** and
    `s4_opening_phrase_candidates` at `word_count >= 3`, so `is` / `synde` / `ontfangen` / `opt`
    are live members; `min_words` is the post-hoc floor P1 added to measure that.
    """

    def __init__(self, min_words: int = 1) -> None:
        from scripts.s6c_group_c_attribution_check import build_combined_c_searcher

        self.min_words = min_words
        self.searcher = build_combined_c_searcher()
        self.label = (
            "Group C as defined today (s2 top-20 unfiltered + s4 >=3 words)"
            if min_words <= 1
            else f"Group C restricted to phrases of >= {min_words} words"
        )

    def candidates(self, axis_id: str, text: str) -> list[Candidate]:
        matches = self.searcher.find_matches({"id": axis_id, "text": text})
        best: dict[int, tuple[tuple[float, int], str]] = {}
        for match in matches:
            offset = int(match.offset)
            if not 0 < offset < len(text):
                continue
            phrase = match.phrase.phrase_string
            if len(phrase.split()) < self.min_words:
                continue
            score = (float(match.levenshtein_similarity), len(phrase))
            if offset not in best or score > best[offset][0]:
                best[offset] = (score, phrase)
        return [
            Candidate(offset, best[offset][0][0], best[offset][1], UNCLASSIFIED, "", "legacy", 0)
            for offset in sorted(best)
        ]

    def pick(self, candidates: list[Candidate]) -> Candidate:
        """Highest Levenshtein similarity, longer phrase as tie-break -- `phrase_hits`'s own key."""
        return max(
            candidates,
            key=lambda candidate: (candidate.similarity, len(candidate.phrase), -candidate.offset),
        )


def build_channel(name: str, min_words: int = 1) -> Any:
    if name == "legacy":
        return LegacyPhraseChannel(min_words)
    if name == "typed":
        return TypedFormulaChannel()
    if name == "typed-no-ordering":
        return TypedFormulaChannel(use_ordering=False)
    if name == "typed-no-pattern":
        return TypedFormulaChannel(use_pattern=False)
    if name == "typed-legacy-rank":
        return TypedFormulaChannel(legacy_rank=True)
    raise ValueError(f"unknown channel {name!r}")


# --------------------------------------------------------------------------------- explain


def explain(date: str, paragraph_index: int) -> None:
    """Dump one paragraph's typed candidate set -- how the worked example is checked."""
    from scripts.build_pathology_corpus import load_axis_indexes
    from scripts.s4_corpus_paragraph_predictions import axis_for_date

    channel = TypedFormulaChannel()
    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
    if not 0 <= paragraph_index < len(axis):
        raise SystemExit(f"{date}: paragraph {paragraph_index} outside axis of {len(axis)}")
    record = axis[paragraph_index]
    text = record["text"]
    print(f"{date} paragraph {paragraph_index} ({len(text)} chars, axis_id={record['axis_id']})")
    print(f"inventory: {len(channel.specs)} admitted phrases, {len(channel.purged)} purged")
    raw = channel._phrase_matches(record["axis_id"], text)
    if channel.use_pattern:
        raw.extend(channel._pattern_matches(text))
    resolved = {candidate.offset: candidate for candidate in channel._resolve_classes(raw)}
    kept = channel.candidates(record["axis_id"], text)
    kept_offsets = {candidate.offset for candidate in kept}
    print(f"{len(raw)} raw matches -> {len(resolved)} offsets -> {len(kept)} interior candidates")
    for offset in sorted(resolved):
        candidate = resolved[offset]
        if offset in kept_offsets:
            state = "candidate"
        elif offset == 0 or offset >= len(text):
            state = "not interior"
        else:
            state = "suppressed (ordering)"
        print(
            f"  {offset:6} {candidate.formula_class:10} {state:21} "
            f"sim={candidate.similarity:.3f} src={candidate.source:9} "
            f"spec={candidate.specificity} {candidate.phrase!r} <- {candidate.frame!r}"
        )
    if kept:
        pick = channel.pick(kept)
        print(f"  channel's own pick: offset {pick.offset} [{pick.formula_class}] {pick.phrase!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--explain", metavar="DATE", help="dump one paragraph's typed candidates")
    parser.add_argument("--paragraph", type=int, default=0, help="paragraph stream index for --explain")
    parser.add_argument("--purged", action="store_true", help="list the purged empirical n-grams")
    args = parser.parse_args()

    if args.explain:
        explain(args.explain, args.paragraph)
        return

    channel = TypedFormulaChannel()
    intake = sum(1 for spec in channel.specs.values() if spec.formula_class == INTAKE)
    empirical = sum(1 for spec in channel.specs.values() if spec.source == "empirical")
    print(f"frames: {sum(1 for f in channel.frames if f.formula_class == INTAKE)} intake forms, "
          f"{sum(1 for f in channel.frames if f.formula_class == DECISION)} decision forms, "
          f"{sum(1 for f in channel.frames if f.formula_class == CONSTITUENT)} constituent forms")
    print(f"admitted: {len(channel.specs)} phrases ({empirical} empirical, "
          f"{len(channel.specs) - empirical} REPUBLIC), {intake} intake / {len(channel.specs) - intake} decision")
    print(f"purged:   {len(channel.purged)} empirical n-grams")
    print(f"participle classes derived from REPUBLIC: {len(channel.participle_classes)}")
    if args.purged:
        for phrase, reason in sorted(channel.purged.items()):
            print(f"  {phrase!r}: {reason}")


if __name__ == "__main__":
    main()
