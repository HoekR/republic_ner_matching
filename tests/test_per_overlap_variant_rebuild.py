import pandas as pd

from build_per_overlap import build_per_overlap
from build_windowed_overlap import to_period_index_from_iso

PER_NAMES = {
    "P1": "Jan Jansz",
    "P2": "Pieter de Wit",
    "P3": "Cornelis Beveren",
}


def _surfaces_df() -> pd.DataFrame:
    rows = [
        # Variant-only case: editorial spelling "J. Jansz" differs from both the
        # canonical registry name ("Jan Jansz") and today's HTR spelling
        # ("Janszoon"); only the entity-linked variant harvest bridges them.
        {
            "person_id": "EP1",
            "surface_name": "J. Jansz",
            "canonical_name": "Jan Jansz",
            "volgnr": "V1",
            "xml_file": "x1.xml",
            "resolution_index": 1,
            "date": "1626-01-05",
        },
        # tag_text substring regression case: editorial surface differs from the
        # canonical registry name (so the canonical pass can't fire), but the
        # editorial surface is a literal substring of today's HTR tag_text.
        {
            "person_id": "EP2",
            "surface_name": "Pieter Wit",
            "canonical_name": "Pieter de Wit",
            "volgnr": "V2",
            "xml_file": "x2.xml",
            "resolution_index": 1,
            "date": "1626-01-06",
        },
        # surname-token regression case: only the last token ("beveren") appears
        # as a whole word in today's HTR tag_text.
        {
            "person_id": "EP3",
            "surface_name": "Cornelis van Beveren",
            "canonical_name": "Cornelis Beveren",
            "volgnr": "V3",
            "xml_file": "x3.xml",
            "resolution_index": 1,
            "date": "1626-01-07",
        },
        # Precision guard: no HTR PER annotation exists on this date at all.
        {
            "person_id": "EP4",
            "surface_name": "Totally Unrelated Name",
            "canonical_name": "Totally Unrelated Name",
            "volgnr": "V4",
            "xml_file": "x4.xml",
            "resolution_index": 1,
            "date": "1626-01-08",
        },
    ]
    return pd.DataFrame(rows)


def _per_dated() -> pd.DataFrame:
    rows = [
        # Seeds P1's variant registry with a spelling equal to EP1's editorial
        # surface, on a different day so it never appears in EP1's own window.
        {
            "entity": "P1",
            "tag_text": "J. Jansz",
            "tag_text_norm": "j. jansz",
            "paragraph_id": "para-seed",
            "resolution_id": "res-seed",
            "flat_date": "1626-02-10",
        },
        # Today's HTR mention of P1, spelled differently from EP1's editorial
        # surface and from the canonical registry name.
        {
            "entity": "P1",
            "tag_text": "Janszoon",
            "tag_text_norm": "janszoon",
            "paragraph_id": "para-B",
            "resolution_id": "res-B",
            "flat_date": "1626-01-05",
        },
        {
            "entity": "P2",
            "tag_text": "seeker Pieter Wit aldaer",
            "tag_text_norm": "seeker pieter wit aldaer",
            "paragraph_id": "para-C",
            "resolution_id": "res-C",
            "flat_date": "1626-01-06",
        },
        {
            "entity": "P3",
            "tag_text": "d'Heer van Beveren",
            "tag_text_norm": "d'heer van beveren",
            "paragraph_id": "para-D",
            "resolution_id": "res-D",
            "flat_date": "1626-01-07",
        },
    ]
    frame = pd.DataFrame(rows)
    frame["flat_date_period"] = to_period_index_from_iso(frame["flat_date"])
    return frame


def _run():
    output, stats = build_per_overlap(_surfaces_df(), _per_dated(), PER_NAMES, window_days=0)
    return output, stats


def test_variant_pass_recovers_a_spelling_never_seen_by_editorial_surface():
    output, _ = _run()
    match = output.loc[output["person_id"] == "EP1"]
    assert len(match) == 1
    assert match.iloc[0]["match_kind"] == "variant"
    assert match.iloc[0]["paragraph_id"] == "para-B"


def test_tag_text_substring_pass_still_catches_literal_substrings():
    output, _ = _run()
    match = output.loc[output["person_id"] == "EP2"]
    assert len(match) == 1
    assert match.iloc[0]["match_kind"] == "tag_text"
    assert match.iloc[0]["paragraph_id"] == "para-C"


def test_surname_token_fallback_still_catches_last_token_only_matches():
    output, _ = _run()
    match = output.loc[output["person_id"] == "EP3"]
    assert len(match) == 1
    assert match.iloc[0]["match_kind"] == "surname_token"
    assert match.iloc[0]["paragraph_id"] == "para-D"


def test_no_match_produced_when_nothing_overlaps_that_day():
    output, _ = _run()
    assert output.loc[output["person_id"] == "EP4"].empty


def test_stats_report_all_four_match_kinds():
    _, stats = _run()
    assert stats["canonical_matches"] == 0
    assert stats["variant_matches"] == 1
    assert stats["tag_text_matches"] == 1
    assert stats["surname_token_matches"] == 1
    assert stats["output_rows"] == 3
