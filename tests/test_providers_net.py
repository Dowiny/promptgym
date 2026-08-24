"""Transport-layer unit tests: Cloudflare-block detection + diagnostics."""

import promptgym.providers as providers


def test_detects_cf_1010():
    assert providers._looks_blocked(403, "error code: 1010")
    assert providers._looks_blocked(403, "<html>Cloudflare</html>")


def test_detects_network_failure():
    assert providers._looks_blocked(None, "")  # status None = dead network


def test_does_not_flag_normal_responses():
    assert not providers._looks_blocked(200, '{"data": []}')
    assert not providers._looks_blocked(401, '{"error":"invalid api key"}')
    assert not providers._looks_blocked(404, "not found")


def test_flags_rate_limit_wall():
    assert providers._looks_blocked(429, "error code: 1010")


def test_net_diagnose_cleared_on_success(monkeypatch):
    calls = {"n": 0}

    class R:
        status = 200
        text = '{"data": [{"id": "m1"}]}'

        def read(self):
            return self.text.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=60):
        calls["n"] += 1
        return R()

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    providers.NET_DIAGNOSE = "stale error"
    ids = providers.list_models()
    assert ids == ["m1"]
    assert providers.NET_DIAGNOSE == ""
    assert providers._TRANSPORT["mode"] == "urllib"
