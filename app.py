import logging

from flask import Flask
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

# --- 0. Common OpenTelemetry Resource ---
resource = Resource.create(attributes={"service.name": "python-example"})

app = Flask(__name__)

# --- 1. Prometheus native SDK config (Pull mode) ---
prom_counter = Counter("native_prom_requests_total", "Total requests via Native SDK")

# --- 2. OpenTelemetry SDK config (Push mode) ---

# --- Tracing ---
trace_provider = TracerProvider(resource=resource)
trace_exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
trace.set_tracer_provider(trace_provider)
tracer = trace.get_tracer(__name__)

# --- Metrics ---
otlp_metric_exporter = OTLPMetricExporter(
    endpoint="http://localhost:4317", insecure=True
)
reader = PeriodicExportingMetricReader(otlp_metric_exporter)
meter_provider = MeterProvider(metric_readers=[reader], resource=resource)
metrics.set_meter_provider(meter_provider)
otel_meter = metrics.get_meter(__name__)
otel_counter = otel_meter.create_counter(
    "otel_requests_total", description="Total requests via OTel SDK"
)

# --- Logging ---
logger_provider = LoggerProvider(resource=resource)
log_exporter = OTLPLogExporter(endpoint="http://localhost:4317", insecure=True)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
set_logger_provider(logger_provider)
# Attach OTel handler to root logger
handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
logging.getLogger().addHandler(handler)
# Get a logger for the current module
log = logging.getLogger(__name__)


# --- 3. Instrument Flask app ---
FlaskInstrumentor().instrument_app(app)


@app.route("/buy")
def buy():
    # 同时记录两个指标
    prom_counter.inc()  # Prometheus: 简单增加
    otel_counter.add(1, {"item": "book"})  # OTel: 带属性增加

    # Add a log message
    log.info("Purchase request received for item: book")

    # Add event to the current span
    current_span = trace.get_current_span()
    current_span.add_event("Processing purchase")
    current_span.set_attribute("item.name", "book")

    return "Purchased!"


# Prometheus 需要一个显式的接口供抓取
@app.route("/metrics")
def metrics_route():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(port=5000)
