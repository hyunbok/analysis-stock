from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    excluded_handlers=["/metrics", "/api/v1/health"],
    env_var_name="ENABLE_METRICS",
)

# --- Custom metrics (cointrader_ namespace) ---

# Exchange API
cointrader_exchange_request_duration = Histogram(
    "cointrader_exchange_request_duration_seconds",
    "Exchange API request duration",
    ["exchange", "method"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)
cointrader_exchange_request_errors = Counter(
    "cointrader_exchange_request_errors_total",
    "Exchange API errors",
    ["exchange", "error_type"],
)
cointrader_circuit_breaker_state = Gauge(
    "cointrader_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half-open, 2=open)",
    ["exchange"],
)

# Orders
cointrader_orders_placed = Counter(
    "cointrader_orders_placed_total",
    "Total orders placed",
    ["exchange", "side", "status"],
)

# AI Trading
cointrader_ai_trade_executions = Counter(
    "cointrader_ai_trade_executions_total",
    "AI trade execution count",
    ["action", "strategy", "result"],
)
cointrader_ai_regime_analysis_duration = Histogram(
    "cointrader_ai_regime_analysis_duration_seconds",
    "AI regime analysis duration",
)

# API (endpoint-level detail)
cointrader_api_request_duration = Histogram(
    "cointrader_api_request_duration_seconds",
    "API request latency",
    ["method", "endpoint", "status_code"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)

# WebSocket
cointrader_ws_active_connections = Gauge(
    "cointrader_ws_active_connections",
    "Active WebSocket connections",
)
cointrader_ws_subscriptions = Gauge(
    "cointrader_ws_subscriptions_total",
    "Total active WS subscriptions",
    ["channel"],
)
