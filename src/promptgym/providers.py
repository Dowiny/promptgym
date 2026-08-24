"""Provider layer: any OpenAI-compatible chat-completions endpoint.

Env vars (PROMPTGYM_* preferred, legacy AOCHAOS_* still honored):
    OPENAI_API_KEY / PROMPTGYM_API_KEY   auth token
    PROMPTGYM_BASE_URL / AOCHAOS_BASE_URL
    PROMPTGYM_PROVIDER                    one of PRESETS (fills base_url if unset)
    PROMPTGYM_MODEL / AOCHAOS_MODEL       primary practice model
    PROMPTGYM_MODELS / AOCHAOS_MODELS     comma list enabling --compare
    PROMPTGYM_JUDGE_MODEL                 judge/watcher model (defaults to primary)
    PROMPTGYM_PRICES / AOCHAOS_PRICES     "model=in,out;..." USD per 1M tokens
"""

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

USER_AGENT = "PromptGym/4.3 (local training client)"
NET_DIAGNOSE = ""  # human-readable reason for the last network failure
_TRANSPORT = {"mode": None}  # None | "urllib" | "curl" - remembered per process

PRESETS = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
        "key_required": False,
        "note": "free + local; run `ollama pull llama3.1` first",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "key_required": True,
        "note": "free tier, fast; gpt-oss family is HARDENED - holds even T1-T4",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "key_required": True,
        "note": "some :free models; strength varies by model",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_required": True,
        "note": "paid; frontier models = hardened everywhere",
    },
}


def env(*names, default=""):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


PROVIDER_NAME = env("PROMPTGYM_PROVIDER").lower().strip()

BASE_URL = env("PROMPTGYM_BASE_URL", "AOCHAOS_BASE_URL")
if not BASE_URL:
    BASE_URL = PRESETS.get(PROVIDER_NAME, {}).get(
        "base_url", "https://api.openai.com/v1"
    )
API_KEY = env("PROMPTGYM_API_KEY", "OPENAI_API_KEY")
PRIMARY_MODEL = env("PROMPTGYM_MODEL", "AOCHAOS_MODEL") or PRESETS.get(
    PROVIDER_NAME, {}).get("model", "gpt-4o-mini")

_extra = [m.strip() for m in env("PROMPTGYM_MODELS", "AOCHAOS_MODELS").split(",") if m.strip()]
MODELS = _extra if _extra else [PRIMARY_MODEL]
if PRIMARY_MODEL not in MODELS:
    MODELS.insert(0, PRIMARY_MODEL)

JUDGE_MODEL = env("PROMPTGYM_JUDGE_MODEL", "AOCHAOS_JUDGE_MODEL") or PRIMARY_MODEL

# Pristine env-derived values, captured before any runtime mutation so
# "reset to environment" can always restore them.
ENV_DEFAULTS = {
    "provider": PROVIDER_NAME,
    "base_url": BASE_URL,
    "api_key": API_KEY,
    "model": PRIMARY_MODEL,
    "judge_model": JUDGE_MODEL,
    "models": ",".join(MODELS),
}


def update_config(provider=None, base_url=None, api_key=None, model=None,
                  judge_model=None, models=None, prices=None):
    """Mutate live globals. Used by the web settings tab (saved config wins)."""
    global PROVIDER_NAME, BASE_URL, API_KEY, PRIMARY_MODEL, JUDGE_MODEL, MODELS, PRICES
    if provider:
        PROVIDER_NAME = provider.lower().strip()
        preset = PRESETS.get(PROVIDER_NAME, {})
        if not base_url and preset.get("base_url"):
            BASE_URL = preset["base_url"]
        if not model and preset.get("model"):
            model = preset["model"]
    if base_url:
        BASE_URL = base_url.strip()
    if api_key:
        API_KEY = api_key.strip()
    if model:
        PRIMARY_MODEL = model.strip()
        if PRIMARY_MODEL not in MODELS:
            MODELS.insert(0, PRIMARY_MODEL)
    if judge_model:
        JUDGE_MODEL = judge_model.strip()
    if models:
        parsed = [m.strip() for m in str(models).split(",") if m.strip()]
        if parsed:
            MODELS = parsed
            if PRIMARY_MODEL not in MODELS:
                MODELS.insert(0, PRIMARY_MODEL)
    if prices:
        table = parse_prices(str(prices))
        if table:
            PRICES.update(table)


def parse_prices(raw):
    table = {}
    for chunk in raw.split(";"):
        if "=" not in chunk:
            continue
        model, prices = chunk.split("=", 1)
        parts = prices.split(",")
        if len(parts) == 2:
            try:
                table[model.strip()] = (float(parts[0]), float(parts[1]))
            except ValueError:
                pass
    return table


DEFAULT_PRICES = {"default": (0.15, 0.60)}
PRICES = parse_prices(env("PROMPTGYM_PRICES", "AOCHAOS_PRICES")) or dict(DEFAULT_PRICES)


def usd_cost(model, prompt_tokens, completion_tokens):
    pin, pout = PRICES.get(model, PRICES.get("default", (0.15, 0.60)))
    return (prompt_tokens / 1e6) * pin + (completion_tokens / 1e6) * pout


def _looks_blocked(status, text):
    """Cloudflare-style wall (e.g. Groq's 'error code: 1010') or dead network."""
    if status is None:
        return True  # network-level failure (reset/timeout) - fallback eligible
    if status in (403, 503, 429):
        low = text[:400].lower()
        return "1010" in low or "cloudflare" in low or "error code" in low
    return False


def _via_curl(method, url, obj, api_key, timeout):
    """Last-resort transport: OS curl binary has a different TLS fingerprint."""
    exe = shutil.which("curl") or shutil.which("curl.exe")
    if not exe:
        return None, ""
    cmd = [exe, "-sS", "--max-time", str(int(timeout)),
           "-X", method,
           "-H", "Authorization: Bearer " + (api_key or ""),
           "-H", "Content-Type: application/json",
           "-H", "User-Agent: " + USER_AGENT,
           "-H", "Accept: application/json"]
    if obj is not None:
        cmd += ["-d", json.dumps(obj)]
    cmd += ["-w", "\n%{http_code}", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        out = proc.stdout.decode("utf-8", "ignore")
        if "\n" in out:
            body, _, code = out.rpartition("\n")
            return int(code) if code.strip().isdigit() else None, body
        return None, out
    except Exception:  # noqa: BLE001 - curl missing/failed = no transport
        return None, ""


def _http_json(method, url, obj, api_key, timeout=60):
    """JSON request via urllib with browser-grade headers; auto-falls back to
    curl when a Cloudflare wall blocks Python's TLS fingerprint.

    Returns (status:int|None, text:str). Never raises.
    """
    global NET_DIAGNOSE

    def urllib_attempt():
        global NET_DIAGNOSE
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        data = None
        if obj is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(obj).encode()
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                body = ""
            return e.code, body
        except Exception as e:  # noqa: BLE001 - reset/timeout/DNS
            NET_DIAGNOSE = repr(e)[:120]
            return None, ""

    mode = _TRANSPORT["mode"]
    if mode == "curl":
        status, text = _via_curl(method, url, obj, api_key, timeout)
        return status, text

    status, text = urllib_attempt()
    if _looks_blocked(status, text):
        cstatus, ctext = _via_curl(method, url, obj, api_key, timeout)
        if cstatus is not None and not _looks_blocked(cstatus, ctext):
            _TRANSPORT["mode"] = "curl"
            NET_DIAGNOSE = "urllib blocked (%s) - using curl transport" % (
                status if status else NET_DIAGNOSE)
            return cstatus, ctext
        NET_DIAGNOSE = ("blocked by provider edge (HTTP %s)" %
                        (status if status else NET_DIAGNOSE))
    elif status is not None:
        _TRANSPORT["mode"] = "urllib"
        NET_DIAGNOSE = ""
    return status, text


def chat(messages, model):
    """One chat completion. Returns (content, prompt_tokens, completion_tokens)."""
    from .textutils import count_tokens

    url = BASE_URL.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 300,
    }
    status, text = _http_json("POST", url, body, API_KEY, timeout=90)
    if status is None:
        return "[ERROR] %s (%s)" % (text[:120], NET_DIAGNOSE), 0, 0
    if status >= 400:
        return "[API ERROR %d] %s" % (status, text[:200]), 0, 0
    try:
        data = json.loads(text)
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        pt = usage.get("prompt_tokens", 0) or 0
        ct = usage.get("completion_tokens", 0) or 0
        if not pt:
            pt = sum(count_tokens(m.get("content", "")) for m in messages
                     if isinstance(m.get("content"), str))
        if not ct:
            ct = count_tokens(content)
        return content, pt, ct
    except Exception as e:  # noqa: BLE001 - malformed provider payload
        return "[ERROR] malformed response: %s" % e, 0, 0


def list_models():
    """Returns list of model ids from GET /models, or None if unreachable.

    Sets NET_DIAGNOSE with a human-readable reason on failure so the doctor
    can explain WHY instead of a bare FAIL.
    """
    global NET_DIAGNOSE
    status, text = _http_json("GET", BASE_URL.rstrip("/") + "/models", None,
                              API_KEY, timeout=20)
    if status is None:
        NET_DIAGNOSE = "network failure: %s" % NET_DIAGNOSE
        return None
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001 - html error pages etc.
        NET_DIAGNOSE = "HTTP %s non-JSON: %s" % (status, text[:80])
        return None
    if isinstance(data, dict) and data.get("error"):
        msg = str(data["error"].get("message", data["error"]))[:100]
        NET_DIAGNOSE = "HTTP %s from provider: %s" % (status, msg)
        return None
    ids = [m.get("id", "") for m in data.get("data", [])]
    return ids


def doctor(return_entries=False):
    """Setup verification. Prints a table; optionally returns the entries."""
    print("\n--- PROMPTGYM DOCTOR ---")
    ok = True
    entries = []

    def line(name, state, detail=""):
        nonlocal ok
        mark = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}.get(state, "[ ?? ]")
        if state == "FAIL":
            ok = False
        entries.append({"check": name, "state": state, "detail": detail})
        print("%s %-22s %s" % (mark, name, detail))

    import sys

    line("python", "OK" if sys.version_info >= (3, 9) else "FAIL", sys.version.split()[0])

    key_needed = PRESETS.get(PROVIDER_NAME, {}).get("key_required", True) or bool(API_KEY)
    line(
        "api key",
        "OK" if API_KEY else ("FAIL" if key_needed else "WARN"),
        ("set" if API_KEY else "missing")
        + (
            ""
            if API_KEY or key_needed
            else " (provider preset says optional)"
        ),
    )
    line("base url", "OK", BASE_URL)
    line("primary model", "OK", PRIMARY_MODEL)
    if JUDGE_MODEL != PRIMARY_MODEL:
        line("judge model", "OK", JUDGE_MODEL)

    models = list_models()
    if models is None:
        detail = "GET /models failed"
        if NET_DIAGNOSE:
            detail += " - " + NET_DIAGNOSE
        else:
            detail += " - wrong URL/key/provider down?"
        line("connectivity", "FAIL", detail)
    elif len(models) == 0:
        line("connectivity", "WARN", "reachable but listed no models")
    elif PRIMARY_MODEL in models:
        line("model hosted", "OK", "%d models listed" % len(models))
    else:
        line("model hosted", "WARN", "not in provider catalog (%d listed)" % len(models))

    try:
        import tiktoken  # noqa: F401

        line("tiktoken", "OK", "exact token counts")
    except ImportError:
        line("tiktoken", "WARN", "pip install tiktoken (using chars/4 estimate)")

    try:
        import PIL  # noqa: F401

        line("pillow", "OK", "tier 11 image-injection available")
    except ImportError:
        line("pillow", "WARN", "pip install pillow to unlock tier 11")

    from .storage import DATA_DIR

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        line("data dir", "OK", str(DATA_DIR))
    except Exception as e:  # noqa: BLE001
        line("data dir", "FAIL", "%s (%s)" % (DATA_DIR, e))

    preset = PROVIDER_NAME
    if preset and preset in PRESETS:
        line("preset", "OK", "%s - %s" % (preset, PRESETS[preset]["note"]))

    print("--- DOCTOR DONE: %s ---\n" % ("ALL CRITICAL CHECKS PASSED" if ok else "PROBLEMS FOUND"))
    if return_entries:
        return {"ok": ok, "entries": entries,
                "model": PRIMARY_MODEL, "base_url_host": BASE_URL.split("//")[-1].split("/")[0],
                "api_key_set": bool(API_KEY)}
    return ok


def wait_retry(attempt):
    """Simple backoff helper for rate-limited free tiers."""
    time.sleep(min(2 ** attempt, 8))

