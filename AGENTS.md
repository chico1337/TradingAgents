# AGENTS.md

Compact repo notes for future OpenCode sessions. Keep additions here factual and repo-specific.

## Project Shape

- `pyproject.toml` is the packaging source of truth; `requirements.txt` only contains `.`.
- Installable packages are `tradingagents*` and `cli*`; the console script is `tradingagents = cli.main:app`.
- Main entrypoints: `tradingagents` or `python -m cli.main` for the Typer CLI, `main.py` for a direct NVDA demo run, and `web_ui.py` for the standalone Streamlit UI.
- Runtime/library code lives under `tradingagents/`; terminal UX lives under `cli/`; ad hoc provider smoke tooling lives under `scripts/`.

## Commands

- Install locally with `pip install .`. The README suggests Python 3.13, Docker uses Python 3.12, and `pyproject.toml` only requires `>=3.10`.
- This workspace may not have a bare `python` on PATH; use `python3` or `./venv/bin/python` when the active environment is unclear.
- CLI help: `python -m cli.main --help`. A focused non-interactive run can use flags like `--ticker NVDA --date 2026-01-15 --analysts market,news --research-depth 1`.
- Docker CLI run: copy `.env.example` to `.env`, fill keys, then run `docker compose run --rm tradingagents`.
- Ollama Docker profile: `docker compose --profile ollama run --rm tradingagents-ollama`.
- Default test command: `python -m pytest`; focused examples: `python -m pytest tests/test_config_loader.py` or `python -m pytest -m unit`.
- No repo-defined lint, typecheck, pre-commit, task-runner, or CI workflow config was found. Do not invent `ruff`, `mypy`, `make`, `tox`, or GitHub Actions commands.

## Config And Secrets

- Copy `tradingagents.example.yaml` to `tradingagents.local.yaml` for local defaults; `tradingagents.local.yaml` is gitignored and auto-loaded from the current working directory.
- Config precedence is `DEFAULT_CONFIG` < YAML config < env path overrides < explicit CLI overrides.
- Only these env vars override paths: `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_MEMORY_LOG_PATH`.
- Keep secrets in `.env` or `.env.enterprise`, not YAML. The CLI loads both `.env` and `.env.enterprise`; Docker compose loads `.env`.
- `primary_recommendation_horizon` must be `short_term` or `mid_term`; `selected_analysts` must be a list or comma-separated string.
- `ollama`, `openrouter`, and `litellm` accept arbitrary model names; other providers are checked against the local model catalog.

## Runtime Gotchas

- `TradingAgentsGraph` is the core orchestrator. Selected analysts are optional/dynamic, but after analysts the graph always runs bull/bear research, research manager, trader, risk debate, and portfolio manager.
- Structured-output agents are Research Manager, Trader, and Portfolio Manager. They render Pydantic outputs back to markdown and fall back to plain `llm.invoke()` if structured output fails.
- The final machine-readable signal is parsed from the Portfolio Manager markdown `**Rating**:` field; `SignalProcessor` should not make another LLM call.
- Portfolio output is dual-horizon; the leading `**Rating**` follows `primary_recommendation_horizon`.
- Data vendor routing is configured through `data_vendors`/`tool_vendors`; built-in vendors are `yfinance` and `alpha_vantage`, and tool-level overrides beat category defaults.

## State And Artifacts

- Default generated paths are `./reports`, `~/.tradingagents/cache`, and `~/.tradingagents/memory/trading_memory.md`; all are gitignored/local state.
- Decision memory is append-only markdown and is injected only into the Portfolio Manager prompt, not earlier agents.
- Checkpoint resume is opt-in with `--checkpoint`. Checkpoint DBs are per ticker under `~/.tradingagents/cache/checkpoints/<TICKER>.db`, keyed by ticker plus date.
- `--clear-checkpoints` deletes all saved checkpoint DBs before running; do not use it casually on a user's workspace.
- CLI saved reports use `reports/<TICKER>_<timestamp>/` with `1_analysts/` through `5_portfolio/` plus `complete_report.md`; in-run logs live under `results_dir/<ticker>/<date>/`.
- `web_ui.py` writes history differently from the CLI, so check its report/history code before changing report browsing.

## Testing Notes

- `tests/conftest.py` injects placeholder API keys, so unit tests should not require real provider credentials.
- Current pytest markers include `unit`, `integration`, and `smoke`, but no tests are marked integration/smoke at this time.
- Real-provider structured-output smoke tests are separate from pytest, e.g. `OPENAI_API_KEY=... python scripts/smoke_structured_output.py openai`.
- Tests assert structured-output fallback, deterministic signal parsing, config precedence, CLI prompt skipping when flags/config are present, checkpoint clearing/resume behavior, and memory-log formatting. Preserve those contracts when editing related code.
