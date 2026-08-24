"""--daily: one seeded puzzle per day, same for everyone, shareable result."""

import datetime
import random

POOL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 16]
POOL_VERSION = 1


def daily_puzzle(date=None):
    """Deterministically pick (tier_id, secret) for the given date."""
    day = (date or datetime.date.today())
    rng = random.Random("promptgym-daily-v%d-%s" % (POOL_VERSION, day.isoformat()))
    tid = rng.choice(POOL)
    secret = "BLZ-%d-%s" % (rng.randint(100, 999), rng.choice(["KX", "VR", "QN", "JT", "MW"]))
    return tid, secret


def share_string(date, tid, best_tokens, solved):
    status = "%dtok" % best_tokens if solved else "unsolved"
    return "PG-%s v%d T%d %s" % (
        date.isoformat().replace("-", ""), POOL_VERSION, tid, status)
