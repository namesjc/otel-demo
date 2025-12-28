# Import the logging module.
import logging

from config import Config
from flask import Flask

# Import tracing components
# Import metrics components
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider

# Import the OTLPLogExporter class from the OpenTelemetry gRPC log exporter module.
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Import Flask instrumentation
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

# Import the LoggerProvider and LoggingHandler classes from the OpenTelemetry SDK logs module.
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler

# Import the BatchLogRecordProcessor class from the OpenTelemetry SDK logs export module.
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# Import the Resource class from the OpenTelemetry SDK resources module.
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.engine import Engine


class CustomOtelFW:
    """CustomOtelFW sets up OpenTelemetry logging, tracing, and metrics with a specified service name and instance ID."""

    def __init__(self, service_name: str, instance_id: str) -> None:
        """
        Initialize the CustomOtelFW with a service name and instance ID.

        :param service_name: Name of the service for observability purposes.
        :param instance_id: Unique instance ID of the service.
        """
        self.service_name = service_name
        self.instance_id = instance_id

        # Create a Resource object that includes service name and instance ID
        self.resource = Resource.create(
            {
                "service.name": service_name,
                "service.instance.id": instance_id,
            },
        )

        # Initialize providers
        self.logger_provider = None
        self.tracer_provider = None
        self.meter_provider = None
        self.tracer = None
        self.meter = None

    def setup_logging(self) -> LoggingHandler:
        """
        Set up the logging configuration.

        :return: LoggingHandler instance configured with the logger provider.
        """
        # Create an instance of LoggerProvider with the Resource
        self.logger_provider = LoggerProvider(resource=self.resource)

        # Set the created LoggerProvider as the global logger provider.
        set_logger_provider(self.logger_provider)

        # Create an instance of OTLPLogExporter with insecure connection.
        exporter = OTLPLogExporter(
            endpoint=Config.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True,
        )

        # Add a BatchLogRecordProcessor to the logger provider with the exporter.
        self.logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

        # Create a LoggingHandler with the specified logger provider and log level set to NOTSET.
        handler = LoggingHandler(
            level=logging.DEBUG,
            logger_provider=self.logger_provider,
        )

        return handler

    def setup_tracing(self) -> trace.Tracer:
        """
        Set up distributed tracing configuration.

        :return: Tracer instance configured with the tracer provider.
        """
        # Create TracerProvider with the Resource
        self.tracer_provider = TracerProvider(resource=self.resource)

        # Create OTLP span exporter
        span_exporter = OTLPSpanExporter(
            endpoint=Config.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True,
        )

        # Add BatchSpanProcessor to the tracer provider
        self.tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))

        # Set the global tracer provider
        trace.set_tracer_provider(self.tracer_provider)

        # Get a tracer for this service
        self.tracer = trace.get_tracer(self.service_name)

        return self.tracer

    def setup_metrics(self) -> metrics.Meter:
        """
        Set up metrics configuration.

        :return: Meter instance configured with the meter provider.
        """
        # Create OTLP metric exporter
        metric_exporter = OTLPMetricExporter(
            endpoint=Config.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True,
        )

        # Create a metric reader with periodic exporting (every 30 seconds)
        metric_reader = PeriodicExportingMetricReader(
            exporter=metric_exporter,
            export_interval_millis=30000,  # Export every 30 seconds
        )

        # Create MeterProvider with the Resource and metric reader
        self.meter_provider = MeterProvider(
            resource=self.resource,
            metric_readers=[metric_reader],
        )

        # Set the global meter provider
        metrics.set_meter_provider(self.meter_provider)

        # Get a meter for this service
        self.meter = metrics.get_meter(self.service_name)

        return self.meter

    def instrument_flask_app(self, app: Flask) -> None:
        """
        Automatically instrument a Flask application with OpenTelemetry.

        :param app: Flask application instance to instrument.
        """
        FlaskInstrumentor().instrument_app(app)

    def instrument_requests(self) -> None:
        """Automatically instrument the requests library for HTTP client tracing."""
        RequestsInstrumentor().instrument()

    def instrument_sqlalchemy(self, engine: Engine) -> None:
        """
        Automatically instrument SQLAlchemy for database tracing.

        :param engine: SQLAlchemy engine instance to instrument.
        """
        SQLAlchemyInstrumentor().instrument(engine=engine)
