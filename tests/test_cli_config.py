import pytest

from cli.main import get_user_selections, validate_cli_date


def _base_config():
    return {
        "output_language": "English",
        "analysis_date": "today",
        "selected_analysts": ["market", "news"],
        "research_depth": 1,
        "llm_provider": "litellm",
        "backend_url": "http://localhost:4000/v1",
        "quick_think_llm": "pentagi-cheap",
        "deep_think_llm": "pentagi-research",
        "google_thinking_level": None,
        "openai_reasoning_effort": None,
        "anthropic_effort": None,
        "short_term_horizon": "2-10 trading days",
        "mid_term_horizon": "1-3 months",
        "primary_recommendation_horizon": "short_term",
    }


@pytest.fixture(autouse=True)
def _disable_announcements(monkeypatch):
    monkeypatch.setattr("cli.main.fetch_announcements", lambda: [])
    monkeypatch.setattr("cli.main.display_announcements", lambda console, announcements: None)


@pytest.mark.unit
def test_config_defaults_skip_output_language_prompt(monkeypatch):
    monkeypatch.setattr(
        "cli.main.ask_output_language",
        lambda: pytest.fail("output language prompt should not run"),
    )
    monkeypatch.setattr(
        "cli.main.get_analysis_date",
        lambda: pytest.fail("analysis date prompt should not run"),
    )

    selections = get_user_selections(
        base_config=_base_config(),
        ticker="NVDA",
    )

    assert selections["output_language"] == "English"
    assert selections["analysis_date"] == validate_cli_date("today")
    assert [analyst.value for analyst in selections["analysts"]] == ["market", "news"]
    assert selections["research_depth"] == 1
    assert selections["llm_provider"] == "litellm"


@pytest.mark.unit
def test_explicit_cli_values_override_config_defaults():
    selections = get_user_selections(
        base_config=_base_config(),
        ticker="NVDA",
        analysis_date="2024-05-10",
        output_language="Spanish",
        analysts="market",
        research_depth=2,
        llm_provider="litellm",
        backend_url="http://localhost:4001/v1",
        quick_model="pentagi-json",
        deep_model="pentagi-coder",
        short_horizon="1-5 trading days",
        mid_horizon="2-6 weeks",
        primary_horizon="mid_term",
    )

    assert selections["output_language"] == "Spanish"
    assert [analyst.value for analyst in selections["analysts"]] == ["market"]
    assert selections["research_depth"] == 2
    assert selections["backend_url"] == "http://localhost:4001/v1"
    assert selections["shallow_thinker"] == "pentagi-json"
    assert selections["deep_thinker"] == "pentagi-coder"
    assert selections["short_term_horizon"] == "1-5 trading days"
    assert selections["mid_term_horizon"] == "2-6 weeks"
    assert selections["primary_recommendation_horizon"] == "mid_term"
