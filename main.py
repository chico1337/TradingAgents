from dotenv import load_dotenv
import datetime

# Load environment variables from .env file
load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.config_loader import load_config

config = load_config()

ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate
_, decision = ta.propagate("NVDA", datetime.date.today().isoformat())
print(decision)

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
