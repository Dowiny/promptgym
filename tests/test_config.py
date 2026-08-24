import json

import promptgym.config as config
import promptgym.providers as providers


def test_mask():
    assert config.mask("") == ""
    assert config.mask("short") == "set"
    m = config.mask("gsk_1234567890abcd")
    assert m.startswith("gsk_") and "…" in m and m.endswith("abcd")
    assert "1234567890" not in m


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "settings.json")
    clean = config.save({"api_key": "gsk_test_1234567890", "model": "llama-x",
                         "bogus_field": "dropped"})
    assert set(clean) == {"api_key", "model"}
    loaded = config.load()
    assert loaded["model"] == "llama-x"
    config.clear()
    assert config.load() == {}


def test_resolved_view_masks_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(providers, "API_KEY", "gsk_supersecretvalue99")
    view = config.resolved_view()
    raw = json.dumps(view)
    assert "gsk_supersecretvalue99" not in raw
    assert "…" in view["api_key_masked"] or view["api_key_masked"] == "set"


def test_save_and_apply_updates_providers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "settings.json")
    old_model = providers.PRIMARY_MODEL
    old_url = providers.BASE_URL
    try:
        view = config.save_and_apply({"model": "test-model-9",
                                      "base_url": "http://127.0.0.1:9/v1",
                                      "models": "test-model-9, other-m"})
        assert view["model"] == "test-model-9"
        assert providers.PRIMARY_MODEL == "test-model-9"
        assert providers.BASE_URL == "http://127.0.0.1:9/v1"
        assert "other-m" in providers.MODELS
    finally:
        providers.update_config(model=old_model, base_url=old_url)


def test_save_preserves_key_when_field_blank(tmp_path, monkeypatch):
    """The classic accident: edit models, leave key field empty, save -> key gone."""
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "settings.json")
    config.save({"api_key": "gsk_original_123456", "model": "old-model"})
    config.save({"model": "new-model"})            # no api_key field sent
    loaded = config.load()
    assert loaded["api_key"] == "gsk_original_123456"
    assert loaded["model"] == "new-model"


def test_precedence_settings_over_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(providers, "PRIMARY_MODEL", "env-model")
    config.save({"model": "file-model"})
    view = config.resolved_view()
    assert view["model"] == "file-model"
    config.clear()
