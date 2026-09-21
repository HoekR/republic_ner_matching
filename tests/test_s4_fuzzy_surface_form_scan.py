import json

from scripts.s4_fuzzy_surface_form_scan import (
    MIN_MATCH_LENGTH,
    already_processed_keys,
    load_category_names,
    scan_category,
)


def test_load_category_names_extracts_names_and_first_id(monkeypatch):
    import scripts.s4_fuzzy_surface_form_scan as module

    fake_records = [
        {"id": "L0001", "name": "Amsterdam"},
        {"id": "L0002", "name": "Rotterdam"},
        {"id": "L0003", "name": "Amsterdam"},  # duplicate name, first id wins
        {"id": "L0004", "name": ""},  # no name, skipped
    ]
    monkeypatch.setattr(module, "load", lambda name: fake_records)

    names, name_to_id = load_category_names("loc_entities")
    assert names == ["Amsterdam", "Rotterdam", "Amsterdam"]
    assert name_to_id == {"Amsterdam": "L0001", "Rotterdam": "L0002"}


def test_already_processed_keys_reads_existing_output(tmp_path):
    output_path = tmp_path / "out.jsonl"
    output_path.write_text(
        json.dumps({"axis_id": "a1#p0", "category": "LOC"}) + "\n"
        + json.dumps({"axis_id": "a1#p1", "category": "PER"}) + "\n",
        encoding="utf-8",
    )
    assert already_processed_keys(output_path) == {("a1#p0", "LOC"), ("a1#p1", "PER")}


def test_already_processed_keys_empty_when_file_missing(tmp_path):
    assert already_processed_keys(tmp_path / "missing.jsonl") == set()


def test_min_match_length_constant_matches_documented_value():
    assert MIN_MATCH_LENGTH == 4


def test_scan_category_flags_already_known_and_filters_short_matches(monkeypatch, tmp_path):
    import scripts.s4_fuzzy_surface_form_scan as module

    fake_dictionary = [
        {"id": "L0001", "name": "Amsterdam"},
        {"id": "L0002", "name": "Ede"},  # short name -> its matches get filtered by MIN_MATCH_LENGTH
    ]
    monkeypatch.setattr(module, "load", lambda name: fake_dictionary)

    paragraphs = [
        {"axis_id": "f1#p0", "flat_id": "f1", "para_index": 0, "date": "1626-01-01", "text": "Synde te Amsterdam vergadert."},
        {"axis_id": "f2#p0", "flat_id": "f2", "para_index": 0, "date": "1626-01-02", "text": "Niets van belang."},
    ]
    known = {"f1": {"L0001"}}  # Amsterdam already confirmed in f1
    out_path = tmp_path / "scan.jsonl"

    with out_path.open("w", encoding="utf-8") as handle:
        written = scan_category("LOC", "loc_entities", paragraphs, known, set(), handle, limit=None)

    records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert written == len(records)
    assert all(len(r["matched_text"]) >= MIN_MATCH_LENGTH for r in records)
    amsterdam_hits = [r for r in records if r["canonical_name"] == "Amsterdam"]
    assert amsterdam_hits and amsterdam_hits[0]["already_known"] is True


def test_scan_category_skips_paragraphs_already_done(monkeypatch, tmp_path):
    import scripts.s4_fuzzy_surface_form_scan as module

    monkeypatch.setattr(module, "load", lambda name: [{"id": "L0001", "name": "Amsterdam"}])
    paragraphs = [
        {"axis_id": "f1#p0", "flat_id": "f1", "para_index": 0, "date": "1626-01-01", "text": "Amsterdam."},
    ]
    out_path = tmp_path / "scan.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        written = scan_category("LOC", "loc_entities", paragraphs, {}, {("f1#p0", "LOC")}, handle, limit=None)
    assert written == 0
    assert out_path.read_text(encoding="utf-8") == ""
