from scripts.svz import (
    CANONICAL_GOAL_MARKER,
    check_document,
    contains_goal_assertion,
    has_canonical_goal_marker,
    parse_doc_status,
    split_plan_sections,
)


def test_parse_doc_status_reads_the_marker():
    assert parse_doc_status("<!-- doc-status: active -->\nsome text") == "active"


def test_parse_doc_status_is_case_insensitive():
    assert parse_doc_status("<!-- DOC-STATUS: Retired -->") == "retired"


def test_parse_doc_status_returns_none_when_absent():
    assert parse_doc_status("just prose, no marker") is None


def test_has_canonical_goal_marker():
    assert has_canonical_goal_marker(f"before {CANONICAL_GOAL_MARKER} after")
    assert not has_canonical_goal_marker("no marker here")


def test_contains_goal_assertion_matches_goal_colon_style():
    assert contains_goal_assertion("Goal: map each enriched resolution to its span.")


def test_contains_goal_assertion_matches_prose_phrasing():
    assert contains_goal_assertion("the goal is to fine-tune a tagger")
    assert not contains_goal_assertion("this section has nothing to do with aims")


def test_split_plan_sections_splits_on_level_2_headings():
    text = "# Title\nintro line\n## First\nbody one\n## Second\nbody two\n"
    sections = split_plan_sections(text)
    headings = [heading for heading, _ in sections]
    assert headings == ["<preamble>", "First", "Second"]
    assert "body one" in dict(sections)["First"]
    assert "body two" in dict(sections)["Second"]


def test_split_plan_sections_drops_empty_trailing_section():
    sections = split_plan_sections("## Only\nbody\n")
    assert [heading for heading, _ in sections] == ["Only"]


# --- check_document: the two failure modes the conformance check exists to catch ---


def test_check_document_fails_a_statusless_document():
    problems = check_document("foo.md", "Some prose with no marker at all.")
    assert any("no doc-status marker" in p for p in problems)


def test_check_document_fails_an_active_document_asserting_a_goal():
    text = "<!-- doc-status: active -->\nGoal: do the thing.\n"
    problems = check_document("baz.md", text)
    assert any("asserts a project goal outside the canonical location" in p for p in problems)


def test_check_document_fails_an_unstatused_document_asserting_a_goal_too():
    # Absent status defaults to being treated as active for the goal-assertion check --
    # unstatused text is not a safe place to park a goal statement either.
    problems = check_document("bar.md", "Goal: do the thing.")
    assert any("asserts a project goal outside the canonical location" in p for p in problems)


def test_check_document_allows_a_retired_document_to_keep_its_historical_goal_text():
    text = "<!-- doc-status: retired -->\nGoal: do the old thing.\n"
    assert check_document("qux.md", text) == []


def test_check_document_allows_a_future_document_to_discuss_goals():
    text = "<!-- doc-status: future -->\nGoal: something we might do later.\n"
    assert check_document("plan.md", text) == []


def test_check_document_exempts_the_canonical_location_regardless_of_status():
    text = f"<!-- doc-status: active -->\n{CANONICAL_GOAL_MARKER}\nGoal: the real one.\n"
    assert check_document("PLAN.md", text) == []


def test_check_document_passes_a_clean_active_document_with_no_goal_talk():
    text = "<!-- doc-status: active -->\nJust ordinary content.\n"
    assert check_document("clean.md", text) == []
