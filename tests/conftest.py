import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-ci")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_transport(monkeypatch):
    """Every test starts with a clean provider-transport slate.

    The urllib-vs-curl decision is cached at module level; without this
    fixture, one test's transport choice leaks into every later test.
    """
    import promptgym.providers as _p

    monkeypatch.setattr(_p, "_TRANSPORT", {"mode": None})
    monkeypatch.setattr(_p, "NET_DIAGNOSE", "")
    yield
