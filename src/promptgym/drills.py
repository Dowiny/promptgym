"""Shared drill orchestration for CLI and web.

DrillController drives multi-tier sessions (gauntlet/sim/daily/weak/compare)
on top of GameSession. build_scorecard + make_queue are shared verbatim with
the CLI so both frontends produce identical scoring.
"""

import datetime
import random
import time

from . import analytics, daily, providers, tiers
from .session import GameSession

GAUNTLET_TIERS = 5
SIM_TIERS = 3
PER_TIER_BUDGET_S = 20 * 60
SKIP_PENALTY = 150
DNF_PENALTY = 200
OT_PENALTY = 100
REFUSAL_PENALTY = 25


def sim_minutes():
    raw = providers.env("PROMPTGYM_SIM_MINUTES", default="60")
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 60.0


def make_queue(dtype, models=None, level=None):
    """Returns (queue, strict_default). Queue items: {level, model, secret?}."""
    primary = providers.PRIMARY_MODEL
    pool = list(range(1, tiers.MAX_TIER + 1))
    if dtype == "gauntlet":
        return [{"level": lv, "model": primary}
                for lv in random.sample(pool, GAUNTLET_TIERS)], True
    if dtype == "sim":
        return [{"level": lv, "model": primary}
                for lv in random.sample(pool, SIM_TIERS)], True
    if dtype == "daily":
        tid, secret = daily.daily_puzzle()
        return [{"level": tid, "model": primary,
                 "secret": secret}], True
    if dtype == "weak":
        queue = analytics.weak_tiers(4) or [1]
        return [{"level": lv, "model": primary} for lv in queue], False
    if dtype == "compare":
        model_list = [m.strip() for m in (models or "").split(",") if m.strip()]
        if len(model_list) < 2:
            model_list = list(providers.MODELS)[:3]
        tier = int(level) if level else 1
        return [{"level": tier, "model": m} for m in model_list], False
    raise ValueError("unknown drill type: %s" % dtype)


def build_scorecard(results, minutes):
    """Pure scorecard math. Returns (score, report_lines).

    Scoring: each solved tier costs its best tokens; unsolved +150;
    skipped/DNF +200; every hard refusal +25; over-time +100.
    """
    lines = []
    total_best = 0
    solved = 0
    penalties = 0
    for r in sorted(results, key=lambda x: x["level"]):
        dnf = r.get("dnf", False)
        best = r.get("best")
        refusals = r.get("refusals", 0)
        if dnf or not best:
            status = "DNF" if dnf else "unsolved"
            penalties += DNF_PENALTY if dnf else SKIP_PENALTY
        else:
            status = "%d tok%s" % (best, " +OT" if r.get("over_time") else "")
            total_best += best
            solved += 1
        penalties += REFUSAL_PENALTY * refusals
        if r.get("over_time"):
            penalties += OT_PENALTY
        lines.append("  T%-2d %-18s %3d ref | %s"
                     % (r["level"], status, refusals, r.get("verdict") or ""))
    score = total_best + penalties
    header = "SIM SCORECARD (%.0f min clock)" % minutes
    footer = "score: %d adj-tok | %d/%d tiers solved" % (
        score, solved, len(results))
    return score, [header] + lines + [footer]


class DrillController:
    """Stateful drill for the web UI."""

    def __init__(self, dtype, models=None, level=None, strict=None,
                 practice=False, clock=time.time):
        self.type = dtype
        self.clock = clock
        self.practice = bool(practice)
        self.queue, strict_default = make_queue(dtype, models=models, level=level)
        self.strict_default = True if strict is None else strict
        self.strict_override = strict
        self.index = -1
        self.current = None
        self.results = []
        self.started_at = clock()
        self.minutes = sim_minutes() if dtype == "sim" else None
        self.deadline = (self.started_at + self.minutes * 60) if dtype == "sim" else None

    # -- helpers ---------------------------------------------------------------

    def _strict_for(self):
        if self.type in ("gauntlet", "sim", "daily"):
            return True
        return bool(self.strict_override)

    def remaining_s(self):
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - self.clock())

    def expired(self):
        rem = self.remaining_s()
        return rem is not None and rem <= 5 and self.index < len(self.queue)

    # -- lifecycle -------------------------------------------------------------

    def start(self):
        return self.start_next()

    def start_next(self):
        if self.expired():
            self._record_dnf_remaining()
            self.current = None
            return self.status()
        self.index += 1
        if self.index >= len(self.queue):
            self.current = None
            return self.status()
        item = self.queue[self.index]
        budget = PER_TIER_BUDGET_S if self.type == "gauntlet" else None
        self.current = GameSession(
            item["level"], item["model"],
            strict=self._strict_for(),
            crescendo=False,
            forced_secret=item.get("secret"),
            practice=self.practice,
        )
        st = self.current.state()
        st.update({
            "active": True,
            "type": self.type,
            "practice": self.practice,
            "drill_type": self.type,
            "index": self.index,
            "total": len(self.queue),
            "drill_index": self.index,
            "drill_total": len(self.queue),
            "per_tier_budget_s": budget,
            "remaining_s": self.remaining_s(),
        })
        return st

    def attack(self, payload):
        if self.current is None:
            return {"error": "drill finished"}
        res = self.current.attack(payload)
        if res.get("error"):
            return res
        if res.get("done") or res.get("win"):
            # a solved tier is complete; an exhausted crescendo-style done also advances
            if res.get("win"):
                self._finalize_current(dnf=False)
                self.current = None
        if self.expired():
            if self.current is not None:
                self.current.abandon()
                self._finalize_current(dnf=True)
                self.current = None
            self._record_dnf_remaining()
        return res

    def skip_current(self):
        """User bail-out: scored as DNF per competition rules.

        Always advances exactly one slot, whether or not a tier is currently
        live - safe against duplicate/rapid calls.
        """
        if self.current is not None:
            self.current.abandon()
            self._finalize_current(dnf=True)
            self.current = None
        elif self.index + 1 < len(self.queue):
            # no live tier (duplicate call) - consume the NEXT slot as DNF
            nxt = self.queue[self.index + 1]
            self.results.append({"level": nxt["level"], "best": None,
                                 "dnf": True, "refusals": 0,
                                 "over_time": False, "model": nxt["model"],
                                 "turns": 0, "verdict": None})
            self.index += 1
        if self.expired():
            self._record_dnf_remaining()
            self.current = None
            return self.status()
        if self.index + 1 < len(self.queue):
            return self.start_next()
        return self.status()

    def advance_or_finish(self):
        if self.index + 1 >= len(self.queue) or self.expired():
            if self.expired():
                self._record_dnf_remaining()
            self.current = None
            return self.status()
        return self.start_next()

    # -- bookkeeping -----------------------------------------------------------

    def _finalize_current(self, dnf):
        s = self.current.summary()
        s["dnf"] = dnf
        s["model"] = self.current.model
        if self.type == "gauntlet":
            elapsed = self.clock() - self.started_at
            s["over_time"] = s["over_time"] or elapsed > PER_TIER_BUDGET_S * (self.index + 1)
        self.results.append(s)

    def _record_dnf_remaining(self):
        while self.index + 1 < len(self.queue):
            nxt = self.queue[self.index + 1]
            self.index += 1
            self.results.append({"level": nxt["level"], "best": None,
                                 "dnf": True, "refusals": 0,
                                 "over_time": False, "model": nxt["model"],
                                 "turns": 0, "verdict": None})

    def _done_now(self):
        if self.current is not None:
            return False
        if self.deadline is not None:
            return self.remaining_s() <= 5
        return self.index >= len(self.queue) - 1

    def scorecard(self):
        results = [r for r in self.results]
        minutes = self.minutes or (PER_TIER_BUDGET_S / 60.0)
        return build_scorecard(results, minutes)

    def share_string(self):
        if self.type != "daily" or not self.results:
            return None
        r = self.results[0]
        date = datetime.date.today()
        return daily.share_string(date, r["level"], r.get("best") or 0,
                                  bool(r.get("best")))

    def status(self):
        cur = None
        if self.current is not None:
            cur = {
                "level": self.current.level,
                "tier_label": tiers.tier_label(self.current.level),
                "hint": self.current.state().get("hint"),
                "model": self.current.model,
                "done": self.current.done,
                "bootstrap_lines": self.current.bootstrap_lines,
            }
        done = self._done_now()
        card = None
        share = None
        if done:
            score, lines = self.scorecard()
            card = {"score": score, "lines": lines}
            share = self.share_string()
        return {
            "type": self.type,
            "total": len(self.queue),
            "index": self.index,
            "current": cur,
            "remaining_s": round(self.remaining_s(), 0) if self.remaining_s() is not None else None,
            "results": self.results,
            "done": done,
            "scorecard": card,
            "share_string": share,
        }
