"""Payload technique taxonomy + heatmap renderer.

After each solve you tag the technique that did it. Over time attempts.jsonl
becomes a personal research dataset: which techniques crack which model
families and which defense classes.
"""

from collections import defaultdict

from . import storage

TECHNIQUES = [
    ("A", "AUTHORITY", "fake authority / policy / system framing"),
    ("R", "ROLEPLAY", "fiction, persona, hypothetical frames"),
    ("E", "ENCODING", "base64/rot13/hex channel tricks"),
    ("C", "CRESCENDO", "gradual multi-turn escalation"),
    ("T", "TOOL_ABUSE", "abused a tool surface"),
    ("I", "INDIRECT_INJECTION", "payload via retrieved content/data channel"),
    ("S", "SOCIAL_ENGINEERING", "urgency, empathy, debugging claims"),
    ("D", "DIRECT_ASK", "plain ask worked - take the free win"),
    ("O", "OTHER", "anything else (note it in the payload)"),
]

CODES = {c: name for c, name, _ in TECHNIQUES}
TAG_PROMPT = "tag technique [%s] (enter=skip): " % "/".join(c for c, _, _ in TECHNIQUES)


def name_for(code):
    return CODES.get((code or "").strip().upper())


def _load_tagged():
    path = storage._path("attempts.jsonl")
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json_loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if e.get("technique"):
                    rows.append(e)
    except FileNotFoundError:
        pass
    return rows


def json_loads(line):
    import json

    return json.loads(line)


def heatmap_data():
    """Structured matrices for the web UI: technique x model and x tier."""
    rows = _load_tagged()
    out = {"techniques": [(c, n) for c, n, _ in TECHNIQUES],
           "by_model": {"cols": [], "rows": {}},
           "by_tier": {"cols": [], "rows": {}}}

    def build(keyfn, bucket):
        wins = defaultdict(list)
        cols = set()
        for e in rows:
            k = keyfn(e)
            cols.add(k)
            wins[(e["technique"], k)].append(e.get("payload_tokens", 0))
        out[bucket]["cols"] = sorted(cols)
        for code, name, _desc in TECHNIQUES:
            row = {}
            for c in out[bucket]["cols"]:
                toks = wins.get((name, c), [])
                if toks:
                    row[c] = {"wins": len(toks),
                              "avg": round(sum(toks) / len(toks), 1)}
            if row:
                out[bucket]["rows"][name] = row

    build(lambda e: str(e.get("model", "?")), "by_model")
    build(lambda e: "T%s" % e.get("level", "?"), "by_tier")
    return out


def render_heatmap():
    rows = _load_tagged()
    print("\n=== TECHNIQUE HEATMAP ===")
    if not rows:
        print("No tagged solves yet. Win a tier and tag the technique.")
        print("=========================\n")
        return

    def matrix(keyfn, title):
        wins = defaultdict(int)
        toks = defaultdict(list)
        for e in rows:
            k = keyfn(e)
            wins[k] += 1
            toks[k].append(e.get("payload_tokens", 0))
        cols = sorted({k for k in wins})
        print("\n%s" % title)
        header = "%-20s" % "technique"
        for c in cols:
            header += "%14s" % str(c)[:13]
        print(header)
        for code, name, _desc in TECHNIQUES:
            line = "%-20s" % name[:19]
            any_row = False
            for c in cols:
                n = wins.get((name, c), 0)
                avg = sum(toks.get((name, c), [0])) / max(1, len(toks.get((name, c), [1])))
                cell = "%d/%.0f" % (n, avg) if n else "-"
                line += "%14s" % cell
                any_row = any_row or bool(n)
            if any_row:
                print(line)
        print("(cell = wins/avg-tokens)")

    matrix(lambda e: (e["technique"], e.get("model", "?")),
           "technique x MODEL (your transfer dataset)")
    matrix(lambda e: (e["technique"], "T%s" % e.get("level", "?")),
           "technique x TIER (what cracks which defense)")
    print("=========================\n")
