import json

import promptgym.storage as storage
from promptgym import taxonomy


def _write_attempts(entries):
    with open(storage._path("attempts.jsonl"), "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_codes_roundtrip():
    for code, name, _ in taxonomy.TECHNIQUES:
        assert taxonomy.name_for(code) == name
        assert taxonomy.name_for(code.lower()) == name
    assert taxonomy.name_for("ZZZ") is None
    assert taxonomy.name_for("") is None


def test_heatmap_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    taxonomy.render_heatmap()
    assert "No tagged solves" in capsys.readouterr().out


def test_heatmap_matrices(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    _write_attempts([
        {"ts": "2026-08-24 10:00:00", "level": 1, "model": "m1",
         "payload": "p", "payload_tokens": 10, "win": True,
         "technique": "DIRECT_ASK"},
        {"ts": "2026-08-24 10:01:00", "level": 5, "model": "m1",
         "payload": "q", "payload_tokens": 20, "win": True,
         "technique": "AUTHORITY"},
        {"ts": "2026-08-24 10:02:00", "level": 5, "model": "m2",
         "payload": "r", "payload_tokens": 15, "win": True,
         "technique": "AUTHORITY"},
        {"ts": "2026-08-24 10:03:00", "level": 9, "model": "m2",
         "payload": "s", "payload_tokens": 30, "win": False,
         "technique": None},
    ])
    taxonomy.render_heatmap()
    out = capsys.readouterr().out
    assert "technique x MODEL" in out and "technique x TIER" in out
    assert "AUTHORITY" in out and "DIRECT_ASK" in out


def test_refusal_threshold_stats(tmp_path, monkeypatch):
    from promptgym import analytics

    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    _write_attempts([
        {"model": "m", "level": 2, "win": False, "response_class": "REFUSAL"},
        {"model": "m", "level": 2, "win": False, "response_class": "REFUSAL"},
        {"model": "m", "level": 2, "win": True, "response_class": "LEAK"},
        {"model": "m", "level": 3, "win": True, "response_class": "LEAK"},
    ])
    stats = analytics.refusal_stats()
    assert abs(stats[("m", "2")] - 2.0) < 1e-9   # two refusals before the win
    assert stats[("m", "3")] == 0.0              # instant compliance
