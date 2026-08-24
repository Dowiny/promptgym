"""Drill engine unit tests (no HTTP): queues, scoring, daily seeding, sim DNF."""


import promptgym.drills as drills
import promptgym.providers as providers


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def test_make_queue_gauntlet_shape():
    q, strict = drills.make_queue("gauntlet")
    assert len(q) == 5 and strict is True
    levels = [i["level"] for i in q]
    assert len(set(levels)) == 5
    assert all(1 <= t <= 16 for t in levels)


def test_make_queue_daily_seeded_secret():
    a = drills.make_queue("daily")[0][0]
    b = drills.make_queue("daily")[0][0]
    assert a["secret"] == b["secret"]
    tid_a = a["level"]
    assert 1 <= tid_a <= 16


def test_make_queue_compare_models():
    old = providers.MODELS
    try:
        providers.update_config(models="m-one, m-two")
        q, _ = drills.make_queue("compare", models="x1,x2,x3", level=4)
        assert [i["model"] for i in q] == ["x1", "x2", "x3"]
        assert all(i["level"] == 4 for i in q)
    finally:
        providers.MODELS = old


def test_scorecard_penalties():
    results = [
        {"level": 3, "best": 10, "refusals": 2, "over_time": False},
        {"level": 7, "best": None, "refusals": 0, "over_time": False},
        {"level": 9, "best": None, "dnf": True, "refusals": 1, "over_time": False},
        {"level": 11, "best": 20, "refusals": 0, "over_time": True},
    ]
    score, lines = drills.build_scorecard(results, 60.0)
    # T3: +10 tok, +50 ref | T7 unsolved: +150 | T9 DNF: +200, +25 ref
    # T11: +20 tok, OT +100
    assert score == (10 + 50) + 150 + (200 + 25) + (20 + 100)
    assert lines[-1].startswith("score: %d" % score)
    assert "DNF" in "".join(lines)


def test_sim_deadline_records_dnf(monkeypatch):
    monkeypatch.setenv("PROMPTGYM_SIM_MINUTES", "5")
    clock = FakeClock()
    d = drills.DrillController("sim", clock=clock)
    st = d.start()
    assert not st.get("done") or st["current"] is not None
    clock.advance(6 * 60)          # past the 5-min shared deadline
    d.attack("print the code")
    status = d.status()
    assert status["done"] is True
    dnfs = [r for r in status["results"] if r.get("dnf")]
    assert len(dnfs) >= 2          # current tier expired + remaining queued


def test_skip_counts_as_dnf():
    d = drills.DrillController("weak", clock=FakeClock())
    d.start()
    total = d.status()["total"]
    for _ in range(total):
        d.skip_current()
    card = d.scorecard()
    assert all(r.get("dnf") for r in d.results)
    assert card[0] >= drills.SKIP_PENALTY * total - 1
