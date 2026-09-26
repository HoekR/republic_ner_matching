from scripts.svz import metric_health, score_task, task_next_action


def test_task_next_action_prefers_explicit_field():
    task = {"next_action": "Run the audit", "notes": "Next action: something stale"}
    assert task_next_action(task) == "Run the audit"


def test_task_next_action_falls_back_to_notes():
    task = {"notes": "Blocked on data. Next action: map page_ids to dates. Do not skip."}
    assert task_next_action(task) == "map page_ids to dates"


def test_task_next_action_returns_none_when_absent():
    assert task_next_action({"notes": "No guidance here."}) is None


def test_metric_health_reports_no_metric():
    assert metric_health([], 0.03) == "no-metric"


def test_metric_health_reports_all_stagnant():
    metrics = [{"history": [{"value": 0.5}, {"value": 0.5}]}]
    assert metric_health(metrics, 0.03) == "all-stagnant"


def test_metric_health_prefers_improving_when_any_metric_improves():
    metrics = [
        {"history": [{"value": 0.5}, {"value": 0.5}]},
        {"history": [{"value": 0.2}, {"value": 0.4}]},
    ]
    assert metric_health(metrics, 0.03) == "improving"


def test_metric_health_flags_unjudgeable_single_point_history():
    assert metric_health([{"history": [{"value": 0.5}]}], 0.03) == "unjudgeable"


def test_score_task_ranks_leverage_above_cheapness():
    upstream = {"id": "a", "blocks": ["x", "y"], "cost": "multi-session"}
    cheap_leaf = {"id": "b", "blocks": [], "cost": "cheap"}
    assert score_task(upstream, "improving") > score_task(cheap_leaf, "improving")


def test_score_task_rewards_cheapness_between_equal_leverage():
    cheap = {"id": "a", "blocks": ["x"], "cost": "cheap"}
    costly = {"id": "b", "blocks": ["x"], "cost": "multi-session"}
    assert score_task(cheap, "improving") > score_task(costly, "improving")


def test_score_task_surfaces_unmeasurable_work():
    """A track with no metric can't be judged — ITERATION_POLICY.md calls that a defect."""
    measured = {"id": "a", "blocks": [], "cost": "session"}
    unmeasured = {"id": "b", "blocks": [], "cost": "session"}
    assert score_task(unmeasured, "no-metric") > score_task(measured, "improving")
