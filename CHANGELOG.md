# Changelog

## 4.3.1 - 2026-08-24

Calibration release: model-strength guidance, practice wheels, and three
first-session bug fixes reported by real usage.

### Added
- **Practice wheels** (🛞 toggle / `--practice`): non-credential secret
  framing on tiers 1–4 so safety-trained model families (gpt-oss etc.)
  stay solvable while learning ladder mechanics. Flagged `"practice": true`
  in attempt logs; honored inside drill modes too.
- **Miss-streak hints**: 6/10 consecutive misses on low tiers explain that
  the model family itself may be holding the tier, with suggested escapes.
- **MODEL-CALIBRATION.md**: seeded findings table (gpt-oss-120b held T1 vs
  the entire classic ladder incl. side-channels; qwen3.6 think-block token
  overhead) + community contribution template.
- Provider presets now carry strength notes; SETUP tab auto-fills base-url
  and hosted model when switching presets (kills the URL/model mismatch trap).
- README rewritten for first-time users: 60-second start, ASCII demo,
  FAQ covering every first-session failure mode.

## 4.3.0 - 2026-08-24

Browser parity: every terminal capability now lives in the web UI, plus a
Settings tab and hardened localhost security.

### Added
- Drill modes in the browser via the mode strip: DAILY (seeded worldwide
  puzzle + copyable share string), GAUNTLET (5 random tiers, 20 min each),
  SIM (shared 60-min clock), WEAK (auto-queued worst tiers), COMPARE
  (same tier across an editable model list -> transfer matrix).
- Drill HUD: progress, live sim countdown, SKIP button scored as DNF,
  scorecard on completion.
- SETUP tab: paste your API key once (stored in gitignored
  data/settings.json, shown masked forever), switch provider/base-url/
  models/prices without touching env vars; "reset to environment" restores.
- REPORT tab: weekly miss-rate, per-tier win rates, judge trend, fixation
  warnings, suggested queue.
- CSV export button (transfer matrix download).
- Security hardening for the localhost server:
  * per-start session token injected into the page, required on all /api
    calls -> cross-site pages cannot forge requests;
  * Host header must be 127.0.0.1/localhost on the served port -> DNS
    rebinding rejected;
  * API keys are write-only over HTTP (masked suffix responses only).

### Fixed
- `--daily` now uses the seeded secret end to end (share strings are truly
  identical worldwide).
- Provider connectivity on networks where provider CDNs (e.g. Groq behind
  Cloudflare) reject Python's TLS fingerprint: browser-grade headers plus an
  automatic curl.exe fallback transport, and doctor now explains WHY a
  connection failed instead of a bare FAIL.

### Compatibility
- CLI flags/outputs unchanged; drills share the same scoring engine.

## 4.2.0 - 2026-08-24

The Web UI. Same engine, new arena.

### Added
- `--serve [--port]`: local web frontend at 127.0.0.1 (stdlib server +
  single-file vanilla JS - still zero required dependencies).
- Arena: tier picker, STRICT/JUDGE/CRESCENDO toggles, chat-style attacking,
  per-payload token chips, WIN/REFUSAL/EVASION/PARTIAL badges, refusal-budget
  meter, crescendo turn counter + verdict banners, judge scores.
- Live token+cost preview estimated client-side while typing (before the LLM
  responds); exact counts arrive with each result.
- One-click technique-tag modal on every win (feeds the heatmap).
- Sidebar panels: cheapest-solve table with refusal thresholds, technique
  heatmaps, doctor checks, attempt history.
- Security posture: localhost bind only; API key never leaves the server
  process and is never sent to the browser.

### Changed
- Core loop refactored into a shared GameSession engine; CLI and web drive
  identical mechanics. All CLI flags and outputs unchanged.

## 4.1.0 - 2026-08-24

The four training-loop upgrades: refusal budgets, crescendo drilling,
technique tagging, and competition simulation.

### Added
- Refusal-budget tracker: every miss classified REFUSAL / EVASION / PARTIAL,
  live per-session counter, and per-model-per-tier "avg refusals before win"
  thresholds in `--stats` (`response_class` field in attempts.jsonl).
- `--crescendo` multi-turn escalation drill: turn budget
  (PROMPTGYM_CRESCENDO_TURNS, default 8), verdicts ESCALATION CLEAN /
  BRUTE FORCE / FAILED.
- Technique taxonomy: tag every solve (AUTHORITY, ROLEPLAY, ENCODING,
  CRESCENDO, TOOL_ABUSE, INDIRECT_INJECTION, SOCIAL_ENGINEERING,
  DIRECT_ASK, OTHER -> `technique` field) and render `--heatmap`
  technique x model + technique x tier matrices.
- `--sim` competition simulator: 3 random tiers on one shared clock
  (PROMPTGYM_SIM_MINUTES, default 60), strict scoring, DNF/OT/refusal
  penalties, scorecard report.

### Compatibility
- Fully additive: existing attempts.jsonl entries load unchanged; all v4
  flags behave identically.

## 4.0.0 - 2026-08-24

The "ultimate edition" rewrite. Same scoring soul, ten times the arsenal.

### Added
- Five new defense tiers (12-16): multi-agent gatekeeper with SENTINEL
  watcher model, output-format lock (strict JSON), self-audit redaction,
  tool-call hijack dual-judge sim (Gray Swan IPI style), memory lock
  (seal after onboarding reveal).
- `--daily` seeded worldwide puzzle with shareable result string.
- `--gauntlet` random 5-tier timed exam with report card and OT penalties.
- `--weak` weak-spot auto-queue from your attempt history.
- `--report` weekly review: miss-rate, judge trend, fixation warnings.
- `--doctor` one-shot setup verification (connectivity, model hosted,
  tiktoken/pillow presence, data dir).
- `--export csv` transfer-matrix dump.
- Provider presets: ollama / groq / openrouter / openai via
  `PROMPTGYM_PROVIDER`; Ollama path needs no API key at all.
- `PROMPTGYM_JUDGE_MODEL` for separate judge/watcher models.

### Changed
- Restructured single-file trainer into an installable package
  (`pip install -e .`, console command `promptgym`).
- Env vars now accept both `PROMPTGYM_*` and legacy `AOCHAOS_*`.

### Compatibility
- Data files unchanged (solves.json v2, attempts.jsonl, spend.json).
- First run auto-copies records from a detected legacy agents-of-chaos
  folder; originals untouched.
- All v3 flags (`--levels/--compare/--strict/--judge/--stats`) behave as before.

### Lineage
- v3: cipher tiers 9-10, image tier 11, --judge, spend tracking.
- v2: --compare transfer drills, strict mode, per-model records.
- v1: eight tiers, best-solve tracking.
