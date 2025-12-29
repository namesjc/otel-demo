# simulation_service.py

import logging
import threading
from random import randint, uniform

import requests
from config import Config
from flask import Flask, request
from flask_socketio import SocketIO, join_room, leave_room
from loggingfw import CustomOtelFW

# Initialize OpenTelemetry framework
otelFW = CustomOtelFW(service_name="simulation_service", instance_id="1")

# Setup logging
handler = otelFW.setup_logging()
logging.getLogger().addHandler(handler)

# Setup tracing
tracer = otelFW.setup_tracing()

# Setup metrics
meter = otelFW.setup_metrics()

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", engineio_logger=True)

# Instrument Flask app and requests library
otelFW.instrument_flask_app(app)
otelFW.instrument_requests()

# Create custom metrics
simulation_started_counter = meter.create_counter(
    name="simulation_service.simulations.started",
    description="Total number of simulations started",
    unit="1",
)

data_emitted_counter = meter.create_counter(
    name="simulation_service.data.emitted",
    description="Total number of data points emitted",
    unit="1",
)

active_simulations_gauge = meter.create_up_down_counter(
    name="simulation_service.simulations.active",
    description="Number of active simulations",
    unit="1",
)

error_counter = meter.create_counter(
    name="simulation_service.errors.count",
    description="Total number of errors",
    unit="1",
)

connections_gauge = meter.create_up_down_counter(
    name="simulation_service.connections.active",
    description="Number of active connections",
    unit="1",
)

BUGS = False

PLANT_SERVICE_URL = "http://plant_service:5002"

active_users = {}
simulation_threads = {}
stop_flags = {}


@app.route("/start_simulation", methods=["POST"])
def start_simulation():
    with tracer.start_as_current_span("start_simulation") as span:
        data = request.json
        user_id = data.get("user_id")

        if user_id:
            span.set_attribute("user.id", user_id)
            simulation_started_counter.add(1)

            if user_id in simulation_threads:
                stop_flags[user_id] = True
                simulation_threads[user_id].join()  # Wait for the old thread to finish
                active_simulations_gauge.add(-1, {"user_id": str(user_id)})

            stop_flags[user_id] = False
            thread = threading.Thread(target=simulate_plant_data, args=(user_id,))
            simulation_threads[user_id] = thread
            thread.start()
            active_simulations_gauge.add(1, {"user_id": str(user_id)})

            span.set_attribute("result", "success")
            logging.info(f"Simulation started for user {user_id}.")
            return "Simulation started", 200

        error_counter.add(
            1, {"error_type": "invalid_user_id", "operation": "start_simulation"}
        )
        span.set_attribute("error", True)
        span.set_attribute("error.type", "invalid_user_id")
        logging.error("Start simulation failed: Invalid user_id provided")
        return "Invalid user_id", 400


@app.route("/trigger_bug", methods=["GET"])
def bug():
    with tracer.start_as_current_span("trigger_bug"):
        logging.error("Triggering bug...")
        global BUGS
        BUGS = True
        return "Bug triggered", 200


@socketio.on("connect")
def handle_connect():
    user_id = request.args.get("user_id")
    if user_id:
        with tracer.start_as_current_span("websocket_connect") as span:
            span.set_attribute("user.id", user_id)
            span.set_attribute("result", "success")
            active_users[user_id] = True
            join_room(str(user_id))
            connections_gauge.add(1, {"user_id": str(user_id)})
            logging.info(f"User {user_id} connected and joined room.")


@socketio.on("disconnect")
def on_disconnect():
    user_id = request.args.get("user_id")
    if user_id in active_users:
        with tracer.start_as_current_span("websocket_disconnect") as span:
            span.set_attribute("user.id", user_id)
            span.set_attribute("result", "success")
            del active_users[user_id]
            leave_room(str(user_id))
            connections_gauge.add(-1, {"user_id": str(user_id)})
            logging.info(f"User {user_id} disconnected and left room.")
            if user_id in stop_flags:
                stop_flags[user_id] = True
                if user_id in simulation_threads:
                    simulation_threads[user_id].join()
                    active_simulations_gauge.add(-1, {"user_id": str(user_id)})


def simulate_plant_data(user_id):
    while not stop_flags[user_id]:
        socketio.sleep(2)
        try:
            with tracer.start_as_current_span("fetch_plants_and_simulate") as span:
                span.set_attribute("user.id", user_id)

                response = requests.get(f"{PLANT_SERVICE_URL}/plants/{user_id}")
                if response.status_code == 200:
                    plants = response.json()
                    span.set_attribute("plants.count", len(plants))

                    for plant in plants:
                        fake_data = {
                            "temperature": round(uniform(20.0, 30.0), 2),
                            "humidity": round(uniform(40.0, 60.0), 2),
                            "water_level": randint(1, 10),
                            "number_of_insects": randint(0, 10),
                        }
                        global BUGS
                        if BUGS == True:
                            error_counter.add(
                                1,
                                {
                                    "error_type": "bug_triggered",
                                    "operation": "simulate_data",
                                },
                            )
                            span.set_attribute("error", True)
                            span.set_attribute("error.type", "bug_triggered")
                            logging.error(
                                "What a nasty bug! It flew into the simulation service and stopped producing sensor readings."
                            )
                            BUGS = False
                        else:
                            socketio.emit(
                                "update_plant",
                                {"plant_id": plant["id"], "data": fake_data},
                                room=str(user_id),
                            )
                            data_emitted_counter.add(
                                1,
                                {"user_id": str(user_id), "plant_id": str(plant["id"])},
                            )
                            logging.debug(
                                f"Simulated data for plant {plant['id']} sent to user {user_id}"
                            )
                else:
                    error_counter.add(
                        1,
                        {
                            "error_type": "fetch_plants_failed",
                            "operation": "simulate_data",
                        },
                    )
                    span.set_attribute("error", True)
                    logging.error(
                        f"Failed to fetch plants for user {user_id}. Status code: {response.status_code}"
                    )
        except Exception as e:
            error_counter.add(
                1, {"error_type": "exception", "operation": "simulate_data"}
            )
            logging.error(f"Error in simulation thread for user {user_id}: {str(e)}")


if __name__ == "__main__":
    socketio.run(app=app, host="0.0.0.0", port=5003, allow_unsafe_werkzeug=True)
