"""Tests for the shared rating heuristic and the SignalProcessor adapter.

The Portfolio Manager produces a typed PortfolioDecision via structured
output and renders it to markdown that always contains a ``**Rating**: X``
header.  The deterministic heuristic in ``tradingagents.agents.utils.rating``
is therefore sufficient to extract the rating downstream — no second LLM
call is needed — and SignalProcessor is now a thin adapter that delegates
to it.
"""

import pytest

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    render_pm_decision,
)
from tradingagents.agents.utils.rating import RATINGS_5_TIER, parse_rating
from tradingagents.graph.signal_processing import SignalProcessor


# ---------------------------------------------------------------------------
# Heuristic parser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseRating:
    def test_explicit_label_buy(self):
        assert parse_rating("Rating: Buy\nReasoning here.") == "Buy"

    def test_explicit_label_overweight(self):
        assert parse_rating("Rating: Overweight\nDetails.") == "Overweight"

    def test_explicit_label_with_markdown_bold_value(self):
        # Regression: Rating: **Sell** — markdown around the value.
        assert parse_rating("Rating: **Sell**\nExit immediately.") == "Sell"

    def test_explicit_label_with_markdown_bold_label(self):
        assert parse_rating("**Rating**: Underweight\nTrim exposure.") == "Underweight"

    def test_rendered_pm_markdown_shape(self):
        # The exact shape produced by render_pm_decision must always parse.
        text = (
            "**Rating**: Buy\n\n"
            "**Primary Horizon**: Short-Term\n\n"
            "## Short-Term Recommendation\n"
            "**Rating**: Buy\n"
            "**Time Horizon**: 2-10 trading days\n"
            "**Thesis**: AI capex cycle intact.\n"
            "**Action Plan**: Enter at $189-192, 6% portfolio cap.\n\n"
            "## Mid-Term Recommendation\n"
            "**Rating**: Overweight\n"
            "**Time Horizon**: 1-3 months\n"
            "**Thesis**: Institutional flows constructive.\n"
            "**Action Plan**: Build gradually."
        )
        assert parse_rating(text) == "Buy"

    def test_explicit_label_wins_over_prose_with_markdown(self):
        text = (
            "The buy thesis is weakened by guidance.\n"
            "Rating: **Sell**\n"
            "Exit before earnings."
        )
        assert parse_rating(text) == "Sell"

    def test_no_rating_returns_default(self):
        assert parse_rating("No clear directional signal at this time.") == "Hold"

    def test_no_rating_custom_default(self):
        assert parse_rating("Plain prose.", default="Underweight") == "Underweight"

    def test_all_five_tiers_recognised(self):
        for r in RATINGS_5_TIER:
            assert parse_rating(f"Rating: {r}") == r


# ---------------------------------------------------------------------------
# SignalProcessor: thin adapter over the heuristic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSignalProcessor:
    def test_returns_rating_from_pm_markdown(self):
        sp = SignalProcessor()
        md = (
            "**Rating**: Overweight\n"
            "**Primary Horizon**: Short-Term\n\n"
            "## Short-Term Recommendation\n"
            "**Rating**: Overweight\n"
            "**Time Horizon**: 2-10 trading days"
        )
        assert sp.process_signal(md) == "Overweight"

    def test_short_term_rating_is_default_canonical_signal(self):
        decision = PortfolioDecision(
            short_term_rating=PortfolioRating.HOLD,
            short_term_thesis="Short-term setup is stretched.",
            short_term_action_plan="Wait for a better entry.",
            short_term_time_horizon="2-10 trading days",
            mid_term_rating=PortfolioRating.BUY,
            mid_term_thesis="Mid-term fundamentals are constructive.",
            mid_term_action_plan="Accumulate on pullbacks.",
            mid_term_time_horizon="1-3 months",
        )
        sp = SignalProcessor()
        assert sp.process_signal(render_pm_decision(decision)) == "Hold"

    def test_makes_no_llm_calls(self):
        """SignalProcessor must not invoke the LLM it was constructed with —
        the rating is parseable from the rendered PM markdown directly."""
        from unittest.mock import MagicMock

        llm = MagicMock()
        sp = SignalProcessor(llm)
        sp.process_signal("Rating: Buy\nDetails.")
        llm.invoke.assert_not_called()
        llm.with_structured_output.assert_not_called()

    def test_default_when_no_rating_present(self):
        sp = SignalProcessor()
        assert sp.process_signal("Plain prose without a recommendation.") == "Hold"
