import pandas as pd

from scripts.render_session_date_heatmap import render_heatmap


def test_renders_statuses_and_inventory_panels():
    ledger = pd.DataFrame(
        {
            "inventory_id": [3185, 3186],
            "enriched_date": ["1626-01-01", "1627-01-02"],
            "status_code": ["N", "+1"],
            "session_date_key": ["session-3185|1626-01-01", "session-3186|1627-01-02"],
            "trusted_anchor_count": [0, 0],
            "exact_date_paragraph_count": [0, 0],
            "fallback_distance": [pd.NA, 1],
            "status_detail": ["no same-day HTR session candidate", "one next-day HTR session candidate pending review"],
            "trusted_session_ids": [[], []],
            "exact_date_session_ids": [[], []],
            "previous_day_session_ids": [[], []],
            "next_day_session_ids": [[], ["session-3186-num-1"]],
        }
    )

    document = render_heatmap(ledger)

    assert "Inventory 3185" in document
    assert "Inventory 3186" in document
    assert "status-N" in document
    assert "status-+1" in document
    assert "Session-Date Evidence Status" in document