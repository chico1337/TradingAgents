"""Load user-editable TradingAgents configuration."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

from tradingagents.default_config import DEFAULT_CONFIG


DEFAULT_LOCAL_CONFIG = "tradingagents.local.yaml"

_ENV_CONFIG_KEYS = {
    "TRADINGAGENTS_RESULTS_DIR": "results_dir",
    "TRADINGAGENTS_CACHE_DIR": "data_cache_dir",
    "TRADINGAGENTS_MEMORY_LOG_PATH": "memory_log_path",
}

_VALID_PRIMARY_HORIZONS = {"short_term", "mid_term"}


def deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge override values into base and return base."""
    for key, value in override.items():
        if (
            isinstance(value, Mapping)
            and isinstance(base.get(key), dict)
        ):
            deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _load_yaml_file(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Config file not found: {path}")
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return data


def _apply_environment_overrides(config: dict[str, Any]) -> None:
    for env_key, config_key in _ENV_CONFIG_KEYS.items():
        value = os.getenv(env_key)
        if value:
            config[config_key] = value


def validate_config(config: Mapping[str, Any]) -> None:
    primary_horizon = str(config.get("primary_recommendation_horizon", "")).strip().lower()
    if primary_horizon not in _VALID_PRIMARY_HORIZONS:
        raise ValueError("primary_recommendation_horizon must be 'short_term' or 'mid_term'.")

    analysts = config.get("selected_analysts")
    if analysts is not None and not isinstance(analysts, (list, str)):
        raise ValueError("selected_analysts must be a list or comma-separated string.")


def load_config(
    config_path: str | Path | None = None,
    *,
    cli_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load TradingAgents config from defaults, local YAML, env, and CLI overrides.

    Precedence is:
    1. built-in DEFAULT_CONFIG
    2. YAML config file, if present
    3. environment path overrides
    4. explicit CLI overrides
    """
    config = copy.deepcopy(DEFAULT_CONFIG)

    if config_path is None:
        yaml_path = Path.cwd() / DEFAULT_LOCAL_CONFIG
        yaml_data = _load_yaml_file(yaml_path, required=False)
    else:
        yaml_path = Path(config_path).expanduser()
        yaml_data = _load_yaml_file(yaml_path, required=True)

    deep_merge(config, yaml_data)
    _apply_environment_overrides(config)

    if cli_overrides:
        deep_merge(config, {k: v for k, v in cli_overrides.items() if v is not None})

    validate_config(config)
    return config
