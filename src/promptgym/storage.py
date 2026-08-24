"""Progress storage: solves.json, attempts.jsonl, spend.json.

Format is identical to trainer v3 so existing records carry over. If the
classic agents-of-chaos folder is found nearby and this repo has no data yet,
records are copied in automatically (never moved).
"""

import json
import os
import shutil
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("PROMPTGYM_DATA_DIR", str(REPO_ROOT / "data")))

# Where v3 records might live. Point PROMPTGYM_LEGACY_DIR at your old
# trainers' folder explicitly; the built-in guesses cover common layouts.
LEGACY_DIRS = []
_explicit = os.environ.get("PROMPTGYM_LEGACY_DIR")
if _explicit:
    LEGACY_DIRS.append(Path(_explicit))
LEGACY_DIRS += [
    REPO_ROOT.parent / "agents-of-chaos",
    Path.cwd() / "agents-of-chaos",
]

FILES = ("solves.json", "attempts.jsonl", "spend.json")


def _path(name):
    return DATA_DIR / name


def migrate_legacy():
    """Copy v3 data files from a detected legacy folder. Returns list copied."""
    copied = []
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - doctor reports unwritable dirs
        return copied
    for name in FILES:
        target = _path(name)
        if target.exists():
            continue
        for legacy in LEGACY_DIRS:
            src = legacy / name
            if src.exists():
                try:
                    shutil.copy2(src, target)
                    copied.append(str(src))
                except Exception:  # noqa: BLE001
                    pass
                break
    return copied


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_solves():
    raw = load_json(_path("solves.json"), {})
    if not raw:
        return {}
    if raw.get("version") == 2:
        return raw["by_model"]
    migrated = {}
    for k, v in raw.items():
        if k.isdigit() and isinstance(v, dict) and "tokens" in v:
            migrated.setdefault("legacy-v1", {})[k] = v
    return migrated


def save_solves(by_model):
    save_json(_path("solves.json"), {"version": 2, "by_model": by_model})


def update_solves(level, payload, tokens, win, model):
    if not win:
        return None
    by_model = load_solves()
    tiers = by_model.setdefault(model, {})
    key = str(level)
    prev = tiers.get(key)
    if prev is None or tokens < prev["tokens"]:
        tiers[key] = {"payload": payload, "tokens": tokens}
        save_solves(by_model)
        return tokens
    return None


def log_attempt(level, payload, tokens, response, win, model, session_cost,
                judge_score=None, usd=0.0, response_class=None, technique=None,
                practice=False):
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "model": model,
        "payload": payload,
        "payload_tokens": tokens,
        "session_cost_so_far": session_cost,
        "win": win,
        "judge_score": judge_score,
        "usd": round(usd, 6),
        "response_class": response_class,
        "technique": technique,
        "practice": bool(practice),
        "response_excerpt": response[:150],
    }
    with open(_path("attempts.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def tag_last_attempt(technique):
    """Attach a technique to the newest attempt line (if untagged).

    Returns the technique name when applied, else None.
    """
    path = _path("attempts.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return None
    if not lines:
        return None
    try:
        entry = json.loads(lines[-1])
    except Exception:  # noqa: BLE001
        return None
    if entry.get("technique"):
        return None
    entry["technique"] = technique
    lines[-1] = json.dumps(entry)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return technique


def load_spend():
    return load_json(_path("spend.json"), {"total_usd": 0.0, "sessions": []})


def record_spend(model, usd, level):
    data = load_spend()
    data["total_usd"] = round(data["total_usd"] + usd, 6)
    data["sessions"].append(
        {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "level": level,
            "usd": round(usd, 6),
        }
    )
    if len(data["sessions"]) > 500:
        data["sessions"] = data["sessions"][-500:]
    save_json(_path("spend.json"), data)


def export_matrix_rows():
    """Cheapest-known-solve rows: [["model","tier","tokens","payload"], ...]"""
    by_model = load_solves()
    rows = [["model", "tier", "tokens", "payload"]]
    for model in sorted(by_model):
        for lv in sorted(by_model[model], key=int):
            s = by_model[model][lv]
            rows.append([model, lv, s["tokens"], s["payload"]])
    return rows


def export_matrix_csv(out_path=None):
    """Cheapest-known-solve table as CSV (per model per tier)."""
    import csv

    out_path = out_path or (_path("transfer-matrix.csv"))
    rows = export_matrix_rows()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return out_path
