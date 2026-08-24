import json

import promptgym.storage as storage


def _write_attempts(entries):
    with open(storage._path("attempts.jsonl"), "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_solves_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    by_model = {"m1": {"3": {"payload": "p", "tokens": 9}}}
    storage.save_solves(by_model)
    assert storage.load_solves() == by_model


def test_update_solves_only_improves(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    assert storage.update_solves(2, "a", 10, True, "m") == 10
    assert storage.update_solves(2, "b", 12, True, "m") is None  # worse, ignored
    assert storage.update_solves(2, "c", 7, True, "m") == 7      # new record
    assert storage.load_solves()["m"]["2"]["tokens"] == 7
    assert storage.update_solves(2, "d", 5, False, "m") is None  # losses never record


def test_export_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.save_solves({"m": {"1": {"payload": "x", "tokens": 4}}})
    out = storage.export_matrix_csv(out_path=tmp_path / "matrix.csv")
    text = out.read_text(encoding="utf-8")
    assert "model,tier,tokens,payload" in text and "m,1,4,x" in text


def test_migrate_legacy_copies(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "solves.json").write_text('{"version": 2, "by_model": {"m": {}}}')
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "LEGACY_DIRS", [legacy])
    copied = storage.migrate_legacy()
    assert len(copied) == 1
    assert json.loads((data_dir / "solves.json").read_text())["version"] == 2
    # second run: no duplicate copy
    assert storage.migrate_legacy() == []


def test_load_spend_default(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    assert storage.load_spend() == {"total_usd": 0.0, "sessions": []}
    storage.record_spend("m", 0.5, 1)
    storage.record_spend("m", 0.25, 2)
    spend = storage.load_spend()
    assert abs(spend["total_usd"] - 0.75) < 1e-6
    assert len(spend["sessions"]) == 2
