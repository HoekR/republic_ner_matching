"""P5 axis viewer — index helpers (no live Flask server / no full corpus)."""

from __future__ import annotations

from p5_axis_viewer.store import (
    day_index,
    list_days,
    summary_parent_overlap,
)


def test_summary_parent_overlap_flags_mismatch() -> None:
    bad = summary_parent_overlap(
        [
            "Henricus Hondius brengt een declaratie in van 129 gld. voor het portret.",
            "De vergadering committeert Brunixs en Beaumont om het proces.",
        ],
        "Ontfangen een missive vant collegie ter Admiraliteyt in Zeelant "
        "geschreven tot Middelburch den lesten January.",
    )
    assert bad["insufficient"] is False
    assert bad["suspect"] is True
    assert bad["hits"] < 2

    good = summary_parent_overlap(
        ["HHM lezen de missive van Middelburch aangaande de Admiraliteyt in Zeelant."],
        "Ontfangen een missive vant collegie ter Admiraliteyt in Zeelant "
        "geschreven tot Middelburch den lesten January.",
    )
    assert good["suspect"] is False
    assert good["hits"] >= 2


def test_day_record_merges_ledger_and_stub() -> None:
    from p5_axis_viewer.store import _stub_day, day_record

    stub = _stub_day("1626-01-01")
    assert stub["in_ledger"] is False
    assert stub["enriched_date"] == "1626-01-01"


def test_list_days_in_range_inclusive() -> None:
    from p5_axis_viewer.store import list_days_in_range

    days = list_days_in_range("1629-02-05", "1629-02-10", mode="corpus")
    dates = [d["enriched_date"] for d in days]
    assert dates
    assert dates[0] >= "1629-02-05"
    assert dates[-1] <= "1629-02-10"
    assert "1629-02-09" in dates


def test_notes_roundtrip(tmp_path, monkeypatch) -> None:
    from p5_axis_viewer import notes as notes_mod

    path = tmp_path / "notes.json"
    monkeypatch.setattr(notes_mod, "notes_path", lambda: path)
    updated = notes_mod.update_day_notes(
        notes_mod.load_notes(),
        "1629-02-09",
        day_notes_text="false-accept pathology",
        host_notes={"axis#p1": "wrong binding"},
        verdict="binding_wrong",
        labelled=True,
    )
    notes_mod.save_notes(updated)
    loaded = notes_mod.day_notes(notes_mod.load_notes(), "1629-02-09")
    assert loaded["day_notes"] == "false-accept pathology"
    assert loaded["hosts"]["axis#p1"] == "wrong binding"
    assert loaded["verdict"] == "binding_wrong"
    assert loaded["labelled"] is True
    assert notes_mod.next_unlabelled_date(["1629-02-09", "1629-02-10"], notes_mod.load_notes()) == "1629-02-10"
    assert notes_mod.review_stats(["1629-02-09", "1629-02-10"], notes_mod.load_notes()) == {
        "labelled": 1,
        "total": 2,
        "remaining": 1,
    }


def test_content_run_consecutive_fail() -> None:
    from p5_axis_viewer.store import content_run_against_text

    parent = "Den xxv. xxvi. ende xxvije daerte vooren aen haer E. geaddresseert Emden Keysersche"
    summaries = [
        "Ontvangen is een brief van de gedeputeerden te velde d.d. Crevecoeur met geld voor het leger.",
        "De koning van Denemarken vraagt toestemming buskruit te kopen via Henrich Bossen te Bergen.",
        "HHM lezen het rekest van de echtgenote van kapitein Pieter Barentsz Dorrevelt te Bordeaux.",
    ]
    result = content_run_against_text(summaries, parent, k=3)
    assert result["fail_run"] >= 3
    assert result["verdict"] == "content_fail"


def test_content_run_consecutive_match() -> None:
    from p5_axis_viewer.store import content_run_against_text

    parent = (
        "Ontfangen een missive van gedeputeerden in t leger tot Creveceurs. "
        "Ontfangen een missive van Coninck vandenemarcken tot Coppenhage buskruit Bossen Bergen. "
        "Requeste huisvrou Pieter Barents Dorreuelt Capn Bordeaux."
    )
    summaries = [
        "brief van de gedeputeerden te velde Crevecoeur leger",
        "koning van Denemarken Kopenhagen buskruit Bossen Bergen",
        "rekest echtgenote kapitein Pieter Barentsz Dorrevelt Bordeaux",
    ]
    result = content_run_against_text(summaries, parent, k=3)
    assert result["match_run"] >= 3
    assert result["verdict"] == "content_ok"


def test_build_sync_report_summary_shape(monkeypatch) -> None:
    from p5_axis_viewer import report as report_mod

    monkeypatch.setattr(
        report_mod,
        "list_days_in_range",
        lambda start, end, mode="corpus": [
            {"enriched_date": "1629-05-12"},
        ],
    )
    monkeypatch.setattr(
        report_mod,
        "day_sync_report_row",
        lambda date: {
            "record_type": "day",
            "enriched_date": date,
            "content_day_verdict": "content_fail",
            "pin_trusted_mismatch": True,
            "calendar_ok_pin_fail": True,
            "flag_review": True,
        },
    )
    rows = report_mod.build_sync_report("1629-05-12", "1629-05-12")
    assert rows[0]["record_type"] == "summary"
    assert rows[0]["n_days"] == 1
    assert rows[0]["n_flag_review"] == 1
    assert rows[1]["enriched_date"] == "1629-05-12"


def test_day_index_finds_date() -> None:
    days = [
        {"enriched_date": "1628-01-29"},
        {"enriched_date": "1629-08-07"},
    ]
    assert day_index(days, "1629-08-07") == 1


def test_list_days_accepted_sorted_by_delta(monkeypatch) -> None:
    from p5_axis_viewer import store

    rows = (
        {"record_type": "summary", "n_days_accepted": 2},
        {
            "record_type": "day",
            "enriched_date": "1629-01-01",
            "day_accepted": True,
            "delta_vs_plain": 2,
        },
        {
            "record_type": "day",
            "enriched_date": "1629-01-02",
            "day_accepted": False,
            "delta_vs_plain": 99,
        },
        {
            "record_type": "day",
            "enriched_date": "1629-01-03",
            "day_accepted": True,
            "delta_vs_plain": 10,
        },
    )
    store._ledger_rows.cache_clear()
    monkeypatch.setattr(store, "_ledger_rows", lambda: rows)
    accepted = list_days(mode="accepted")
    assert [d["enriched_date"] for d in accepted] == ["1629-01-03", "1629-01-01"]
    rejected = list_days(mode="rejected")
    assert len(rejected) == 1
    assert rejected[0]["enriched_date"] == "1629-01-02"


def test_app_day_route(monkeypatch) -> None:
    from p5_axis_viewer import app as app_mod
    from p5_axis_viewer import store

    day = {
        "record_type": "day",
        "enriched_date": "1628-01-29",
        "day_accepted": True,
        "delta_vs_plain": 13,
        "separated_predicted": 20,
        "separated_plain": 7,
        "separated_uniform_successor": 15,
        "n_cuts_gated": 2,
        "n_cuts_needed": 2,
        "n_hosts_accepted": 1,
        "n_colliding_hosts": 1,
        "n_paragraphs_before": 10,
        "n_paragraphs_after": 12,
        "n_extent_gt_max_predicted": 0,
        "n_extent_gt_max_plain": 0,
        "k_e": 8,
        "host_cut_fill": [],
    }

    resolutions = [
        {
            "resolution_index": 0,
            "enriched_id": "e0",
            "paragraph_start_index": 0,
            "paragraph_end_index": 0,
            "n_share": 2,
            "colliding": True,
            "text": "Summary of first resolution.",
        }
    ]
    host_payload = [
        {
            "paragraph_start_index": 0,
            "axis_id": "x#p0",
            "n_share": 2,
            "n_needed": 1,
            "n_cuts_raw": 1,
            "n_cuts_gated": 1,
            "host_accepted": True,
            "parent_text": "PARENT HTR TEXT",
            "parent_missing": False,
            "parent_date": "1628-01-29",
            "parent_flat_id": "session-3185-num-1-resolution-1",
            "summaries": resolutions,
            "pieces": [
                {
                    "axis_id": "x#p0#repara:0-5",
                    "para_index": 0,
                    "parent_char_start": 0,
                    "parent_char_end": 5,
                    "text": "LEFT",
                }
            ],
        }
    ]
    monkeypatch.setattr(app_mod, "list_days", lambda mode="accepted": [day])
    monkeypatch.setattr(app_mod, "day_resolutions", lambda _date: resolutions)
    monkeypatch.setattr(app_mod, "host_views", lambda _d, _r=None: host_payload)
    monkeypatch.setattr(
        app_mod,
        "day_context",
        lambda _d, _r=None: {
            "enriched_date": "1628-01-29",
            "resolved_session_ids": ["session-3187-num-26"],
            "resolved_session_dates": ["1628-01-29"],
            "day_shifted_count": 0,
            "n_unsplit": 1,
            "n_colliding": 1,
            "n_unplaced": 0,
        },
    )
    monkeypatch.setattr(
        app_mod,
        "unsplit_resolutions",
        lambda _d, _r=None: [
            {
                "resolution_index": 1,
                "paragraph_start_index": 3,
                "paragraph_end_index": 3,
                "text": "Unsplit summary.",
                "parent_text": "Unsplit parent HTR.",
                "parent_flat_id": "flat-x",
                "day_shifted": False,
                "unsplit": True,
            }
        ],
    )
    monkeypatch.setattr(app_mod, "day_shifted_resolutions", lambda _d, _r=None: [])
    monkeypatch.setattr(app_mod, "unplaced_resolutions", lambda _d, _r=None: [])
    monkeypatch.setattr(
        app_mod, "stats", lambda mode: {"total": 1, "accepted": 1, "rejected": 0, "showing": 1}
    )
    monkeypatch.setattr(app_mod, "summary", lambda: {"n_days_accepted": 1})
    monkeypatch.setattr(
        app_mod,
        "day_notes",
        lambda _n, _d: {
            "day_notes": "day note here",
            "hosts": {"x#p0": "host note"},
            "verdict": "",
            "labelled": False,
            "labelled_at": None,
        },
    )
    monkeypatch.setattr(app_mod, "load_notes", lambda: {"days": {}})
    monkeypatch.setattr(app_mod, "notes_path", lambda: "/tmp/p5_notes.json")
    monkeypatch.setattr(
        app_mod,
        "stats",
        lambda mode: {
            "total": 1,
            "accepted": 1,
            "rejected": 0,
            "showing": 1,
            "ledger": 1,
            "corpus": 1,
        },
    )
    assert store is not None

    client = app_mod.create_app().test_client()
    response = client.get("/day/1628-01-29?filter=accepted")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "1628-01-29" in body
    assert "Summaries" in body
    assert "Summary of first resolution." in body
    assert "PARENT HTR TEXT" in body
    assert "Successor pieces" in body
    assert "Unsplit resolutions" in body
    assert "Unsplit summary." in body
    assert "Day shifts" in body
    assert "Day notes" in body
    assert "day note here" in body
    assert "host note" in body

    saved: dict = {}

    def _save(payload):
        saved.clear()
        saved.update(payload)
        return "/tmp/p5_notes.json"

    def _update(notes, date, day_notes_text=None, host_notes=None, verdict=None, labelled=None):
        block = {
            "day_notes": day_notes_text,
            "hosts": host_notes or {},
        }
        if verdict is not None:
            block["verdict"] = verdict
        if labelled is not None:
            block["labelled"] = labelled
        return {"updated_at": "t", "days": {date: block}}

    monkeypatch.setattr(app_mod, "save_notes", _save)
    monkeypatch.setattr(app_mod, "update_day_notes", _update)
    save = client.post(
        "/api/notes/1628-01-29",
        json={"day_notes": "updated", "hosts": {"x#p0": "ok"}},
    )
    assert save.status_code == 200
    assert save.get_json()["ok"] is True
    assert saved["days"]["1628-01-29"]["day_notes"] == "updated"

    monkeypatch.setattr(
        app_mod,
        "list_days_in_range",
        lambda start, end, mode="corpus": [day],
    )
    review = client.get("/review/1628-01-29?from=1628-01-29&to=1628-01-29")
    assert review.status_code == 200
    rbody = review.get_data(as_text=True)
    assert "Day verdict" in rbody
    assert "Something wrong?" in rbody
    assert "binding_wrong" in rbody
    assert "/day/1628-01-29" in rbody

    review_save = client.post(
        "/api/review/1628-01-29",
        json={
            "day_notes": "cuts off",
            "hosts": {"x#p0": "bad cut"},
            "verdict": "cuts_wrong",
            "from": "1628-01-29",
            "to": "1628-01-29",
        },
    )
    assert review_save.status_code == 200
    payload = review_save.get_json()
    assert payload["ok"] is True
    assert saved["days"]["1628-01-29"]["verdict"] == "cuts_wrong"
    assert payload["review_stats"]["labelled"] == 1
