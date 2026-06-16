"""
monitoring/metrics.py – Prometheus metric objects shared across the application.
Import and use these objects directly; do NOT create new ones with the same name.
"""
from prometheus_client import Counter, Gauge, Histogram, Info

# ── HTTP ──────────────────────────────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests received",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ── Orders ────────────────────────────────────────────────────────────────────
orders_submitted_total = Counter(
    "orders_submitted_total",
    "Total orders submitted by type",
    ["symbol", "order_type", "side"],
)

orders_filled_total = Counter(
    "orders_filled_total",
    "Total orders fully filled",
    ["symbol"],
)

orders_rejected_total = Counter(
    "orders_rejected_total",
    "Total orders rejected",
    ["symbol", "reason"],
)

orders_cancelled_total = Counter(
    "orders_cancelled_total",
    "Total orders cancelled",
    ["symbol"],
)

# ── Trades ────────────────────────────────────────────────────────────────────
trades_executed_total = Counter(
    "trades_executed_total",
    "Total trades executed",
    ["symbol"],
)

trade_volume_total = Counter(
    "trade_volume_total",
    "Total trade volume (shares * price) executed",
    ["symbol"],
)

# ── WebSocket ─────────────────────────────────────────────────────────────────
active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Number of currently active WebSocket connections",
    ["symbol"],
)

# ── Kafka ─────────────────────────────────────────────────────────────────────
kafka_messages_consumed_total = Counter(
    "kafka_messages_consumed_total",
    "Total Kafka messages consumed",
    ["topic"],
)

kafka_consumer_errors_total = Counter(
    "kafka_consumer_errors_total",
    "Total Kafka consumer errors",
    ["topic"],
)

# ── gRPC ─────────────────────────────────────────────────────────────────────
grpc_calls_total = Counter(
    "grpc_calls_total",
    "Total gRPC calls made to matching engine",
    ["method", "status"],
)

grpc_call_duration_seconds = Histogram(
    "grpc_call_duration_seconds",
    "gRPC call duration in seconds",
    ["method"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

# ── Engine latency (forwarded from C++ metrics) ───────────────────────────────
engine_p50_latency_ns = Gauge("engine_p50_latency_ns", "Matching engine p50 latency (ns)")
engine_p95_latency_ns = Gauge("engine_p95_latency_ns", "Matching engine p95 latency (ns)")
engine_p99_latency_ns = Gauge("engine_p99_latency_ns", "Matching engine p99 latency (ns)")
engine_p999_latency_ns = Gauge("engine_p999_latency_ns", "Matching engine p999 latency (ns)")
engine_orders_per_second = Gauge("engine_orders_per_second", "Orders processed per second")
engine_trades_per_second = Gauge("engine_trades_per_second", "Trades executed per second")

# ── Application info ──────────────────────────────────────────────────────────
app_info = Info("exchangex_backend", "ExchangeX backend application info")
app_info.info({"version": "1.0.0", "environment": "production"})
