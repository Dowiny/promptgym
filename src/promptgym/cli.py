"""PromptGym CLI - argument parsing and mode dispatch."""

import argparse
import datetime
import random
import sys
import time

from . import analytics, daily, providers, session, storage, tiers
from .drills import build_scorecard


def build_parser():
    p = argparse.ArgumentParser(
        prog="promptgym",
        description="Extract a guarded secret from a defended LLM bot at minimum "
                    "token cost. 16 defense tiers. Train locally, transfer anywhere.",
    )
    p.add_argument("--version", action="store_true", help="print version and exit")
    p.add_argument("--levels", nargs="*", type=int, metavar="N",
                   help="play specific tiers (1-%d)" % tiers.MAX_TIER)
    p.add_argument("--compare", action="store_true",
                   help="transfer drill: cycle every model in PROMPTGYM_MODELS per tier")
    p.add_argument("--strict", action="store_true",
                   help="every payload's tokens accumulate into session cost")
    p.add_argument("--judge", action="store_true",
                   help="LLM judges grade solves (payload quality / concealment)")
    p.add_argument("--stats", action="store_true", help="cheapest-known-solve table")
    p.add_argument("--export", choices=["csv"], help="export transfer matrix")
    p.add_argument("--daily", action="store_true",
                   help="today's seeded puzzle (same worldwide), shareable result")
    p.add_argument("--gauntlet", action="store_true",
                   help="random 5-tier timed exam with report card")
    p.add_argument("--weak", action="store_true",
                   help="auto-queue your worst tiers from attempt history")
    p.add_argument("--report", action="store_true",
                   help="weekly review: habits, miss patterns, suggestions")
    p.add_argument("--heatmap", action="store_true",
                   help="technique x model / technique x tier matrices from tagged solves")
    p.add_argument("--crescendo", action="store_true",
                   help="multi-turn escalation drill with refusal-budget tracking "
                        "(turns via PROMPTGYM_CRESCENDO_TURNS, default 8)")
    p.add_argument("--sim", action="store_true",
                   help="competition simulator: continuous clock, strict scoring, "
                        "random tiers (minutes via PROMPTGYM_SIM_MINUTES, default 60)")
    p.add_argument("--practice", action="store_true",
                   help="practice wheels: non-credential secrets on tiers 1-4 "
                        "so safety-trained models stay solvable while learning "
                        "ladder mechanics")
    p.add_argument("--serve", action="store_true",
                   help="launch the local web UI (127.0.0.1 only)")
    p.add_argument("--port", type=int, default=8765, metavar="N",
                   help="port for --serve (default 8765)")
    p.add_argument("--doctor", action="store_true", help="verify setup end to end")
    return p


def _validate_levels(levels):
    for lv in levels:
        if not 1 <= lv <= tiers.MAX_TIER:
            sys.exit("Tiers are 1-%d." % tiers.MAX_TIER)
    return levels


def _migrate_notice():
    copied = storage.migrate_legacy()
    for src in copied:
        print("[migrated] %s" % src)


def run_gauntlet(args):
    rng = random.Random()
    levels = rng.sample(range(1, tiers.MAX_TIER + 1), 5)
    budget = 20 * 60
    print("\n*** GAUNTLET: 5 random tiers, 20 min each. Solve fast, golf fast. ***")
    results = []
    for lv in levels:
        r = session.play_level(lv, providers.PRIMARY_MODEL, strict=args.strict,
                               judge_mode=args.judge, time_budget=budget,
                               quiet_header=False)
        results.append(r)
    print("\n=== GAUNTLET REPORT CARD ===")
    total_best = 0
    solved_n = 0
    ot_n = 0
    for r in sorted(results, key=lambda x: x["level"]):
        best = "%3d tok" % r["best"] if r["best"] else "  -"
        if r["best"]:
            total_best += r["best"]
            solved_n += 1
        if r["over_time"]:
            ot_n += 1
        print("  T%-2d %-10s %s%s" % (
            r["level"], best, "OT!" if r["over_time"] else "",
            "" if not args.strict else "  (strict spent %s tok)" % r["strict_cost"]))
    score = total_best + ot_n * 50
    print("score: %s (%d/5 solved, %d over time)" % (
        ("%d adj-tok" % score) if solved_n else "no solves", solved_n, ot_n))
    print("============================")


def run_sim(args):
    raw = providers.env("PROMPTGYM_SIM_MINUTES", default="60")
    try:
        minutes = max(5.0, float(raw))
    except ValueError:
        minutes = 60.0
    sequence = random.sample(range(1, tiers.MAX_TIER + 1), 3)
    print("\n*** COMPETITION SIMULATOR: 3 unknown tiers | %.0f min shared clock | "
          "strict scoring ***" % minutes)
    deadline = time.time() + minutes * 60
    results = []
    for lv in sequence:
        remaining = deadline - time.time()
        if remaining <= 5:
            results.append({"level": lv, "dnf": True, "best": None,
                            "refusals": 0, "over_time": False})
            continue
        print("\n--- clock: %.0f min left ---" % (remaining / 60.0))
        r = session.play_level(lv, providers.PRIMARY_MODEL, strict=True,
                               judge_mode=args.judge, time_budget=remaining,
                               practice=args.practice)
        r.setdefault("dnf", False)
        results.append(r)
    score, lines = build_scorecard(results, minutes)
    print("")
    for line in lines:
        print(line)
    print("====================")


def run_daily(args):
    today = datetime.date.today()
    tid, secret = daily.daily_puzzle(today)
    tier = tiers.REGISTRY[tid]
    print("\n*** DAILY PUZZLE %s | T%d %s ***" % (today.isoformat(), tid, tier.name))
    print("Everyone worldwide gets this exact puzzle today. Golf it, then share "
          "your result string.\n")
    result = session.play_level(tid, providers.PRIMARY_MODEL, strict=True,
                                judge_mode=False, forced_secret=secret,
                                practice=args.practice)
    share = daily.share_string(today, tid, result.get("best") or 0, result["solved"])
    print("\nshare: %s\n" % share)


def run_weak(args):
    queue = analytics.weak_tiers()
    if not queue:
        print("Not enough history to find weak tiers yet - clear some tiers first.")
        return
    print("\nweak-spot queue: %s" % ", ".join("T%d" % t for t in queue))
    answer = input("Run this queue now? [Y/n] ").strip().lower()
    if answer in ("n", "no"):
        print("Cancelled. Run manually with --levels %s"
              % " ".join(str(t) for t in queue))
        return
    for lv in queue:
        session.play_level(lv, providers.PRIMARY_MODEL, strict=args.strict,
                           judge_mode=args.judge)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.version:
        from . import __version__

        print("promptgym %s" % __version__)
        return 0

    _migrate_notice()

    if args.doctor:
        return 0 if providers.doctor() else 1
    if args.serve:
        from . import webapp

        webapp.serve(port=args.port)
        return 0
    if not providers.API_KEY:
        sys.exit(
            "No API key found. Set OPENAI_API_KEY (or PROMPTGYM_API_KEY).\n"
            "$0 path: install Ollama, `ollama pull llama3.1`, set "
            "PROMPTGYM_PROVIDER=ollama - no key needed."
        )
    if args.export:
        out = storage.export_matrix_csv()
        print("transfer matrix written: %s" % out)
        return 0
    if args.stats:
        session.show_stats()
        return 0
    if args.report:
        analytics.weekly_report()
        return 0
    if args.heatmap:
        from . import taxonomy

        taxonomy.render_heatmap()
        return 0
    if args.sim:
        run_sim(args)
        return 0
    if args.daily:
        run_daily(args)
        return 0
    if args.gauntlet:
        run_gauntlet(args)
        return 0
    if args.weak:
        run_weak(args)
        return 0

    levels = _validate_levels(args.levels) if args.levels else list(range(1, tiers.MAX_TIER + 1))

    crescendo_kwargs = {"practice": args.practice}
    if args.crescendo:
        raw = providers.env("PROMPTGYM_CRESCENDO_TURNS", default="8")
        try:
            turn_budget = max(2, int(raw))
        except ValueError:
            turn_budget = 8
        crescendo_kwargs.update({"crescendo": True, "max_turns": turn_budget})

    if args.compare:
        for lv in levels:
            for m in providers.MODELS:
                session.play_level(lv, m, strict=args.strict, judge_mode=args.judge,
                                   **crescendo_kwargs)
        print("\n--- TRANSFER MATRIX AFTER COMPARE RUN ---")
        session.show_stats()
    else:
        for lv in levels:
            session.play_level(lv, providers.PRIMARY_MODEL,
                               strict=args.strict, judge_mode=args.judge,
                               **crescendo_kwargs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
