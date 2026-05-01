from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def get_trading_horizon_config() -> dict[str, str]:
    """Return configured short/mid-term recommendation horizons."""
    from tradingagents.dataflows.config import get_config

    config = get_config()
    primary = config.get("primary_recommendation_horizon", "short_term")
    if primary not in {"short_term", "mid_term"}:
        primary = "short_term"
    return {
        "short_term_horizon": config.get("short_term_horizon", "2-10 trading days"),
        "mid_term_horizon": config.get("mid_term_horizon", "1-3 months"),
        "primary_recommendation_horizon": primary,
    }


def get_trading_horizon_instruction() -> str:
    """Return prompt text that keeps all decision agents horizon-aware."""
    horizons = get_trading_horizon_config()
    primary_label = (
        "short-term"
        if horizons["primary_recommendation_horizon"] == "short_term"
        else "mid-term"
    )
    return (
        "Evaluate recommendations separately for two horizons:\n"
        f"- Short-term: {horizons['short_term_horizon']}\n"
        f"- Mid-term: {horizons['mid_term_horizon']}\n"
        f"The canonical machine-readable signal is the {primary_label} recommendation. "
        "Allow the short-term and mid-term ratings to differ when technical setup, "
        "fundamentals, or risk profile diverge across horizons."
    )


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
