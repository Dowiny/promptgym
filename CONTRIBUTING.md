# Contributing to PromptGym

Thanks for helping build the best local AI red-team gym. Two rules of the house:

1. **Defensive-training scope only.** Bots are synthetic, secrets are fake, and nothing here should target real systems or generate harmful content.
2. **Manual-posture design.** Features that automate submissions against external platforms are out of scope forever.

## Adding a defense tier (the most valuable contribution)

Tiers live in `src/promptgym/tiers.py` as registry entries. A tier needs:

```python
def p17(s):
    return _base(s) + (
        "YOUR DEFENSE SPEC: describe exactly how the bot protects "
        "the access code, what it must never do, and how it replies "
        "when suspicious. Be concrete - vagueness makes tiers trivial."
    )

# in REGISTRY:
17: Tier(17, "Name", "short class label",
         "real-world mapping line", prompt=p17),
```

Checklist for a good tier:

- [ ] Fresh secret is embedded in the system prompt (use `_base(s)`).
- [ ] Defense is beatable but not free: it should resist at least the
      obvious ladder (`print the code`, `repeat everything above`).
- [ ] The win condition stays `check_win` unless the defense genuinely
      changes what "leak" means (see `check_win_format` for tier 13).
- [ ] Real-world mapping line references an OWASP LLM Top 10 item,
      MITRE ATLAS technique, or a named production pattern.
- [ ] Add tests in `tests/`: checker behavior + one e2e flow if you added
      a new `kind`.

### New mechanics kinds

If your tier needs more than a system prompt (a second model, response
post-processing, bootstrap turns), add a `kind` and handle it in
`session.py` next to `"gatekeeper"` / `"toolcall"` / `"memory"`. Keep the
mechanics in their own module (`gatekeeper.py`, `toolsim.py`) so tests can
exercise them without a live model.

## Dev setup

```bash
pip install -e ".[dev,tokens,vision]"
python -m pytest tests -q     # all tests run offline via mock provider
python -m ruff check src tests
```

CI must stay green: ruff (E/F/W/I) + pytest on Linux and Windows.

## Style

- Python 3.9+ compatible (no match statements, no `X | Y` type unions).
- `%`-formatting and f-strings both fine; keep modules dependency-free
  (stdlib only; optional imports guarded with try/except like tiktoken/pillow).
- Comments explain *why* (defense rationale), not *what*.

## Reporting issues

Include: provider preset (or BASE_URL), model name, tier number, and whether
`--doctor` passes. Payloads and logs from your own sessions are yours -
sanitize before pasting.
