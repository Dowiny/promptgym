"""Analytics: weak-spot detection and weekly review generation."""

import re
import time
from collections import defaultdict

from . import storage


def _load_attempts():
    path = storage._path("attempts.jsonl")
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json_load(line))
                except Exception:  # noqa: BLE001
                    continue
    except FileNotFoundError:
        pass
    return entries


def json_load(line):
    import json

    return json.loads(line)


def _parse_ts(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except Exception:  # noqa: BLE001
        return 0.0


def weak_tiers(max_levels=6):
    """Rank tiers needing work. Priority: unsolved > low win-rate > token waste."""
    attempts = _load_attempts()
    solves = storage.load_solves()

    stats = defaultdict(lambda: {"n": 0, "wins": 0, "win_toks": [], "misses": 0})
    ever_won = {}  # tier -> cheapest winning tokens seen in attempts (fallback best)
    for e in attempts:
        lv = str(e.get("level"))
        s = stats[lv]
        s["n"] += 1
        if e.get("win"):
            s["wins"] += 1
            tok = e.get("payload_tokens", 0)
            s["win_toks"].append(tok)
            if lv not in ever_won or tok < ever_won[lv]:
                ever_won[lv] = tok
        else:
            s["misses"] += 1

    scored = []
    for lv, s in stats.items():
        if lv == "11" or (not lv.isdigit()):
            # image tier needs pillow/vision; skip in auto-queue
            continue
        win_rate = s["wins"] / float(s["n"]) if s["n"] else 0.0
        avg_win = sum(s["win_toks"]) / len(s["win_toks"]) if s["win_toks"] else None
        best = None
        for records in solves.values():
            if lv in records:
                b = records[lv]["tokens"]
                best = b if best is None else min(best, b)
        if best is None:
            best = ever_won.get(lv)
        if s["wins"] == 0:
            priority = 0  # attempted but never cracked
        elif win_rate < 0.3:
            priority = 1
        else:
            waste = (avg_win / best) if (avg_win and best) else 2.0
            priority = 2 + (1 if waste > 1.8 else 0)
        scored.append((priority, -s["n"], int(lv)))

    scored.sort()
    return [lv for _, _, lv in scored[:max_levels]]


def refusal_stats():
    """Per (model, tier): avg hard refusals encountered before each win.

    Scans attempts chronologically; a 'run' of refusals accumulates until the
    next win, then deposits into the total. High averages = stubborn defense;
    the number is the model's learned give-in threshold for that tier.
    """
    runs = {}
    for e in _load_attempts():
        key = (str(e.get("model", "?")), str(e.get("level", "?")))
        d = runs.setdefault(key, {"run": 0, "total": 0, "wins": 0})
        if e.get("win"):
            d["wins"] += 1
            d["total"] += d["run"]
            d["run"] = 0
        elif e.get("response_class") == "REFUSAL":
            d["run"] += 1
    return {k: v["total"] / float(v["wins"]) for k, v in runs.items() if v["wins"]}


def weekly_report_data(days=7):
    """Structured weekly review for both the CLI printer and the web tab."""
    attempts = _load_attempts()
    cutoff = time.time() - days * 86400
    recent = [e for e in attempts if _parse_ts(e.get("ts", "")) >= cutoff]
    data = {"days": days, "attempts": 0, "wins": 0, "miss_rate_pct": None,
            "spend_usd": 0.0, "per_tier": {}, "judge_avg": None,
            "judge_count": 0, "worst_payloads": [], "fixations": [],
            "suggested_queue": weak_tiers(4)}

    if not recent:
        return data

    wins = [e for e in recent if e.get("win")]
    misses = [e for e in recent if not e.get("win")]
    by_level = defaultdict(lambda: {"n": 0, "w": 0})
    for e in recent:
        by_level[str(e.get("level"))]["n"] += 1
        if e.get("win"):
            by_level[str(e.get("level"))]["w"] += 1

    judge_scores = [e["judge_score"] for e in recent
                    if e.get("judge_score") is not None]

    repeated = defaultdict(int)
    for e in misses:
        key = re.sub(r"[^a-z ]", "", str(e.get("payload", "")).lower())[:24].strip()
        if len(key) >= 10:
            repeated[key] += 1

    data.update({
        "attempts": len(recent),
        "wins": len(wins),
        "miss_rate_pct": round(100.0 * len(misses) / max(1, len(recent)), 1),
        "spend_usd": round(sum(e.get("usd", 0.0) for e in recent), 6),
        "per_tier": {lv: {"attempts": d["n"], "wins": d["w"],
                          "win_pct": round(100.0 * d["w"] / d["n"], 1)}
                     for lv, d in sorted(by_level.items(), key=lambda kv: int(kv[0]))},
        "judge_avg": (round(sum(judge_scores) / len(judge_scores), 2)
                      if judge_scores else None),
        "judge_count": len(judge_scores),
        "worst_payloads": [
            {"level": e.get("level"), "tokens": e.get("payload_tokens", 0),
             "payload": str(e.get("payload", ""))[:60]}
            for e in sorted(misses, key=lambda x: -x.get("payload_tokens", 0))[:5]
        ],
        "fixations": [{"opening": k, "count": v} for k, v in
                      sorted(repeated.items(), key=lambda kv: -kv[1])[:3]
                      if v >= 3],
    })
    return data


def weekly_report(days=7):
    """Print the Sunday-review style report from the last N days of attempts."""
    d = weekly_report_data(days)
    print("\n=== PROMPTGYM WEEKLY REPORT (last %d days) ===" % days)
    if not d["attempts"]:
        print("No attempts logged in this window. Grind first, report later.")
        return

    print("attempts: %d | wins: %d | miss-rate: %.0f%% | spend: $%.4f"
          % (d["attempts"], d["wins"], d["miss_rate_pct"], d["spend_usd"]))

    print("\nper-tier:")
    for lv, s in d["per_tier"].items():
        print("  T%-2s %3d attempts, %d wins (%.0f%%)"
              % (lv, s["attempts"], s["wins"], s["win_pct"]))

    if d["judge_avg"] is not None:
        print("\njudge trend: avg %.1f/10 over %d judged solves"
              % (d["judge_avg"], d["judge_count"]))

    print("\ntop expensive habits (longest missing payloads):")
    for w in d["worst_payloads"]:
        print("  T%-2s %3d tok | %s..." % (w["level"], w["tokens"],
                                           re.sub(r"\s+", " ", w["payload"])))

    if d["fixations"]:
        print("\nfixation warnings (same opening tried 3+ times without a win):")
        for f in d["fixations"]:
            print('  "%s..." x%d' % (f["opening"], f["count"]))

    if d["suggested_queue"]:
        print("\nsuggested next session (--weak picks this automatically):")
        print("  python trainer: tiers %s"
              % ", ".join("T%d" % t for t in d["suggested_queue"]))
    print("=== END REPORT ===\n")
