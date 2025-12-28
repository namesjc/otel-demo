# bug_service.py

import logging
import random
import threading
import time

import requests
from config import Config
from flask import Flask, jsonify
from loggingfw import CustomOtelFW

# Initialize OpenTelemetry framework
otel_fw = CustomOtelFW(service_name="bug_service", instance_id="1")

# Setup logging
handler = otel_fw.setup_logging()
logging.getLogger().addHandler(handler)

# Setup tracing
tracer = otel_fw.setup_tracing()

# Setup metrics
meter = otel_fw.setup_metrics()

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY

# Instrument Flask app and requests library
otel_fw.instrument_flask_app(app)
otel_fw.instrument_requests()

# Create custom metrics
bugs_triggered_counter = meter.create_counter(
    name="bug_service.bugs.triggered",
    description="Total number of bugs triggered",
    unit="1",
)

bug_mode_gauge = meter.create_up_down_counter(
    name="bug_service.bug_mode.active",
    description="Whether bug mode is active (1) or not (0)",
    unit="1",
)

bug_attempts_counter = meter.create_counter(
    name="bug_service.bug_attempts.count",
    description="Total number of bug trigger attempts",
    unit="1",
)

SERVICES = [
    "http://user_service:5001",
    "http://plant_service:5002",
    "http://simulation_service:5003",
    "http://websocket_service:5004",
]

bug_mode = False


def bug_mode_worker() -> None:
    while True:
        if bug_mode:
            with tracer.start_as_current_span("bug_trigger_cycle") as span:
                service_url = random.choice(SERVICES)
                span.set_attribute("target.service", service_url)
                bug_attempts_counter.add(1)

                try:
                    with tracer.start_as_current_span(
                        "trigger_bug_request"
                    ) as req_span:
                        req_span.set_attribute("target.service", service_url)
                        response = requests.get(f"{service_url}/trigger_bug")
                        req_span.set_attribute("http.status_code", response.status_code)

                    if response.status_code == 200:
                        bugs_triggered_counter.add(1, {"service": service_url})
                        span.set_attribute("result", "success")
                        logging.info(f"Bug triggered in {service_url}")
                    else:
                        span.set_attribute("error", True)
                        logging.error(f"Failed to trigger bug in {service_url}")
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    logging.error(f"Error triggering bug in {service_url}: {str(e)}")
        time.sleep(10)  # Trigger a bug every 10 seconds


@app.route("/toggle_bug_mode", methods=["POST"])
def toggle_bug_mode():
    with tracer.start_as_current_span("toggle_bug_mode") as span:
        global bug_mode
        old_mode = bug_mode
        bug_mode = not bug_mode

        span.set_attribute("old_mode", old_mode)
        span.set_attribute("new_mode", bug_mode)

        # Update gauge metric
        if bug_mode:
            bug_mode_gauge.add(1)
        else:
            bug_mode_gauge.add(-1)

        logging.info(f"Bug mode toggled: {bug_mode}")
        return jsonify({"message": "Bug mode toggled", "bug_mode": bug_mode}), 200


@app.route("/bug_mode_status", methods=["GET"])
def bug_mode_status():
    with tracer.start_as_current_span("bug_mode_status") as span:
        span.set_attribute("bug_mode", bug_mode)
        return jsonify({"bug_mode": bug_mode}), 200


if __name__ == "__main__":
    threading.Thread(target=bug_mode_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=5010)
