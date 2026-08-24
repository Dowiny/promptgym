import datetime

from promptgym import daily, tiers


def test_deterministic_same_day():
    d = datetime.date(2026, 8, 24)
    t1, s1 = daily.daily_puzzle(d)
    t2, s2 = daily.daily_puzzle(d)
    assert (t1, s1) == (t2, s2)


def test_different_days_differ():
    secrets = set()
    tiers_seen = set()
    for day in range(1, 15):
        t, s = daily.daily_puzzle(datetime.date(2026, 8, day))
        secrets.add(s)
        tiers_seen.add(t)
    assert len(secrets) > 5
    assert len(tiers_seen) > 2


def test_pool_valid_and_secret_shape():
    tid, secret = daily.daily_puzzle(datetime.date(2026, 8, 24))
    assert tid in daily.POOL
    assert tid in tiers.REGISTRY
    parts = secret.split("-")
    assert len(parts) == 3 and parts[0] == "BLZ"


def test_share_string():
    d = datetime.date(2026, 8, 24)
    s = daily.share_string(d, 5, 14, True)
    assert s == "PG-20260824 v%d T5 14tok" % daily.POOL_VERSION
    unsolved = daily.share_string(d, 5, 0, False)
    assert unsolved.endswith("unsolved")
