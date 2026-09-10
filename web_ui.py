import streamlit as st
import datetime
import os
import glob
import re
import time
from pathlib import Path
from collections import deque

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

from tradingagents.config_loader import load_config
from tradingagents.agents.utils.rating import parse_rating, RATINGS_5_TIER
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

# ── Page Config ──
st.set_page_config(
    page_title="TradingAgents",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ──
FIXED_AGENTS = {
    "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
    "Trading Team": ["Trader"],
    "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
    "Portfolio Management": ["Portfolio Manager"],
}

ANALYST_MAPPING = {
    "market": "Market Analyst",
    "social": "Social Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}

ANALYST_ORDER = ["market", "social", "news", "fundamentals"]

REPORT_SECTION_TITLES = {
    "market_report": "Market Analysis",
    "sentiment_report": "Social Sentiment",
    "news_report": "News Analysis",
    "fundamentals_report": "Fundamentals Analysis",
    "investment_plan": "Research Team Decision",
    "trader_investment_plan": "Trading Team Plan",
    "final_trade_decision": "Portfolio Management Decision",
}

STATUS_EMOJI = {
    "pending": "⏳",
    "in_progress": "🔄",
    "completed": "✅",
    "error": "❌",
}


# ── Helper Functions ──

def init_session_state():
    """Initialize all session state keys for streaming analysis."""
    defaults = {
        "agent_status": {},
        "report_sections": {},
        "messages": [],
        "tool_calls": [],
        "current_report": None,
        "processed_ids": set(),
        "llm_calls": 0,
        "tool_call_count": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "start_time": 0,
        "analysis_running": False,
        "analysis_done": False,
        "final_decision": "",
        "selected_analyst_keys": [],
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def reset_analysis_state(selected_keys):
    """Reset session state for a new analysis run."""
    keys = ["market", "social", "news", "fundamentals"]
    selected = [k for k in keys if k in selected_keys]

    st.session_state["agent_status"] = {}
    for k in selected:
        st.session_state["agent_status"][ANALYST_MAPPING[k]] = "pending"
    for agents in FIXED_AGENTS.values():
        for agent in agents:
            st.session_state["agent_status"][agent] = "pending"

    st.session_state["report_sections"] = {}
    st.session_state["messages"] = []
    st.session_state["tool_calls"] = []
    st.session_state["current_report"] = None
    st.session_state["processed_ids"] = set()
    st.session_state["llm_calls"] = 0
    st.session_state["tool_call_count"] = 0
    st.session_state["tokens_in"] = 0
    st.session_state["tokens_out"] = 0
    st.session_state["start_time"] = time.time()
    st.session_state["analysis_running"] = True
    st.session_state["analysis_done"] = False
    st.session_state["final_decision"] = ""
    st.session_state["selected_analyst_keys"] = selected


def get_completed_reports_count():
    """Count finalized report sections."""
    count = 0
    for section, content in st.session_state["report_sections"].items():
        if content is None:
            continue
        if section == "market_report" and st.session_state["agent_status"].get("Market Analyst") == "completed":
            count += 1
        elif section == "sentiment_report" and st.session_state["agent_status"].get("Social Analyst") == "completed":
            count += 1
        elif section == "news_report" and st.session_state["agent_status"].get("News Analyst") == "completed":
            count += 1
        elif section == "fundamentals_report" and st.session_state["agent_status"].get("Fundamentals Analyst") == "completed":
            count += 1
        elif section == "investment_plan" and st.session_state["agent_status"].get("Research Manager") == "completed":
            count += 1
        elif section == "trader_investment_plan" and st.session_state["agent_status"].get("Trader") == "completed":
            count += 1
        elif section == "final_trade_decision" and st.session_state["agent_status"].get("Portfolio Manager") == "completed":
            count += 1
    return count


def format_tokens(n):
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# ── Report History Parsing ──

def scan_reports_dir(reports_dir="./reports"):
    """Scan ./reports/ for run directories (TICKER_YYYYMMDD_HHMMSS format)."""
    entries = []
    path = Path(reports_dir)
    if not path.exists():
        return entries

    for entry in sorted(path.iterdir(), key=lambda e: e.name, reverse=True):
        if not entry.is_dir():
            continue
        match = re.match(r"^([A-Za-z0-9.]+)_(\d{4}\d{2}\d{2})_(\d{2}\d{2}\d{2})$", entry.name)
        if not match:
            continue
        ticker = match.group(1)
        date_str = match.group(2)
        time_str = match.group(3)
        display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        display_time = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"

        decision_path = entry / "5_portfolio" / "decision.md"
        decision = ""
        if decision_path.exists():
            try:
                decision = parse_rating(decision_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        complete_path = entry / "complete_report.md"
        entries.append({
            "ticker": ticker,
            "date": display_date,
            "time": display_time,
            "decision": decision,
            "run_dir": str(entry),
            "complete_path": str(complete_path) if complete_path.exists() else None,
            "source": "reports",
        })

    return entries


def scan_logs_dir(log_dir):
    """Scan a flat-file markdown log directory for past reports."""
    entries = []
    if not os.path.exists(log_dir):
        return entries

    md_files = sorted(glob.glob(os.path.join(log_dir, "*.md")), key=os.path.getmtime, reverse=True)
    for filepath in md_files[:20]:
        basename = os.path.basename(filepath)
        parts = basename.split("_")
        ticker = parts[0] if parts else ""
        date_disp = parts[1] if len(parts) > 1 else ""

        decision = ""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                decision = parse_rating(f.read())
        except Exception:
            pass

        entries.append({
            "ticker": ticker,
            "date": date_disp,
            "time": "",
            "decision": decision,
            "filepath": filepath,
            "complete_path": filepath,
            "source": "logs",
        })

    return entries


def extract_tldr(report_text: str):
    """Extract TLDR summary from a markdown report.

    Returns dict with: rating, action, entry, stop, target, position, summary
    """
    result = {"rating": "", "action": "", "entry": "", "stop": "", "target": "", "position": "", "summary": ""}

    result["rating"] = parse_rating(report_text)

    # Extract action
    m = re.search(r"\*\*Action\*\*[:\s]*(\w+)", report_text, re.IGNORECASE)
    if not m:
        m = re.search(r"FINAL TRANSACTION PROPOSAL:\s*\*?\*?(BUY|SELL|HOLD|OVERWEIGHT|UNDERWEIGHT)\*?\*?", report_text, re.IGNORECASE)
    if m:
        result["action"] = m.group(1).strip("*").upper()

    # Extract trade parameters
    for field, patterns in {
        "entry": [r"\*\*Entry[^:]*\*\*[:\s]*([^\n]+)", r"\*\*Entry trigger\*\*[:\s]*([^\n]+)"],
        "stop": [r"\*\*Stop[^:]*\*\*[:\s]*([^\n]+)", r"\*\*Stop-loss\*\*[:\s]*([^\n]+)"],
        "target": [r"\*\*Target\*\*[:\s]*([^\n]+)"],
        "position": [r"\*\*Position\s*size\*\*[:\s]*([^\n]+)", r"\*\*Position sizing\*\*[:\s]*([^\n]+)"],
    }.items():
        for pat in patterns:
            m = re.search(pat, report_text, re.IGNORECASE)
            if m:
                result[field] = m.group(1).strip()
                break

    # Extract first substantive paragraph as summary
    in_portfolio = False
    for line in report_text.splitlines():
        stripped = line.strip()
        if re.match(r"^#+\s*(Portfolio|Rating|Decision)", stripped, re.IGNORECASE):
            in_portfolio = True
            continue
        if in_portfolio and stripped and not stripped.startswith("#") and not stripped.startswith("|") and not stripped.startswith("*"):
            if len(stripped) > 60 and not stripped.startswith("FINAL"):
                result["summary"] = stripped.strip("* ")[:500]
                break

    if not result["summary"]:
        for line in report_text.splitlines():
            stripped = line.strip()
            if len(stripped) > 80 and not stripped.startswith("#") and not stripped.startswith("|") and not stripped.startswith(">"):
                result["summary"] = stripped.strip("* ")[:500]
                break

    return result


# ── Render functions ──

def _render_status_panel(placeholder):
    with placeholder.container():
        st.subheader("🤖 Agent Status")
        teams_data = {
            "Analyst Team": [ANALYST_MAPPING[k] for k in ANALYST_ORDER if k in st.session_state.get("selected_analyst_keys", [])],
            **{team: agents for team, agents in FIXED_AGENTS.items()},
        }

        rows = []
        for team, agents in teams_data.items():
            active = [a for a in agents if a in st.session_state.get("agent_status", {})]
            if not active:
                continue
            for i, agent in enumerate(active):
                status = st.session_state["agent_status"].get(agent, "pending")
                rows.append({
                    "Team": team if i == 0 else "",
                    "Agent": agent,
                    "Status": f"{STATUS_EMOJI.get(status, '⏳')} {status}",
                })

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=min(38 + len(rows) * 35, 400))
        else:
            st.info("No agents selected")


def _render_live_report(placeholder):
    with placeholder.container():
        st.subheader("📋 Live Report")
        if st.session_state.get("current_report"):
            st.markdown(st.session_state["current_report"])
        else:
            st.info("Waiting for analysis to produce results...")


def _render_message_log(placeholder):
    with placeholder.container():
        st.subheader("📨 Messages & Tools")
        all_items = []
        for ts, name in st.session_state.get("tool_calls", [])[-15:]:
            all_items.append((ts, "🛠 Tool", name))
        for ts, mtype, content in st.session_state.get("messages", [])[-15:]:
            all_items.append((ts, f"💬 {mtype}", content))

        all_items.sort(key=lambda x: x[0])
        if all_items:
            lines = []
            for ts, tag, text in all_items:
                lines.append(f"`{ts}` **{tag}** {text}")
            st.markdown("\n\n".join(lines[-12:]))
        else:
            st.caption("No messages yet")


def _render_footer(placeholder):
    with placeholder.container():
        agents_completed = sum(1 for s in st.session_state.get("agent_status", {}).values() if s == "completed")
        agents_total = len(st.session_state.get("agent_status", {}))
        reports_done = get_completed_reports_count()
        reports_total = len(st.session_state.get("report_sections", {}))

        elapsed = time.time() - st.session_state.get("start_time", time.time())
        elapsed_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"

        cols = st.columns([1, 1, 1, 1, 1, 1])
        with cols[0]:
            st.metric("Agents", f"{agents_completed}/{agents_total}")
        with cols[1]:
            st.metric("Reports", f"{reports_done}/{reports_total}")
        with cols[2]:
            st.metric("LLM Calls", st.session_state.get("llm_calls", 0))
        with cols[3]:
            st.metric("Tools", st.session_state.get("tool_call_count", 0))
        with cols[4]:
            ti = format_tokens(st.session_state.get("tokens_in", 0))
            to = format_tokens(st.session_state.get("tokens_out", 0))
            st.metric("Tokens", f"↑{ti} ↓{to}")
        with cols[5]:
            st.metric("Elapsed", elapsed_str)


def _render_tldr(tldr: dict):
    """Render a compact TLDR summary box at the top of a report view."""
    st.header("⚡ TL;DR")

    rating_color = {
        "Buy": "#16a34a", "Overweight": "#65a30d",
        "Hold": "#d97706", "Underweight": "#ea580c", "Sell": "#dc2626",
    }.get(tldr.get("rating", ""), "#6b7280")

    action_color = {
        "BUY": "#16a34a", "OVERWEIGHT": "#65a30d",
        "HOLD": "#d97706", "UNDERWEIGHT": "#ea580c", "SELL": "#dc2626",
    }.get(tldr.get("action", ""), "#6b7280")

    cols = st.columns([1, 1, 1])
    with cols[0]:
        if tldr.get("rating"):
            st.markdown(
                f"**Rating:** <span style='color:{rating_color};font-size:1.3em'>{tldr['rating']}</span>",
                unsafe_allow_html=True,
            )
    with cols[1]:
        if tldr.get("action"):
            st.markdown(
                f"**Action:** <span style='color:{action_color};font-size:1.3em'>{tldr['action']}</span>",
                unsafe_allow_html=True,
            )
    with cols[2]:
        elapsed = st.session_state.get("total_elapsed")
        if elapsed:
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            st.metric("⏱ Time", f"{mins}m {secs}s")

    trade_params = []
    if tldr.get("entry"):
        trade_params.append(f"Entry: {tldr['entry']}")
    if tldr.get("stop"):
        trade_params.append(f"Stop: {tldr['stop']}")
    if tldr.get("target"):
        trade_params.append(f"Target: {tldr['target']}")
    if tldr.get("position"):
        trade_params.append(f"Position: {tldr['position']}")
    if trade_params:
        with cols[2]:
            st.markdown("  \n".join(trade_params))

    if tldr.get("summary"):
        st.markdown(f"> {tldr['summary']}")


def _build_final_markdown():
    sections = []
    rs = st.session_state.get("report_sections", {})

    analyst_parts = []
    for key in ["market_report", "sentiment_report", "news_report", "fundamentals_report"]:
        if rs.get(key):
            title = REPORT_SECTION_TITLES.get(key, key)
            analyst_parts.append(f"### {title}\n{rs[key]}")
    if analyst_parts:
        sections.append("## Analyst Team Reports\n\n" + "\n\n".join(analyst_parts))

    if rs.get("investment_plan"):
        sections.append(f"## Research Team Decision\n\n{rs['investment_plan']}")

    if rs.get("trader_investment_plan"):
        sections.append(f"## Trading Team Plan\n\n{rs['trader_investment_plan']}")

    if rs.get("final_trade_decision"):
        sections.append(f"## Portfolio Management Decision\n\n{rs['final_trade_decision']}")

    return "\n\n".join(sections) if sections else ""


def trigger_analysis():
    st.session_state["_trigger_run"] = True

with st.sidebar:
    _cfg = load_config()

    # ── Ticker + Run ──
    if "ticker_input" not in st.session_state:
        st.session_state["ticker_input"] = "SPY"
    st.text_input(
        "Ticker Symbol",
        key="ticker_input",
        on_change=trigger_analysis,
    )
    clicked = st.button("▶️ Run Analysis", type="primary", use_container_width=True)

    # ── Analysis Options ──
    st.date_input("Analysis Date", value=datetime.date.today(), key="analysis_date_input")

    with st.expander("⚙️ Model Configuration", expanded=False):
        providers = list(MODEL_OPTIONS.keys()) + ["openrouter", "azure"]
        default_provider = _cfg.get("llm_provider", "openai")
        if default_provider not in providers:
            default_provider = providers[0]
        provider_idx = providers.index(st.session_state.get("_provider", default_provider)) if st.session_state.get("_provider", default_provider) in providers else 0
        llm_provider = st.selectbox("LLM Provider", providers, index=provider_idx, key="_provider")

        st.text_input("Backend URL", value=_cfg.get("backend_url") or "",
                      placeholder="http://localhost:4000/v1", key="backend_url_input")

        # Model dropdowns: config default + catalog + custom
        provider_models = MODEL_OPTIONS.get(llm_provider, {})
        cfg_quick = _cfg.get("quick_think_llm", "")
        cfg_deep = _cfg.get("deep_think_llm", "")

        def _model_selectbox(label, catalog_list, cfg_default, session_key):
            labels, ids = [], []
            if cfg_default:
                labels.append(f"{cfg_default} (from config)")
                ids.append(cfg_default)
            for cat_label, cat_id in catalog_list:
                if cat_id == cfg_default:
                    continue
                labels.append(cat_label)
                ids.append(cat_id)
            labels.append("Other (custom)...")
            ids.append("__custom__")
            # Store ID mapping in session_state
            st.session_state[f"{session_key}_ids"] = ids
            st.session_state[f"{session_key}_labels"] = labels
            current = st.session_state.get(session_key, labels[0])
            idx = labels.index(current) if current in labels else 0
            chosen = st.selectbox(label, labels, index=idx, key=session_key)
            return ids[labels.index(chosen)]

        col_q, col_d = st.columns(2)
        with col_q:
            quick_model_id = _model_selectbox("Quick Model", provider_models.get("quick", []), cfg_quick, "quick_model_sel")
            if quick_model_id == "__custom__":
                quick_model_id = st.text_input("Custom Quick Model", value=cfg_quick, key="custom_quick_input")
            st.session_state["quick_model_resolved"] = quick_model_id
        with col_d:
            deep_model_id = _model_selectbox("Deep Model", provider_models.get("deep", []), cfg_deep, "deep_model_sel")
            if deep_model_id == "__custom__":
                deep_model_id = st.text_input("Custom Deep Model", value=cfg_deep, key="custom_deep_input")
            st.session_state["deep_model_resolved"] = deep_model_id

        st.number_input("Research Depth (debate rounds)", min_value=1, max_value=5,
                        value=_cfg.get("max_debate_rounds", 1), key="research_depth_input")

        default_analysts = _cfg.get("selected_analysts") or ["market", "social", "news", "fundamentals"]
        if isinstance(default_analysts, str):
            default_analysts = [a.strip() for a in default_analysts.split(",")]
        st.multiselect(
            "Analysts",
            options=["market", "social", "news", "fundamentals"],
            default=[a for a in default_analysts if a in ["market", "social", "news", "fundamentals"]],
            format_func=lambda x: ANALYST_MAPPING.get(x, x),
            key="analysts_select",
        )

    st.divider()

    st.header("📁 Report History")

    tab_reports, tab_logs = st.tabs(["📂 Reports/", "📄 Logs"])

    with tab_reports:
        report_entries = scan_reports_dir("./reports")
        if not report_entries:
            st.info("No reports found in ./reports/")
        else:
            for entry in report_entries[:20]:
                cols = st.columns([1.5, 1, 1, 1])
                with cols[0]:
                    st.write(f"**{entry['ticker']}**")
                    st.caption(f"{entry['date']} {entry['time']}")
                with cols[1]:
                    if entry["decision"]:
                        color = "green" if entry["decision"] in ("BUY", "OVERWEIGHT") else \
                                "red" if entry["decision"] in ("SELL", "UNDERWEIGHT") else "orange"
                        st.markdown(f":{color}[{entry['decision']}]")
                with cols[2]:
                    if entry["complete_path"] and os.path.exists(entry["complete_path"]):
                        with open(entry["complete_path"], "r", encoding="utf-8") as f:
                            st.download_button(
                                label="⬇ Download",
                                data=f.read(),
                                file_name=f"{entry['ticker']}_{entry['date']}.md",
                                mime="text/markdown",
                                key=f"dl_reports_{entry['run_dir']}",
                                use_container_width=True,
                            )
                with cols[3]:
                    if entry["complete_path"]:
                        if st.button("👁 View", key=f"view_reports_{entry['run_dir']}", use_container_width=True):
                            st.session_state["report_to_display"] = entry["complete_path"]
                            st.session_state.pop("report_content", None)
    st.rerun()

# ── Static Display (when not running) ──

if not st.session_state.get("analysis_running"):
    if st.session_state.get("report_to_display"):
        report_path = st.session_state["report_to_display"]
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
            tldr = extract_tldr(report_text)
            _render_tldr(tldr)
            st.divider()
            st.header("📄 Full Report")
            st.markdown(report_text)
            if st.button("✕ Close Report", use_container_width=False):
                st.session_state.pop("report_to_display", None)
                st.rerun()
        else:
            st.warning(f"Report file not found: {report_path}")

    elif st.session_state.get("analysis_done") and not st.session_state.get("_shown_result", False):
        st.session_state["_shown_result"] = True
        if st.session_state.get("report_sections"):
            full = _build_final_markdown()
            if full:
                tldr = extract_tldr(full)
                _render_tldr(tldr)
                st.divider()
                st.header("📄 Full Report")
                st.markdown(full)
            if st.button("🔄 Run Another Analysis", use_container_width=False):
                st.session_state["_shown_result"] = False
                st.session_state.pop("report_to_display", None)
                st.rerun()

    elif not st.session_state.get("report_to_display"):
        st.info("👈 Enter a ticker and click **Run Analysis** to start, or select a past report from the sidebar.")

    with tab_logs:
        log_dir = _cfg.get("results_dir", os.path.join(os.getcwd(), "reports"))
        log_entries = scan_logs_dir(log_dir)
        if not log_entries:
            st.info("No reports found in logs directory")
        else:
            for entry in log_entries[:20]:
                cols = st.columns([1.5, 1, 1, 1])
                with cols[0]:
                    st.write(f"**{entry['ticker']}**")
                    st.caption(entry["date"])
                with cols[1]:
                    if entry["decision"]:
                        st.caption(entry["decision"][:20])
                with cols[2]:
                    with open(entry["filepath"], "rb") as f:
                        st.download_button(
                            label="⬇ Download",
                            data=f.read(),
                            file_name=os.path.basename(entry["filepath"]),
                            mime="text/markdown",
                            key=f"dl_logs_{entry['filepath']}",
                            use_container_width=True,
                        )
                with cols[3]:
                    if st.button("👁 View", key=f"view_logs_{entry['filepath']}", use_container_width=True):
                        st.session_state["report_to_display"] = entry["filepath"]
                        st.session_state.pop("report_content", None)
                        st.rerun()


# ── Main Content Area ──

st.title("📈 TradingAgents Web UI")
init_session_state()

# ── Run Analysis (Streaming) ──

if clicked or st.session_state.pop("_trigger_run", False):
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from cli.stats_handler import StatsCallbackHandler

    ticker = st.session_state.get("ticker_input", "SPY").upper().strip()
    analysis_date = st.session_state.get("analysis_date_input", datetime.date.today())
    llm_provider = st.session_state.get("_provider", "openai")
    backend_url = st.session_state.get("backend_url_input") or None
    quick_model_id = st.session_state.get("quick_model_resolved") or st.session_state.get("custom_quick_input") or ""
    deep_model_id = st.session_state.get("deep_model_resolved") or st.session_state.get("custom_deep_input") or ""
    research_depth = st.session_state.get("research_depth_input", 1)
    selected_analysts = st.session_state.get("analysts_select", ["market", "social", "news", "fundamentals"])

    config = load_config()
    config["analysis_date"] = analysis_date.isoformat() if hasattr(analysis_date, "isoformat") else str(analysis_date)
    config["llm_provider"] = llm_provider
    config["quick_think_llm"] = quick_model_id or config.get("quick_think_llm", "")
    config["deep_think_llm"] = deep_model_id or config.get("deep_think_llm", "")
    config["backend_url"] = backend_url
    config["max_debate_rounds"] = int(research_depth)
    config["max_risk_discuss_rounds"] = int(research_depth)
    selected_keys = selected_analysts if selected_analysts else ["market", "social", "news", "fundamentals"]

    reset_analysis_state(selected_keys)

    stats_handler = StatsCallbackHandler()
    graph = TradingAgentsGraph(
        selected_keys,
        config=config,
        debug=True,
        callbacks=[stats_handler],
    )

    # Create initial state
    init_state = graph.propagator.create_initial_state(ticker, analysis_date.isoformat())
    args = graph.propagator.get_graph_args(callbacks=[stats_handler])

    # Pre-create placeholder containers
    status_ph = st.empty()
    live_report_ph = st.empty()
    msg_ph = st.empty()
    footer_ph = st.empty()

    # Stream loop
    trace = []
    try:
        for chunk in graph.graph.stream(init_state, **args):
            # ── Process messages ──
            for message in chunk.get("messages", []):
                msg_id = getattr(message, "id", None)
                if msg_id is not None:
                    if msg_id in st.session_state["processed_ids"]:
                        continue
                    st.session_state["processed_ids"].add(msg_id)

                content = getattr(message, "content", "")
                if isinstance(content, list):
                    content = " ".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
                if content and str(content).strip():
                    msg_type = "Agent"
                    st.session_state["messages"].append(
                        (datetime.datetime.now().strftime("%H:%M:%S"), msg_type, str(content)[:200])
                    )

                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tc in message.tool_calls:
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                        st.session_state["tool_calls"].append(
                            (datetime.datetime.now().strftime("%H:%M:%S"), name)
                        )

            # ── Update analyst statuses ──
            found_active = False
            report_key_map = {
                "market": "market_report",
                "social": "sentiment_report",
                "news": "news_report",
                "fundamentals": "fundamentals_report",
            }
            for ak in ANALYST_ORDER:
                if ak not in selected_keys:
                    continue
                agent = ANALYST_MAPPING[ak]
                report_key = report_key_map[ak]

                has = bool(chunk.get(report_key))
                if has:
                    st.session_state["agent_status"][agent] = "completed"
                    st.session_state["report_sections"][report_key] = chunk[report_key]
                    st.session_state["current_report"] = (
                        f"### {REPORT_SECTION_TITLES[report_key]}\n{chunk[report_key]}"
                    )
                elif not found_active:
                    st.session_state["agent_status"][agent] = "in_progress"
                    found_active = True

            if not found_active and selected_keys:
                if st.session_state["agent_status"].get("Bull Researcher") == "pending":
                    st.session_state["agent_status"]["Bull Researcher"] = "in_progress"

            # ── Research team ──
            debate = chunk.get("investment_debate_state", {})
            if debate.get("bull_history") or debate.get("bear_history"):
                st.session_state["agent_status"]["Bull Researcher"] = "in_progress"
            if debate.get("judge_decision"):
                for a in ["Bull Researcher", "Bear Researcher", "Research Manager"]:
                    st.session_state["agent_status"][a] = "completed"
                st.session_state["agent_status"]["Trader"] = "in_progress"
                st.session_state["report_sections"]["investment_plan"] = debate["judge_decision"]
                st.session_state["current_report"] = f"### Research Team Decision\n{debate['judge_decision']}"

            # ── Trader ──
            if chunk.get("trader_investment_plan"):
                st.session_state["agent_status"]["Trader"] = "completed"
                st.session_state["agent_status"]["Aggressive Analyst"] = "in_progress"
                st.session_state["report_sections"]["trader_investment_plan"] = chunk["trader_investment_plan"]
                st.session_state["current_report"] = f"### Trading Team Plan\n{chunk['trader_investment_plan']}"

            # ── Risk management ──
            risk = chunk.get("risk_debate_state", {})
            if risk.get("aggressive_history"):
                st.session_state["agent_status"]["Aggressive Analyst"] = "completed"
            if risk.get("conservative_history"):
                st.session_state["agent_status"]["Conservative Analyst"] = "completed"
            if risk.get("neutral_history"):
                st.session_state["agent_status"]["Neutral Analyst"] = "completed"
            if risk.get("judge_decision"):
                st.session_state["agent_status"]["Portfolio Manager"] = "completed"
                st.session_state["report_sections"]["final_trade_decision"] = risk["judge_decision"]
                st.session_state["current_report"] = f"### Portfolio Management Decision\n{risk['judge_decision']}"

            # ── Sync stats ──
            s = stats_handler.get_stats()
            st.session_state["llm_calls"] = s["llm_calls"]
            st.session_state["tool_call_count"] = s["tool_calls"]
            st.session_state["tokens_in"] = s["tokens_in"]
            st.session_state["tokens_out"] = s["tokens_out"]

            # ── Render panels ──
            _render_status_panel(status_ph)
            _render_live_report(live_report_ph)
            _render_message_log(msg_ph)
            _render_footer(footer_ph)

            trace.append(chunk)

        # ── Done ──
        if trace:
            final_state = trace[-1]
            st.session_state["final_decision"] = graph.process_signal(
                final_state.get("final_trade_decision", "")
            )
        for agent in st.session_state["agent_status"]:
            st.session_state["agent_status"][agent] = "completed"
        st.session_state["analysis_running"] = False
        st.session_state["analysis_done"] = True
        st.session_state["total_elapsed"] = time.time() - st.session_state.get("start_time", time.time())

        _render_status_panel(status_ph)
        _render_live_report(live_report_ph)
        _render_message_log(msg_ph)
        _render_footer(footer_ph)
        st.success(f"Analysis Complete! Decision: **{st.session_state['final_decision']}**")

        # Save report to logs
        log_dir = config.get("results_dir", os.path.join(os.getcwd(), "reports"))
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        full_report = graph._get_full_report(final_state)
        filename = f"{ticker}_{analysis_date.isoformat()}_{timestamp}.md"
        with open(os.path.join(log_dir, filename), "w", encoding="utf-8") as f:
            f.write(full_report)

    except Exception as e:
        st.error(f"Analysis failed: {e}")
        st.session_state["analysis_running"] = False

    # Clear placeholders and rerun to show final/static view
    status_ph.empty()
    live_report_ph.empty()
    msg_ph.empty()
    footer_ph.empty()
    st.rerun()
