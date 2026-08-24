"""Local web frontend for PromptGym. Stdlib only, binds 127.0.0.1 ONLY.

Launch: python -m promptgym --serve [--port 8765]

Security posture:
- Binds 127.0.0.1 only; never expose to your network.
- Session token (per-start, injected into served HTML) required on all
  /api/* requests -> cross-site pages cannot forge actions or reads.
- Host header must be 127.0.0.1/localhost on this port -> DNS rebinding dead.
- The API key is write-only over HTTP: responses carry a masked suffix,
  never the raw value.
"""

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import analytics, config, providers, storage, taxonomy, tiers
from .drills import DrillController
from .session import GameSession

STATIC = Path(__file__).parent / "static" / "index.html"
MAX_BODY = 64 * 1024


class AppState:
    """Single active game or drill (solo trainer). Guarded by a lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.game = None
        self.drill = None

    def new_game(self, level, strict, judge_mode, crescendo, practice=False):
        max_turns = None
        if crescendo:
            raw = providers.env("PROMPTGYM_CRESCENDO_TURNS",
                                "AOCHAOS_CRESCENDO_TURNS", default="8")
            try:
                max_turns = max(2, int(raw))
            except ValueError:
                max_turns = 8
        with self.lock:
            self.game = GameSession(level, providers.PRIMARY_MODEL,
                                    strict=strict, judge_mode=judge_mode,
                                    crescendo=crescendo, max_turns=max_turns,
                                    practice=practice)
            return self.game.state()

    def snapshot(self):
        with self.lock:
            if self.game is None:
                return {"configured": False}
            return self.game.state()

    def reset(self):
        with self.lock:
            self.game = None
            self.drill = None


STATE = AppState()


def _json_bytes(obj, status=200):
    body = json.dumps(obj).encode()
    return status, "application/json", body


class Handler(BaseHTTPRequestHandler):
    server_version = "PromptGym/4.3"

    def log_message(self, fmt, *args):  # quiet
        pass

    # -- security -------------------------------------------------------------

    def _host_ok(self):
        port = self.server.server_address[1]
        allowed = ("127.0.0.1:%d" % port, "localhost:%d" % port)
        host = self.headers.get("Host", "")
        return host in allowed

    def _token_ok(self):
        expected = getattr(self.server, "pg_token", "")
        supplied = self.headers.get("X-PromptGym-Token", "")
        return bool(expected) and secrets.compare_digest(supplied, expected)

    # -- plumbing -------------------------------------------------------------

    def _send(self, status, ctype, body):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:  # noqa: BLE001
            return {}

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            self._send(403, "text/plain", b"forbidden host")
            return
        route = self.path.split("?")[0]

        if route == "/" or route == "/index.html":
            try:
                body = STATIC.read_bytes().replace(
                    b"__PG_TOKEN__", self.server.pg_token.encode())
                self._send(200, "text/html; charset=utf-8", body)
            except FileNotFoundError:
                self._send(500, "text/plain", b"index.html missing")
            return

        if not route.startswith("/api/"):
            self._send(404, "text/plain", b"not found")
            return
        if not self._token_ok():
            self._send(403, "application/json",
                       json.dumps({"error": "bad session token"}).encode())
            return

        if route == "/api/state":
            snap = STATE.snapshot()
            pin, pout = providers.PRICES.get(
                providers.PRIMARY_MODEL,
                providers.PRICES.get("default", (0.15, 0.60)))
            snap["provider"] = {
                "model": providers.PRIMARY_MODEL,
                "base_url_host": providers.BASE_URL.split("//")[-1].split("/")[0],
                "api_key_set": bool(providers.API_KEY),
                "price_in_per_m": pin,
                "price_out_per_m": pout,
                "judge_model": providers.JUDGE_MODEL,
            }
            snap["tiers"] = [
                {"id": tid, "name": t.name, "kind": t.kind}
                for tid, t in sorted(tiers.REGISTRY.items())
            ]
            snap["version"] = __import__("promptgym").__version__
            self._send(*_json_bytes(snap))
            return

        if route == "/api/stats":
            by_model = storage.load_solves()
            spend = storage.load_spend()
            self._send(*_json_bytes({
                "solves": {m: records for m, records in sorted(by_model.items())},
                "refusal_thresholds": {"%s|%s" % k: round(v, 2)
                                       for k, v in analytics.refusal_stats().items()},
                "total_usd": spend.get("total_usd", 0.0),
            }))
            return

        if route == "/api/heatmap":
            self._send(*_json_bytes(taxonomy.heatmap_data()))
            return

        if route == "/api/doctor":
            result = providers.doctor(return_entries=True)
            self._send(*_json_bytes(result))
            return

        if route == "/api/history":
            path = storage._path("attempts.jsonl")
            rows = []
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                rows.append(json.loads(line))
                            except Exception:  # noqa: BLE001
                                pass
            except FileNotFoundError:
                pass
            self._send(*_json_bytes({"history": rows[-50:][::-1]}))
            return

        if route == "/api/config":
            view = config.resolved_view()
            view["presets"] = sorted(providers.PRESETS.keys())
            view["presets_detail"] = providers.PRESETS
            self._send(*_json_bytes(view))
            return

        if route == "/api/report":
            self._send(*_json_bytes(analytics.weekly_report_data()))
            return

        if route == "/api/export.csv":
            rows = storage.export_matrix_rows()
            csv = "\n".join(
                ",".join('"%s"' % str(c).replace('"', '""') for c in row)
                for row in rows)
            self._send(200, "text/csv; charset=utf-8",
                       csv.encode("utf-8"))
            return

        if route == "/api/drill/status":
            if STATE.drill is None:
                self._send(*_json_bytes({"active": False}))
                return
            st = STATE.drill.status()
            st["active"] = True
            self._send(*_json_bytes(st))
            return        self._send(404, "text/plain", b"not found")

    def do_POST(self):  # noqa: N802
        # ALWAYS drain the request body first: responding to a POST with
        # unread body bytes makes Windows reset the connection (client sees
        # WinError 10053) instead of delivering our status code.
        data = self._body()
        if not self._host_ok():
            self._send(403, "text/plain", b"forbidden host")
            return
        route = self.path.split("?")[0]
        if not route.startswith("/api/"):
            self._send(404, "text/plain", b"not found")
            return
        if not self._token_ok():
            self._send(403, "application/json",
                       json.dumps({"error": "bad session token"}).encode())
            return

        if route == "/api/config":
            try:
                view = config.save_and_apply(data)
            except Exception as e:  # noqa: BLE001
                self._send(*_json_bytes({"error": str(e)}, 400))
                return
            self._send(*_json_bytes(view))
            return

        if route == "/api/config/reset":
            config.clear()
            ed = providers.ENV_DEFAULTS
            providers.update_config(
                provider=ed["provider"], base_url=ed["base_url"],
                api_key=ed["api_key"], model=ed["model"],
                judge_model=ed["judge_model"], models=ed["models"])
            self._send(*_json_bytes(config.resolved_view()))
            return

        if route == "/api/start":
            try:
                level = int(data.get("level", 1))
            except (TypeError, ValueError):
                level = 1
            if not 1 <= level <= tiers.MAX_TIER:
                self._send(*_json_bytes({"error": "bad tier"}, 400))
                return
            STATE.reset()  # free play cancels any drill
            state = STATE.new_game(
                level,
                strict=bool(data.get("strict")),
                judge_mode=bool(data.get("judge")),
                crescendo=bool(data.get("crescendo")),
                practice=bool(data.get("practice_wheels")),
            )
            self._send(*_json_bytes(state))
            return

        if route == "/api/drill/start":
            dtype = str(data.get("type", "")).lower()
            known = {"daily", "gauntlet", "sim", "weak", "compare"}
            if dtype not in known:
                self._send(*_json_bytes({"error": "unknown drill type"}, 400))
                return
            STATE.reset()
            with STATE.lock:
                try:
                    STATE.drill = DrillController(
                        dtype,
                        models=str(data.get("models") or ""),
                        level=data.get("level"),
                        strict=data.get("strict"),
                        practice=bool(data.get("practice_wheels")),
                    )
                    STATE.drill.start()
                except Exception as e:  # noqa: BLE001
                    STATE.drill = None
                    self._send(*_json_bytes({"error": str(e)}, 400))
                    return
                status = STATE.drill.status()
            status["active"] = True
            self._send(*_json_bytes(status))
            return

        if route == "/api/drill/skip":
            if STATE.drill is None:
                self._send(*_json_bytes({"error": "no drill"}, 400))
                return
            with STATE.lock:
                STATE.drill.skip_current()
                st = STATE.drill.status()
            st["active"] = True
            self._send(*_json_bytes(st))
            return

        if route == "/api/attack":
            payload = str(data.get("payload", ""))
            if STATE.drill is not None:
                if STATE.drill.current is None:
                    st = STATE.drill.advance_or_finish()
                    st["active"] = True
                    self._send(*_json_bytes(st))
                    return
                with STATE.lock:
                    result = STATE.drill.attack(payload)
                if result.get("error"):
                    self._send(*_json_bytes(result, 400))
                    return
                if result.get("win") or result.get("done"):
                    with STATE.lock:
                        STATE.drill.advance_or_finish()
                with STATE.lock:
                    dstatus = STATE.drill.status()
                dstatus["active"] = True
                result["drill"] = {
                    "type": dstatus["type"],
                    "index": dstatus["index"],
                    "total": dstatus["total"],
                    "remaining_s": dstatus["remaining_s"],
                    "current": dstatus["current"],
                    "results": dstatus["results"],
                    "scorecard": dstatus["scorecard"],
                    "share_string": dstatus["share_string"],
                    "done": dstatus["done"],
                }
                self._send(*_json_bytes(result))
                return

            game = STATE.game
            if game is None:
                self._send(*_json_bytes({"error": "start a session first"}, 400))
                return
            with STATE.lock:
                result = game.attack(payload)
            status = 400 if result.get("error") else 200
            self._send(*_json_bytes(result, status))
            return

        if route == "/api/tag":
            holder = STATE.drill.current if STATE.drill else STATE.game
            if holder is None:
                self._send(*_json_bytes({"error": "no session"}, 400))
                return
            name = holder.tag(str(data.get("code", "")))
            self._send(*_json_bytes({"technique": name}))
            return

        self._send(404, "text/plain", b"not found")


class WebServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(port=8765, open_browser=True):
    config.apply_saved()  # saved settings override env defaults at boot
    server = WebServer(("127.0.0.1", port), Handler)
    server.pg_token = secrets.token_urlsafe(32)  # fresh per server start
    url = "http://127.0.0.1:%d" % port
    print("\nPromptGym Web UI -> %s  (Ctrl+C to stop)" % url)
    print("Bound to 127.0.0.1 only - do not expose to your network.")
    if open_browser:
        try:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception:  # noqa: BLE001
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nweb ui stopped.")
