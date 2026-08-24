"""Runtime configuration: data/settings.json overrides env-derived defaults.

Precedence per field: saved settings file > environment > preset defaults.
The API key is write-only over HTTP - GET responses carry a masked suffix,
never the raw value.
"""

import json

from . import providers
from .storage import DATA_DIR

CONFIG_PATH = DATA_DIR / "settings.json"

FIELDS = ("provider", "base_url", "api_key", "model", "judge_model",
          "models", "prices")


def load():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if k in FIELDS and v}
    except Exception:  # noqa: BLE001 - missing/corrupt file = defaults
        return {}


def save(cfg):
    """Merge-save: blank/missing fields PRESERVE previously stored values.

    Only non-empty incoming fields overwrite. This prevents the classic
    'edited one setting and wiped my API key' accident.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = load()
    incoming = {k: str(v).strip() for k, v in cfg.items() if k in FIELDS}
    incoming = {k: v for k, v in incoming.items() if v}
    merged = dict(existing)
    merged.update(incoming)
    CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def clear():
    try:
        CONFIG_PATH.unlink()
    except FileNotFoundError:
        pass


def mask(key):
    if not key:
        return ""
    if len(key) < 12:
        return "set"
    return "%s…%s" % (key[:4], key[-4:])


def resolved_view():
    """Everything the UI may see. Raw api_key NEVER leaves this process."""
    saved = load()
    ed = providers.ENV_DEFAULTS
    return {
        "provider": saved.get("provider", ed["provider"]),
        "base_url": saved.get("base_url", ed["base_url"]),
        "model": saved.get("model", ed["model"]),
        "judge_model": saved.get("judge_model", ed["judge_model"]),
        "models": saved.get("models", ed["models"]),
        "prices": saved.get("prices", ""),
        "api_key_masked": mask(saved.get("api_key") or providers.API_KEY),
        "api_key_source": "settings" if saved.get("api_key") else (
            "env" if providers.API_KEY else "none"),
        "config_path": str(CONFIG_PATH),
    }


def apply_saved():
    """Push saved settings into live provider globals (env stays fallback)."""
    saved = load()
    if saved:
        providers.update_config(**saved)


def save_and_apply(cfg):
    clean = save(cfg)
    providers.update_config(**clean)
    return resolved_view()
