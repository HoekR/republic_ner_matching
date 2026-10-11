#!/usr/bin/env python3
"""Disambiguate duplicate-claimed sessions by their own embedded date headings (user, 2026-10-05).

`resolution_concordance_1626_1630` lets **67 of 1,053** resolved sessions be claimed by more than
one enriched date (1,884 enriched resolutions, including 1,064 of the corpus's 1,137
`cross_day_shift` rows; competing claims are always within 5 days). The user's framing: disambiguate
these **as anchors, not as ownership**. A duplicate claim is not automatically an error -- an
archival session can legitimately carry two calendar days' business. `session-3185-num-56` holds
both 27 and 28 March 1626, with the 28th's heading recorded *inside* it as plain continuing text,
and the archive's own catalog files the whole thing under the 27th (`docs/DECISIONS.md` 2026-10-02).

So the operation is to **locate each claimant's content region inside the session**, not to award
the session to one date. This script runs the channel the user identified as carrying the signal:
the embedded heading itself. A heading does not merely prove the session is shared -- it *locates
the split*, which is what makes it stronger than any concentration measure.

Instrument: `fuzzy_search`'s wildcard date phrases (`"den .. Martij 1626"`), the same library and
HTR-tolerant matching the project already uses for Group C phrases. Dates in this corpus appear as
a Latin weekday plus `den` + day + month + year, with the day in Roman numerals using terminal `j`
(`"Sabbathi den xxviijen. Martij 1626"`), so both Roman and Arabic day forms are generated, with
Latin and Dutch month names.

Deliberately NOT in this script: the entity channel. This is tier 1 of the design in `PLAN.md`
(track 5) -- run the cheap, exact, split-locating channel first and report **how much is left**,
which is what the user asked for. The remainder is what the entity channel then has to earn.

Validation case, from the user's own archive check rather than from this script's own output:
`session-3185-num-56` must yield a 28 March 1626 heading inside it. Note that session is *not* one
of the 67 -- our ledger gives it a single date -- so it is a true held-out check, and the fact that
the same scan finds unrecognised shared sessions outside the duplicate population is a result in
its own right.

Diagnostic only: no dataset write, no manifest entry, no placement or status change.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6_duplicate_session_date_headings
    PYTHONPATH=. uv run python -m scripts.s6_duplicate_session_date_headings --validate-only
"""

from __future__ import annotations

import argparse
import re
from calendar import monthrange
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from data_io import load
from scripts._republic_date_vocab import DAY_TOKENS, MONTH_NAMES, WEEKDAY_NAMES

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

# Relative day tokens in REPUBLIC's table: 0 = last of month, -1 = second-to-last.
# They must not be compared as literal calendar days (day 0 is invalid).
RELATIVE_LAST = 0
RELATIVE_SECOND_LAST = -1
RELATIVE_DAY_SPELLINGS = {
    RELATIVE_LAST: ["lesten", "leste", "Ultima"],
    RELATIVE_SECOND_LAST: ["naestlesten", "naestleste", "nalesten", "naleste"],
}

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
VALIDATION_SESSION = "session-3185-num-56"
VALIDATION_DATE = "1626-03-28"

# Date vocabularies come from the REPUBLIC project (see `scripts/_republic_date_vocab.py` for the
# source commit and why they are copied rather than imported). Using them instead of a hand-rolled
# set matters: REPUBLIC's *handwritten* variants carry forms this script would never have guessed
# (`Mercurij`, `Sabati`, `Saterdach`, `Doica`) and its day table decodes HTR confusions such as
# `1xen` -> 9 and `vjen` -> 6 by exact lookup rather than Roman arithmetic.
WEEKDAY_WINDOW = 30  # chars before a heading match to look in for its weekday

# Checked against two source-attested headings before use: `1626-03-28` is written `Sabbathi` and
# `pd.Period` gives Saturday; `1626-01-29` is written `Jovis` and gives Thursday. So this corpus's
# weekday labels agree with proleptic Gregorian and need no Julian correction (n=2, not a proof).
WEEKDAY_LOOKUP = {name.lower(): index for name, index in WEEKDAY_NAMES.items()}
MONTH_TOKENS: dict[int, list[str]] = {}
for _name, _month in MONTH_NAMES.items():
    MONTH_TOKENS.setdefault(_month, []).append(_name)
DAY_SPELLINGS: dict[int, list[str]] = {}
for _token, _day in DAY_TOKENS.items():
    DAY_SPELLINGS.setdefault(_day, []).append(_token)

SEARCH_CONFIG = {
    "char_match_threshold": 0.7,
    "ngram_threshold": 0.5,
    "levenshtein_threshold": 0.7,
    "ignorecase": True,
    "ngram_size": 3,
    "skip_size": 1,
}


def parse_day_token(token: str) -> int | None:
    """Day number for a heading's own day token, by exact lookup in REPUBLIC's day table.

    **This is the discriminative step, and it is deliberately exact, not fuzzy.** A first version of
    this script tested each candidate date's full phrase with fuzzy matching and appeared to
    disambiguate 43 of 67 sessions. That was an artifact: adjacent days' Roman numerals
    (`xxviij`/`xxix`/`xxxj`) differ by one character and so fall inside any useful fuzzy threshold,
    making a *single* heading match several candidate dates at the same offset. Checked directly,
    **0 of 41 apparent "both headings present" verdicts had the claimants' hits at separate sites**.
    Finding a heading and attributing it to a date are different problems; only the second
    disambiguates. So the frame is matched fuzzily (HTR noise) while the day is looked up exactly.
    """
    cleaned = token.strip().lower().strip(".,:;")
    for candidate in (token.strip(), token.strip().strip(".,:;"), cleaned, cleaned + "."):
        if candidate in DAY_TOKENS:
            return DAY_TOKENS[candidate]
    for spelling, day in DAY_TOKENS.items():
        if spelling.lower() == cleaned:
            return day
    return None


def weekday_before(text: str, offset: int) -> int | None:
    """`dayofweek` of the weekday name immediately preceding a heading match, if any.

    The weekday is an **independent** constraint on an already-located heading (user suggestion,
    2026-10-05), which is what makes it valuable: adjacent days differ in weekday exactly where their
    Roman numerals collide, so it discriminates where the day token is HTR rubble. It is deliberately
    not used as a search phrase -- `Sabbathi` recurs weekly and would match a session's own opening
    heading as readily as an embedded one.

    HTR noise is handled by stripping non-letters before comparing, so `'J. ovis'` -> `'jovis'`.
    """
    window = text[max(0, offset - WEEKDAY_WINDOW):offset]
    token = re.sub(r"[^a-z]", "", window.lower())
    if not token:
        return None
    best: tuple[int, int] | None = None
    for name, index in WEEKDAY_LOOKUP.items():
        position = token.rfind(name)
        if position >= 0 and (best is None or position > best[0]):
            best = (position, index)
    return None if best is None else best[1]


def resolve_day_token(parsed_day: int | None, period: pd.Period) -> int | None:
    """Map a parsed day token onto a calendar day for ``period``'s month.

    Absolute tokens (1–31) pass through. Relative tokens from REPUBLIC's table
    (``0`` = last of month, ``-1`` = second-to-last) resolve against that month's
    length. Without this, ``lesten`` never verifies against the 28th–31st.
    """
    if parsed_day is None:
        return None
    if parsed_day > 0:
        return parsed_day
    last = monthrange(period.year, period.month)[1]
    if parsed_day == RELATIVE_LAST:
        return last
    if parsed_day == RELATIVE_SECOND_LAST:
        return last - 1
    return None


def matched_year(matched: str) -> int | None:
    """Year numeral inside a heading match, if any (relative-day false-positive guard)."""
    years = re.findall(r"\b(1[5-7]\d{2})\b", matched)
    if not years:
        return None
    return int(years[-1])


def date_phrases(period: pd.Period) -> list[str]:
    """Heading phrases for one date, over every day and month spelling REPUBLIC records.

    The weekday is excluded here on purpose and applied afterwards as a cross-check -- see
    `weekday_before`. Relative month-end spellings (``lesten`` / ``naestlesten``) are added
    only when this date is the last / second-to-last day of its month.
    """
    days = set(DAY_SPELLINGS.get(period.day, [])) | {str(period.day), f"{period.day}."}
    last = monthrange(period.year, period.month)[1]
    if period.day == last:
        days.update(RELATIVE_DAY_SPELLINGS[RELATIVE_LAST])
    if period.day == last - 1:
        days.update(RELATIVE_DAY_SPELLINGS[RELATIVE_SECOND_LAST])
    months = MONTH_TOKENS.get(period.month, [])
    phrases = {f"den {d} {m} {period.year}" for d in days for m in months}
    return sorted(p for p in phrases if len(p) >= 12)


def find_headings(paragraphs: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    """Headings for one date: fuzzy phrase match to **locate**, exact day parse to **verify**.

    Stage 1 accepts HTR noise, which is what makes the heading findable at all. Stage 2 rejects the
    adjacent-day collisions stage 1 cannot avoid, by parsing the matched text's own day token and
    requiring it to equal this date's day. Hits failing stage 2 are returned with
    `verified: False` so the collision rate stays measurable rather than invisible.

    Relative day tokens (``lesten`` → last of month) resolve against the target month. They also
    require the matched year to equal the target year, so prose like ``missive den lesten May
    ontfangen`` cannot verify as a session heading.
    """
    period = pd.Period(date, freq="D")
    phrases = date_phrases(period)
    if not phrases:
        return []
    searcher = FuzzyPhraseSearcher(phrase_list=phrases, config=SEARCH_CONFIG)
    hits = []
    for position, record in enumerate(paragraphs):
        text = str(record.get("text") or "")
        if not text:
            continue
        for match in searcher.find_matches(text):
            matched = str(getattr(match, "string", ""))
            raw_day = next(
                (d for d in (parse_day_token(t) for t in matched.split()[1:]) if d is not None),
                None,
            )
            relative = raw_day is not None and raw_day <= RELATIVE_LAST
            parsed_day = resolve_day_token(raw_day, period)
            offset = int(getattr(match, "offset", 0) or 0)
            weekday = weekday_before(text, offset)
            year = matched_year(matched)
            day_ok = parsed_day == period.day
            if relative:
                # Relative tokens are too common in non-heading prose without a year.
                day_ok = bool(day_ok and year == period.year)
            weekday_ok = None if weekday is None else (weekday == period.dayofweek)
            hits.append({
                "paragraph_position": position,
                "axis_id": record.get("axis_id"),
                "offset": offset,
                "matched": matched,
                "score": float(getattr(match, "levenshtein_similarity", 0.0) or 0.0),
                "parsed_day": parsed_day,
                "raw_day_token": raw_day,
                "weekday_found": weekday,
                "weekday_agrees": weekday_ok,
                # The day numeral and the weekday are independent constraints: a disagreeing weekday
                # vetoes a day match, and an agreeing weekday rescues a hit whose numeral is HTR
                # rubble. Neither alone is enough to accept a hit whose other constraint fails.
                "verified": bool((day_ok and weekday_ok is not False)
                                 or (parsed_day is None and weekday_ok is True)),
                "rescued_by_weekday": bool(parsed_day is None and weekday_ok is True),
                "vetoed_by_weekday": bool(day_ok and weekday_ok is False),
            })
    return hits


def session_paragraphs(axis: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Axis paragraphs grouped by their session id, in reading order."""
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        flat_id = str(record.get("flat_id") or "")
        session = re.sub(r"-resolution-\d+$", "", flat_id)
        if session:
            by_session[session].append(record)
    for session, records in by_session.items():
        records.sort(key=lambda r: (str(r.get("flat_id")), int(r.get("para_index") or 0)))
    return by_session


def duplicate_claims(concordance: pd.DataFrame) -> dict[str, list[str]]:
    """Resolved sessions claimed by more than one enriched date, each date list sorted."""
    pairs = concordance[["enriched_date", "resolved_session_id"]].dropna().drop_duplicates()
    pairs = pairs[pairs["resolved_session_id"].astype(str) != ""]
    grouped = pairs.groupby("resolved_session_id")["enriched_date"].apply(
        lambda dates: sorted(str(d) for d in dates)
    )
    return {session: dates for session, dates in grouped.items() if len(dates) > 1}


def extract_headings(
    paragraphs: list[dict[str, Any]], searcher: FuzzyPhraseSearcher, frames: dict[str, tuple[int, int]]
) -> list[dict[str, Any]]:
    """Every date heading in a session, with the date **read off the text**, not guessed.

    One pass per session. Each hit's own day token is parsed exactly (see `parse_day_token`); hits
    whose day will not parse are returned with `date: None` and counted rather than dropped, so the
    channel's own blind spot stays visible instead of masquerading as absence of a heading.
    """
    headings = []
    for position, record in enumerate(paragraphs):
        text = str(record.get("text") or "")
        if not text:
            continue
        for match in searcher.find_matches(text):
            phrase = str(getattr(getattr(match, "phrase", None), "phrase_string", ""))
            frame = frames.get(phrase)
            if frame is None:
                continue
            month, year = frame
            matched = str(getattr(match, "string", ""))
            tokens = matched.split()
            day = None
            for token in tokens[1:]:  # skip the leading "den"
                day = parse_day_token(token)
                if day is not None:
                    break
            parsed = None
            if day is not None:
                try:
                    parsed = str(pd.Period(f"{year}-{month:02d}-{day:02d}", freq="D"))
                except ValueError:
                    parsed = None
            headings.append({
                "paragraph_position": position,
                "axis_id": record.get("axis_id"),
                "offset": int(getattr(match, "offset", 0) or 0),
                "matched": matched,
                "score": float(getattr(match, "levenshtein_similarity", 0.0) or 0.0),
                "date": parsed,
            })
    return headings


def classify(
    session: str, dates: list[str], by_session: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Verdict for one duplicate-claimed session from verified heading evidence."""
    paragraphs = by_session.get(session) or []
    result = {
        "session": session, "dates": dates, "paragraphs": len(paragraphs),
        "verdict": "no_axis_text" if not paragraphs else "",
        "unverified_hits": 0, "rescued_by_weekday": 0, "vetoed_by_weekday": 0,
        "weekday_present": 0, "hits": 0,
    }
    if not paragraphs:
        return result
    verified: dict[str, list[dict[str, Any]]] = {}
    for date in dates:
        hits = find_headings(paragraphs, date)
        result["unverified_hits"] += sum(1 for h in hits if not h["verified"])
        result["rescued_by_weekday"] += sum(1 for h in hits if h["rescued_by_weekday"])
        result["vetoed_by_weekday"] += sum(1 for h in hits if h["vetoed_by_weekday"])
        result["weekday_present"] += sum(1 for h in hits if h["weekday_agrees"] is not None)
        result["hits"] += len(hits)
        good = [h for h in hits if h["verified"]]
        if good:
            verified[date] = good
    result["claimants_with_heading"] = sorted(verified)

    if len(verified) >= 2:
        later = sorted(verified)[-1]
        first = min(verified[later], key=lambda h: h["paragraph_position"])
        result["verdict"] = "shared_confirmed"
        result["split_at_paragraph"] = first["paragraph_position"]
        result["split_axis_id"] = first["axis_id"]
    elif len(verified) == 1:
        only = next(iter(verified))
        positions = [h["paragraph_position"] for h in verified[only]]
        if only != dates[0] and min(positions) > 0:
            result["verdict"] = "shared_one_heading"
            result["split_at_paragraph"] = min(positions)
        else:
            result["verdict"] = "one_claimant_heading_only"
    elif result["unverified_hits"]:
        result["verdict"] = "hits_but_none_verified"
    else:
        result["verdict"] = "no_heading_signal"
    return result


def validate(by_session: dict[str, list[dict[str, Any]]]) -> bool:
    """Held-out check: `session-3185-num-56` must yield a VERIFIED 1626-03-28 heading."""
    paragraphs = by_session.get(VALIDATION_SESSION) or []
    print(f"validation: {VALIDATION_SESSION} has {len(paragraphs)} axis paragraphs")
    if not paragraphs:
        print("  FAIL -- session absent from the paragraph axis")
        return False
    hits = find_headings(paragraphs, VALIDATION_DATE)
    for hit in hits:
        print(f"  para {hit['paragraph_position']} score {hit['score']:.2f} "
              f"{hit['matched']!r} -> day {hit['parsed_day']} "
              f"{'VERIFIED' if hit['verified'] else 'rejected'}")
    ok = any(h["verified"] for h in hits)
    print(f"  {'PASS' if ok else 'FAIL'} -- {VALIDATION_DATE} "
          f"{'verified in the session text' if ok else 'not verified; verdicts are unproven'}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="run the held-out check and stop")
    args = parser.parse_args()

    axis = load(AXIS_DATASET)
    by_session = session_paragraphs(axis)
    print(f"axis: {len(axis)} paragraphs across {len(by_session)} sessions\n")

    ok = validate(by_session)
    if args.validate_only:
        return
    print()

    concordance = load(CONCORDANCE_DATASET)
    claims = duplicate_claims(concordance)
    print(f"duplicate-claimed sessions: {len(claims)}\n")

    verdicts: Counter[str] = Counter()
    unparsed = 0
    channel: Counter[str] = Counter()
    for session, dates in sorted(claims.items()):
        record = classify(session, dates, by_session)
        verdicts[record["verdict"]] += 1
        unparsed += record.get("unverified_hits", 0)
        for key in ("rescued_by_weekday", "vetoed_by_weekday", "weekday_present", "hits"):
            channel[key] += record.get(key, 0)
        if record["verdict"].startswith("shared"):
            print(f"{session} {dates} -> {record['verdict']} "
                  f"split at paragraph {record.get('split_at_paragraph')} of {record['paragraphs']} "
                  f"(verified for {record['claimants_with_heading']})")

    print("\nverdicts over the duplicate population:")
    for verdict, count in verdicts.most_common():
        print(f"  {verdict:28s} {count:3d}")
    print(f"  (fuzzy hits REJECTED by exact day parse -- the v1 collision rate: {unparsed})")
    print(
        f"\nweekday cross-check over {channel['hits']} fuzzy hits: "
        f"weekday readable on {channel['weekday_present']}, "
        f"vetoed a matching day on {channel['vetoed_by_weekday']}, "
        f"rescued an unparseable day on {channel['rescued_by_weekday']}"
    )
    decided = sum(count for verdict, count in verdicts.items() if verdict.startswith("shared"))
    print(
        f"\ndisambiguated by heading alone: {decided}/{len(claims)} "
        f"({decided / len(claims):.0%}) -- remaining for the entity channel: {len(claims) - decided}"
    )
    if not ok:
        print("\nNOTE: the held-out validation case FAILED, so treat these verdicts as unproven.")


if __name__ == "__main__":
    main()
