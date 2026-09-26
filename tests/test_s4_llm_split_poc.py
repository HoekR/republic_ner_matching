import json

from scripts.s4_llm_split_poc import (
    already_processed_keys,
    build_prompt,
    parse_offsets,
    select_examples,
)


def test_parse_offsets_extracts_json_list_from_surrounding_prose():
    assert parse_offsets("Sure, here you go: [45, 210] -- hope that helps!") == [45, 210]


def test_parse_offsets_sorts_results():
    assert parse_offsets("[210, 45]") == [45, 210]


def test_parse_offsets_returns_none_when_no_list_present():
    assert parse_offsets("I cannot find any cuts in this text.") is None


def test_parse_offsets_returns_none_for_non_integer_list():
    assert parse_offsets('["a", "b"]') is None


def test_parse_offsets_handles_empty_list():
    assert parse_offsets("[]") == []


def test_select_examples_excludes_self_and_prefers_same_k(monkeypatch):
    positions = [
        {"flat_id": "f0", "target_splits": 1},
        {"flat_id": "f1", "target_splits": 2},
        {"flat_id": "f2", "target_splits": 1},
        {"flat_id": "f3", "target_splits": 1},
    ]
    examples = select_examples(positions, target_index=0, n_fewshot=2)
    assert examples == [positions[2], positions[3]]


def test_select_examples_falls_back_to_any_other_position_when_no_same_k_match():
    positions = [
        {"flat_id": "f0", "target_splits": 1},
        {"flat_id": "f1", "target_splits": 2},
    ]
    examples = select_examples(positions, target_index=0, n_fewshot=5)
    assert examples == [positions[1]]


def test_build_prompt_includes_examples_text_and_target_text():
    target = {"target_splits": 2, "text": "TARGET PARAGRAPH TEXT"}
    examples = [{"text": "EXAMPLE TEXT", "target_splits": 1, "gold_offsets": [50]}]
    prompt = build_prompt(target, examples)
    assert "EXAMPLE TEXT" in prompt
    assert "TARGET PARAGRAPH TEXT" in prompt
    assert "exactly 2 interior cut point(s)" in prompt
    assert "[50]" in prompt


def test_already_processed_keys_reads_existing_output(tmp_path):
    output_path = tmp_path / "out.jsonl"
    output_path.write_text(
        json.dumps({"flat_id": "f1", "para_index": 0}) + "\n"
        + json.dumps({"flat_id": "f1", "para_index": 1}) + "\n",
        encoding="utf-8",
    )
    assert already_processed_keys(output_path) == {("f1", 0), ("f1", 1)}


def test_already_processed_keys_empty_when_file_missing(tmp_path):
    assert already_processed_keys(tmp_path / "missing.jsonl") == set()
