from scripts.svz import (
    decisions_md_dates,
    find_metric,
    metric_scope_matches_task,
    metrics_for_task,
    truncate_for_render,
    validate_tasks_metrics,
)


def test_metric_scope_matches_task_exact():
    assert metric_scope_matches_task("foo", "foo")
    assert not metric_scope_matches_task("foobar", "foo")


def test_metric_scope_matches_task_subid():
    assert metric_scope_matches_task("foo-bar", "foo")
    assert not metric_scope_matches_task("bar-foo", "foo")


def test_metrics_for_task_filters_by_scope():
    metrics = [
        {"scope": "a", "name": "x"},
        {"scope": "a-sub", "name": "y"},
        {"scope": "b", "name": "z"},
    ]
    assert metrics_for_task(metrics, "a") == metrics[:2]


def test_find_metric_matches_scope_and_name():
    metrics = [{"scope": "a", "name": "x", "value": 1}, {"scope": "a", "name": "y", "value": 2}]
    assert find_metric(metrics, "a", "y") == {"scope": "a", "name": "y", "value": 2}


def test_find_metric_returns_none_when_absent():
    assert find_metric([{"scope": "a", "name": "x"}], "a", "y") is None


def test_truncate_for_render_leaves_short_text_alone():
    assert truncate_for_render("short", 160) == "short"


def test_truncate_for_render_truncates_with_suffix():
    result = truncate_for_render("x" * 500, 160)
    assert result.startswith("x" * 160)
    assert "full text in docs/state.json" in result
    assert len(result) < 500


def test_validate_tasks_metrics_flags_duplicate_ids():
    tasks = [{"id": "a", "status": "done"}, {"id": "a", "status": "todo"}]
    problems = validate_tasks_metrics(tasks, [])
    assert any("Duplicate task ids" in p for p in problems)


def test_validate_tasks_metrics_flags_unknown_blocks():
    tasks = [{"id": "a", "status": "todo", "blocks": ["ghost"]}]
    problems = validate_tasks_metrics(tasks, [])
    assert any("unknown task id" in p for p in problems)


def test_validate_tasks_metrics_flags_orphan_metric_scope():
    tasks = [{"id": "a", "status": "todo"}]
    metrics = [{"scope": "b", "name": "m"}]
    problems = validate_tasks_metrics(tasks, metrics)
    assert any("does not match any task id" in p for p in problems)


def test_validate_tasks_metrics_allows_subid_scope():
    tasks = [{"id": "a", "status": "todo"}]
    metrics = [{"scope": "a-sub", "name": "m"}]
    assert validate_tasks_metrics(tasks, metrics) == []


def test_validate_tasks_metrics_clean_state_has_no_problems():
    tasks = [{"id": "a", "status": "done"}]
    metrics = [{"scope": "a", "name": "m"}]
    assert validate_tasks_metrics(tasks, metrics) == []


def test_decisions_md_dates_extracts_heading_dates():
    text = "# Decision Log\n\n## 2026-09-18: First\n\nbody\n\n## 2026-10-02: Second\n\nbody\n"
    assert decisions_md_dates(text) == ["2026-09-18", "2026-10-02"]


def test_decisions_md_dates_empty_when_no_headings():
    assert decisions_md_dates("# Decision Log\n\njust prose\n") == []
