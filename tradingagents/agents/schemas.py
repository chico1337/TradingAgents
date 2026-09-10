"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description="Optional sizing guidance, e.g. '5% of portfolio'.",
    )


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    short_term_rating: PortfolioRating = Field(
        description=(
            "The short-term position rating. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell, based on the configured short-term horizon."
        ),
    )
    short_term_thesis: str = Field(
        description=(
            "Short-term reasoning anchored in technical setup, recent news, "
            "near-term catalysts, and immediate risk conditions. Two to four sentences."
        ),
    )
    short_term_action_plan: str = Field(
        description=(
            "Concrete short-term action plan covering entry strategy, key levels, "
            "position sizing, and risk controls."
        ),
    )
    short_term_time_horizon: str = Field(
        description="Recommended holding period matching the configured short-term horizon.",
    )
    mid_term_rating: PortfolioRating = Field(
        description=(
            "The mid-term position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, based on the configured mid-term horizon."
        ),
    )
    mid_term_thesis: str = Field(
        description=(
            "Mid-term reasoning anchored in fundamentals, trend durability, catalysts, "
            "valuation, and broader risk conditions. Two to four sentences."
        ),
    )
    mid_term_action_plan: str = Field(
        description=(
            "Concrete mid-term action plan covering scaling, profit-taking or add levels, "
            "position sizing, and risk controls."
        ),
    )
    mid_term_time_horizon: str = Field(
        description="Recommended holding period matching the configured mid-term horizon.",
    )


def render_pm_decision(
    decision: PortfolioDecision,
    primary_horizon: str = "short_term",
) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown.
    The leading ``**Rating**`` field is preserved for downstream parsers and
    points to the configured primary horizon.
    """
    if primary_horizon == "mid_term":
        primary_rating = decision.mid_term_rating
        primary_label = "Mid-Term"
    else:
        primary_rating = decision.short_term_rating
        primary_label = "Short-Term"

    parts = [
        f"**Rating**: {primary_rating.value}",
        f"**Primary Horizon**: {primary_label}",
        "",
        "## Short-Term Recommendation",
        "**Setup Type**: Swing",
        f"**Rating**: {decision.short_term_rating.value}",
        f"**Time Horizon**: {decision.short_term_time_horizon}",
        f"**Thesis**: {decision.short_term_thesis}",
        f"**Action Plan**: {decision.short_term_action_plan}",
        "",
        "## Mid-Term Recommendation",
        "**Setup Type**: Position",
        f"**Rating**: {decision.mid_term_rating.value}",
        f"**Time Horizon**: {decision.mid_term_time_horizon}",
        f"**Thesis**: {decision.mid_term_thesis}",
        f"**Action Plan**: {decision.mid_term_action_plan}",
    ]
    return "\n".join(parts)
