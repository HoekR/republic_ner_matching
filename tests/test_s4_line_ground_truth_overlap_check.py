import io
import tarfile

import pandas as pd

from scripts.s4_line_ground_truth_overlap_check import (
    GOLD_DATES,
    TARGET_INVENTORIES,
    harvest_page_ids,
)


def test_harvest_page_ids_finds_embedded_page_references():
    raw = b'{"pages": ["NL-HaNA_1.01.02_3186_0042-page-83"], "other": "NL-HaNA_1.01.02_3186_0043-page-84 noise"}'
    assert harvest_page_ids(raw) == {
        "NL-HaNA_1.01.02_3186_0042-page-83",
        "NL-HaNA_1.01.02_3186_0043-page-84",
    }


def test_harvest_page_ids_returns_empty_set_when_no_match():
    assert harvest_page_ids(b'{"page_num": 83, "scan": 42}') == set()


def test_gold_dates_are_within_target_inventory_window():
    assert len(GOLD_DATES) == 12
    assert len(set(GOLD_DATES)) == 12
    assert TARGET_INVENTORIES == {3185, 3186, 3187, 3188, 3189}


def _write_member(tar: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def test_scan_archive_only_returns_wanted_members(monkeypatch, tmp_path):
    archive_path = tmp_path / "sessions_json.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as tar:
        _write_member(tar, "sessions_json/3186/session-3186-num-1.json.gz", b'"NL-HaNA_1.01.02_3186_0001-page-1"')
        _write_member(tar, "sessions_json/3186/session-3186-num-2.json.gz", b'"NL-HaNA_1.01.02_3186_0002-page-2"')
        _write_member(tar, "sessions_json/9999/session-9999-num-1.json.gz", b'"NL-HaNA_1.01.02_9999_0001-page-1"')

    import scripts.s4_line_ground_truth_overlap_check as module

    monkeypatch.setattr(module, "resolve", lambda name: archive_path)

    wanted = {"sessions_json/3186/session-3186-num-1.json.gz"}
    found = module.scan_archive(wanted)
    assert set(found) == wanted
    assert found["sessions_json/3186/session-3186-num-1.json.gz"] == {"NL-HaNA_1.01.02_3186_0001-page-1"}


def test_scan_archive_warns_on_missing_member(monkeypatch, tmp_path, capsys):
    archive_path = tmp_path / "sessions_json.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as tar:
        _write_member(tar, "sessions_json/3186/session-3186-num-1.json.gz", b"{}")

    import scripts.s4_line_ground_truth_overlap_check as module

    monkeypatch.setattr(module, "resolve", lambda name: archive_path)

    found = module.scan_archive({"sessions_json/3186/session-3186-num-1.json.gz", "sessions_json/3186/missing.json.gz"})
    assert "missing.json.gz" not in found
    assert "never found in archive" in capsys.readouterr().out


def test_target_sessions_filters_inventory_and_date(monkeypatch):
    import scripts.s4_line_ground_truth_overlap_check as module

    fake_index = pd.DataFrame(
        [
            {"session_id": "session-3186-num-1", "session_date": "1626-01-08", "session_num": 1, "inventory_num": 3186, "tar_member": "a"},
            {"session_id": "session-3186-num-2", "session_date": "1626-01-09", "session_num": 2, "inventory_num": 3186, "tar_member": "b"},
            {"session_id": "session-9999-num-1", "session_date": "1626-01-08", "session_num": 1, "inventory_num": 9999, "tar_member": "c"},
        ]
    )
    monkeypatch.setattr(module, "load", lambda name: fake_index)

    result = module.target_sessions()
    assert list(result["session_id"]) == ["session-3186-num-1"]
