# websocket_service.py

import logging

import requests
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from loggingfw import CustomOtelFW

# Initialize OpenTelemetry framework
otelFW = CustomOtelFW(service_name="websocket_service", instance_id="1")

# Setup logging
handler = otelFW.setup_logging()
logging.getLogger().addHandler(handler)

# Setup tracing
tracer = otelFW.setup_tracing()

# Setup metrics
meter = otelFW.setup_metrics()

app = Flask(__name__)
app.config["SECRET_KEY"] = "plantsarecool1234"
socketio = SocketIO(app, cors_allowed_origins="*", engineio_logger=True)

# Instrument Flask app and requests library
otelFW.instrument_flask_app(app)
otelFW.instrument_requests()

# Create custom metrics
connections_gauge = meter.create_up_down_counter(
    name="websocket_service.connections.active",
    description="Number of active WebSocket connections",
    unit="1",
)

plants_added_counter = meter.create_counter(
    name="websocket_service.plants.added",
    description="Total number of plants added via WebSocket",
    unit="1",
)

error_counter = meter.create_counter(
    name="websocket_service.errors.count",
    description="Total number of errors",
    unit="1",
)

messages_counter = meter.create_counter(
    name="websocket_service.messages.count",
    description="Total number of WebSocket messages",
    unit="1",
)

PLANT_SERVICE_URL = "http://plant_service:5002"

active_users = {}
BUGS = False


@app.route("/trigger_bug", methods=["GET"])
def bug():
    with tracer.start_as_current_span("trigger_bug"):
        logging.error("Triggering bug...")
        global BUGS
        BUGS = True
        return "Bug triggered", 200


@socketio.on("connect")
def handle_connect():
    user_id = request.args.get("user_id")  # Get user_id from query parameters
    if user_id:
        with tracer.start_as_current_span("websocket_connect") as span:
            span.set_attribute("user.id", user_id)
            active_users[user_id] = {
                "error_mode": False  # You can set the error_mode based on your application logic
            }
            join_room(str(user_id))
            connections_gauge.add(1, {"user_id": str(user_id)})
            messages_counter.add(1, {"message_type": "connect"})
            span.set_attribute("result", "success")
            logging.info(
                f"User {user_id} connected and joined their room with error mode {active_users[user_id]['error_mode']}."
            )


@socketio.on("disconnect")
def on_disconnect():
    user_id = request.args.get("user_id")
    if user_id in active_users:
        with tracer.start_as_current_span("websocket_disconnect") as span:
            span.set_attribute("user.id", user_id)
            del active_users[user_id]
            leave_room(str(user_id))
            connections_gauge.add(-1, {"user_id": str(user_id)})
            messages_counter.add(1, {"message_type": "disconnect"})
            span.set_attribute("result", "success")
            logging.info(
                f"User {user_id} disconnected and was removed from active list."
            )


@socketio.on("add_plant")
def handle_add_plant(data):
    with tracer.start_as_current_span("add_plant") as span:
        messages_counter.add(1, {"message_type": "add_plant"})

        global BUGS
        if BUGS == True:
            error_counter.add(
                1, {"error_type": "bug_triggered", "operation": "add_plant"}
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", "bug_triggered")
            logging.error(
                "What a nasty bug! It flew into the websocket service and stopped the request to add plant."
            )
            BUGS = False
            return "Failed to add plant"

        user_id = request.args.get("user_id")
        if not user_id or user_id not in active_users:
            error_counter.add(
                1, {"error_type": "unauthorized", "operation": "add_plant"}
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", "unauthorized")
            emit("error", {"error": "Unauthorized or failed attempt to add plant"})
            return

        span.set_attribute("user.id", user_id)
        plant_name = data.get("plant_name")
        plant_type = data.get("plant_type")
        span.set_attribute("plant.name", plant_name)
        span.set_attribute("plant.type", plant_type)

        with tracer.start_as_current_span("plant_service_request"):
            response = requests.post(
                f"{PLANT_SERVICE_URL}/plants",
                json={
                    "plant_name": plant_name,
                    "plant_type": plant_type,
                    "user_id": user_id,
                },
            )

        if response.status_code == 201:
            plants_added_counter.add(1, {"user_id": str(user_id)})
            plant_data = response.json()
            span.set_attribute("plant.id", plant_data["plant_id"])
            span.set_attribute("result", "success")

            emit(
                "new_plant",
                {
                    "plant_id": plant_data["plant_id"],
                    "plant_name": plant_name,
                    "plant_type": plant_type,
                },
                room=str(user_id),
            )
            logging.info(
                f"New plant {plant_name} added successfully for user {user_id}."
            )
        else:
            error_counter.add(
                1, {"error_type": "plant_service_failed", "operation": "add_plant"}
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", "plant_service_failed")
            emit("error", {"error": "Failed to add plant"})
            logging.error(f"Failed to add plant {plant_name} for user {user_id}.")


if __name__ == "__main__":
    socketio.run(app=app, host="0.0.0.0", port=5004, allow_unsafe_werkzeug=True)
