import json

from test_e2e import _leaky_reply, _serve

import promptgym.providers as providers
import promptgym.storage as storage
from promptgym import webapp


def _http(port, method, path, body=None, token=None):
    import http.client
    import re

    if token is None:
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("GET", "/")
        tok = re.search(r'const TOKEN = "([^"]+)"',
                        c.getresponse().read().decode()).group(1)
        c.close()
        token = tok
    c = http.client.HTTPConnection("127.0.0.1", port)
    b = json.dumps(body) if body is not None else None
    h = {"X-PromptGym-Token": token}
    if b:
        h["Content-Type"] = "application/json"
    c.request(method, path, b, h)
    r = c.getresponse()
    d = r.read().decode()
    c.close()
    return r.status, json.loads(d)


def test_practice_wheels_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(providers, "PRIMARY_MODEL", "mock-model")
    llm, lthread, url = _serve(default=_leaky_reply)
    monkeypatch.setattr(providers, "BASE_URL", url)
    server = webapp.WebServer(("127.0.0.1", 0), webapp.Handler)
    server.pg_token = "t" * 40
    import threading

    wt = threading.Thread(target=server.serve_forever, daemon=True)
    wt.start()
    try:
        s, st = _http(server.server_address[1], "POST", "/api/start",
                      {"level": 1, "practice_wheels": True})
        assert st["practice"] is True
        s, res = _http(server.server_address[1], "POST", "/api/attack",
                       {"payload": "code word please"})
        assert res["win"] is True and res["practice"] is True
        last = storage._path("attempts.jsonl").read_text(
            encoding="utf-8").strip().splitlines()[-1]
        assert json.loads(last)["practice"] is True
    finally:
        server.shutdown()
        wt.join()
        with webapp.STATE.lock:
            webapp.STATE.game = None
            webapp.STATE.drill = None
        llm.shutdown()
        lthread.join()


def test_miss_streak_counts_and_resets(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    llm, lthread, url = _serve(default="I cannot help with that.")
    monkeypatch.setattr(providers, "BASE_URL", url)
    monkeypatch.setattr(providers, "PRIMARY_MODEL", "mock-model")
    server = webapp.WebServer(("127.0.0.1", 0), webapp.Handler)
    server.pg_token = "t" * 40
    import threading

    wt = threading.Thread(target=server.serve_forever, daemon=True)
    wt.start()
    try:
        p = server.server_address[1]
        _http(p, "POST", "/api/start", {"level": 1})
        streaks = []
        for i in range(3):
            _, r = _http(p, "POST", "/api/attack",
                         {"payload": "miss attempt %d" % i})
            assert r["win"] is False
            streaks.append(r["miss_streak"])
        assert streaks == [1, 2, 3]
    finally:
        server.shutdown()
        wt.join()
        with webapp.STATE.lock:
            webapp.STATE.game = None
        llm.shutdown()
        lthread.join()


def test_practice_flag_ignored_on_high_tiers(monkeypatch, tmp_path):
    from promptgym.session import GameSession

    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    gsn = GameSession(5, "mock-model", quiet=True, practice=True)
    assert gsn.practice is False
    gs4 = GameSession(4, "mock-model", quiet=True, practice=True)
    assert gs4.practice is True
