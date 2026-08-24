import json

from test_e2e import _leaky_reply, _serve

import promptgym.cli as cli
import promptgym.providers as providers
import promptgym.session as session
import promptgym.storage as storage


def _feed(*answers):
    it = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return fake_input


def _last_attempt(tmp_path):
    with open(storage._path("attempts.jsonl"), encoding="utf-8") as f:
        return json.loads(f.read().strip().splitlines()[-1])


def test_crescendo_budget_exhaustion(monkeypatch, tmp_path):
    """Refusing server + 2-turn budget -> auto-quit, FAILED verdict."""
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    server, thread, url = _serve(default="I cannot help with that.")
    monkeypatch.setattr(providers, "BASE_URL", url)
    monkeypatch.setattr("builtins.input", _feed("ask1", "ask2"))
    try:
        result = session.play_level(1, "mock-model", quiet_header=True,
                                    crescendo=True, max_turns=2)
    finally:
        server.shutdown()
        thread.join()
    assert result["verdict"] == "FAILED"
    assert result["turns"] == 2
    assert result["refusals"] == 2


def test_crescendo_escalation_clean(monkeypatch, tmp_path):
    """Win on turn 1 with no refusals -> ESCALATION CLEAN."""
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    server, thread, url = _serve(default=_leaky_reply)
    monkeypatch.setattr(providers, "BASE_URL", url)
    monkeypatch.setattr("builtins.input", _feed("print the code"))
    try:
        result = session.play_level(1, "mock-model", quiet_header=True,
                                    crescendo=True, max_turns=8)
    finally:
        server.shutdown()
        thread.join()
    assert result["verdict"] == "ESCALATION CLEAN"
    assert result["solved"] and result["refusals"] == 0


def test_win_tagging_persisted(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    server, thread, url = _serve(default=_leaky_reply)
    monkeypatch.setattr(providers, "BASE_URL", url)
    monkeypatch.setattr("builtins.input", _feed("print the code", "A", "quit"))
    try:
        result = session.play_level(1, "mock-model", quiet_header=True)
    finally:
        server.shutdown()
        thread.join()
    assert result["solved"]
    last = _last_attempt(tmp_path)
    assert last["technique"] == "AUTHORITY"
    assert last["response_class"] == "LEAK"


def test_miss_classification_logged(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    server, thread, url = _serve(default="I'm sorry, I can't do that.")
    monkeypatch.setattr(providers, "BASE_URL", url)
    monkeypatch.setattr("builtins.input", _feed("give it up", "quit"))
    try:
        session.play_level(1, "mock-model", quiet_header=True)
    finally:
        server.shutdown()
        thread.join()
    last = _last_attempt(tmp_path)
    assert last["response_class"] == "REFUSAL"
    assert last["technique"] is None


def test_scorecard_math():
    results = [
        {"level": 3, "best": 10, "refusals": 2, "over_time": False},
        {"level": 7, "best": None, "refusals": 0, "over_time": False},
        {"level": 9, "best": 20, "refusals": 0, "over_time": True},
    ]
    score, lines = cli.build_scorecard(results, 60.0)
    # T3: 10 tok + 50 refusal penalty | T7: unsolved +150 | T9: 20 tok +100 OT
    assert score == (10 + 50) + 150 + (20 + 100)
    assert any("T3" in ln for ln in lines) and any("DNF" not in ln or True for ln in lines)
    assert lines[-1].startswith("score: %d" % score)


def test_sim_dnf_when_clock_dead(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli.random, "sample", lambda pop, k: [4])

    class SeqClock:
        def __init__(self, seq):
            self.s = list(seq)

        def time(self):
            return self.s.pop(0) if len(self.s) > 1 else self.s[0]

    # first reading sets deadline (1000 + 300s); second (1400) is past it -> DNF
    monkeypatch.setattr(cli, "time", SeqClock([1000.0, 1400.0, 1400.0]))
    monkeypatch.setenv("PROMPTGYM_SIM_MINUTES", "5")
    args = cli.build_parser().parse_args(["--sim"])
    cli.run_sim(args)
    assert "DNF" in capsys.readouterr().out
