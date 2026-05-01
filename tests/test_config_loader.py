from pathlib import Path

import pytest

from tradingagents.config_loader import load_config
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.mark.unit
def test_load_config_uses_defaults_without_local_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRADINGAGENTS_RESULTS_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_CACHE_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_MEMORY_LOG_PATH", raising=False)

    config = load_config()

    assert config["llm_provider"] == DEFAULT_CONFIG["llm_provider"]
    assert config["quick_think_llm"] == DEFAULT_CONFIG["quick_think_llm"]
    assert config["primary_recommendation_horizon"] == "short_term"


@pytest.mark.unit
def test_load_config_applies_yaml_overrides_and_deep_merges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "tradingagents.local.yaml"
    config_file.write_text(
        """
llm_provider: litellm
quick_think_llm: pentagi-cheap
data_vendors:
  news_data: alpha_vantage
""",
        encoding="utf-8",
    )

    config = load_config()

    assert config["llm_provider"] == "litellm"
    assert config["quick_think_llm"] == "pentagi-cheap"
    assert config["data_vendors"]["news_data"] == "alpha_vantage"
    assert config["data_vendors"]["core_stock_apis"] == DEFAULT_CONFIG["data_vendors"]["core_stock_apis"]


@pytest.mark.unit
def test_environment_path_values_override_yaml(tmp_path, monkeypatch):
    config_file = tmp_path / "profile.yaml"
    config_file.write_text("results_dir: /from/yaml\n", encoding="utf-8")
    monkeypatch.setenv("TRADINGAGENTS_RESULTS_DIR", "/from/env")

    config = load_config(config_file)

    assert config["results_dir"] == "/from/env"


@pytest.mark.unit
def test_cli_overrides_win_over_yaml_and_environment(tmp_path, monkeypatch):
    config_file = tmp_path / "profile.yaml"
    config_file.write_text(
        """
llm_provider: openai
results_dir: /from/yaml
data_vendors:
  news_data: alpha_vantage
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADINGAGENTS_RESULTS_DIR", "/from/env")

    config = load_config(
        config_file,
        cli_overrides={
            "llm_provider": "litellm",
            "results_dir": "/from/cli",
            "data_vendors": {"news_data": "yfinance"},
        },
    )

    assert config["llm_provider"] == "litellm"
    assert config["results_dir"] == "/from/cli"
    assert config["data_vendors"]["news_data"] == "yfinance"


@pytest.mark.unit
def test_invalid_primary_horizon_is_rejected(tmp_path):
    config_file = tmp_path / "bad.yaml"
    config_file.write_text("primary_recommendation_horizon: quarterly\n", encoding="utf-8")

    with pytest.raises(ValueError, match="primary_recommendation_horizon"):
        load_config(config_file)
