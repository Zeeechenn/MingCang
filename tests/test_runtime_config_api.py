import pytest


def test_runtime_config_returns_current_settings(monkeypatch):
    from backend.api.routes import get_runtime_config

    response = get_runtime_config()

    assert response["persisted"] is False
    assert response["profile"] in {"auto", "test1_legacy_qlib", "new_framework"}
    assert "new_framework_entry_threshold" in response
    assert "weights" in response
    assert "kill_switch_active" in response


def test_update_runtime_config_mutates_allowed_settings(monkeypatch):
    from backend.api.routes import get_runtime_config, update_runtime_config
    from backend.config import settings

    old_profile = settings.paper_trading_profile
    old_threshold = settings.new_framework_entry_threshold
    old_adx = settings.adx_filter_enabled

    try:
        response = update_runtime_config({
            "paper_trading_profile": "new_framework",
            "new_framework_entry_threshold": 31,
            "adx_filter_enabled": True,
        })

        assert response["profile"] == "new_framework"
        assert response["new_framework_entry_threshold"] == 31
        assert response["adx_filter_enabled"] is True
        assert get_runtime_config()["new_framework_entry_threshold"] == 31
    finally:
        settings.paper_trading_profile = old_profile
        settings.new_framework_entry_threshold = old_threshold
        settings.adx_filter_enabled = old_adx


def test_update_runtime_config_rejects_unknown_keys():
    from fastapi import HTTPException

    from backend.api.routes import update_runtime_config

    try:
        update_runtime_config({"database_url": "sqlite:///surprise.db"})
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Unsupported runtime config key" in exc.detail
    else:
        raise AssertionError("expected unsupported runtime config key to be rejected")


def test_update_runtime_config_rejects_invalid_types_and_weights():
    from fastapi import HTTPException

    from backend.api.routes import update_runtime_config

    with pytest.raises(HTTPException) as exc:
        update_runtime_config({"max_position_per_stock": "large"})
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        update_runtime_config({
            "weight_quant": 0.2,
            "weight_technical": 0.6,
            "weight_sentiment": 0.4,
        })
    assert exc.value.status_code == 400
