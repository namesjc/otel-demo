# plant_service.py

import logging

import requests
from config import Config
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from loggingfw import CustomOtelFW

logging.basicConfig(level=logging.INFO)

# Initialize OpenTelemetry framework
otelFW = CustomOtelFW(service_name="plant_service", instance_id="1")

# Setup logging
handler = otelFW.setup_logging()
logging.getLogger().addHandler(handler)

# Setup tracing
tracer = otelFW.setup_tracing()

# Setup metrics
meter = otelFW.setup_metrics()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"{Config.DATABASE_URL}/plant_service_db"
db = SQLAlchemy(app)

# Instrument Flask app and requests library
otelFW.instrument_flask_app(app)
otelFW.instrument_requests()
with app.app_context():
    otelFW.instrument_sqlalchemy(db.engine)

# Create custom metrics
plants_added_counter = meter.create_counter(
    name="plant_service.plants.added",
    description="Total number of plants added",
    unit="1",
)

plants_queries_counter = meter.create_counter(
    name="plant_service.plants.queries",
    description="Total number of plant queries",
    unit="1",
)

error_counter = meter.create_counter(
    name="plant_service.errors.count", description="Total number of errors", unit="1"
)

active_plants_gauge = meter.create_up_down_counter(
    name="plant_service.plants.active", description="Number of active plants", unit="1"
)

SIMULATION_SERVICE_URL = "http://simulation_service:5003"
BUGS = False


class Plant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    plant_type = db.Column(db.String(50), nullable=False)
    health_data = db.Column(db.String(300), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)


@app.route("/plants", methods=["POST"])
def add_plant():
    with tracer.start_as_current_span("add_plant") as span:
        plants_added_counter.add(1)

        global BUGS
        if BUGS == True:
            error_counter.add(
                1, {"error_type": "bug_triggered", "operation": "add_plant"}
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", "bug_triggered")
            logging.error(
                "What a nasty bug! It flew into the plant service and stopped adding plants."
            )
            BUGS = False
            return "Failed to add plant", 500

        data = request.json
        span.set_attribute("plant.name", data["plant_name"])
        span.set_attribute("plant.type", data["plant_type"])
        span.set_attribute("user.id", data["user_id"])

        new_plant = Plant(
            name=data["plant_name"],
            plant_type=data["plant_type"],
            health_data="Healthy",
            user_id=data["user_id"],
        )

        with tracer.start_as_current_span("database_add_plant") as db_span:
            db.session.add(new_plant)
            db.session.commit()
            db_span.set_attribute("plant.id", new_plant.id)
            db_span.set_attribute("result", "success")

        active_plants_gauge.add(1, {"user_id": str(data["user_id"])})
        span.set_attribute("plant.id", new_plant.id)
        logging.info(f"New plant {data['plant_name']} added successfully.")

        # Start simulation for this user
        with tracer.start_as_current_span("start_simulation") as sim_span:
            sim_span.set_attribute("user.id", data["user_id"])
            simulation_response = requests.post(
                f"{SIMULATION_SERVICE_URL}/start_simulation",
                json={"user_id": data["user_id"]},
            )
            if simulation_response.status_code != 200:
                error_counter.add(
                    1, {"error_type": "simulation_failed", "operation": "add_plant"}
                )
                span.set_attribute("simulation.error", True)
                sim_span.set_attribute("error", True)
                logging.error(f"Failed to start simulation for user {data['user_id']}")
                return "Failed to start simulation", 500
            sim_span.set_attribute("result", "success")
            logging.info(f"Started simulation for user {data['user_id']}")

        span.set_attribute("result", "success")
        return jsonify({"plant_id": new_plant.id}), 201


@app.route("/plants/<int:user_id>", methods=["GET"])
def get_plants(user_id):
    with tracer.start_as_current_span("get_plants") as span:
        plants_queries_counter.add(1)
        span.set_attribute("user.id", user_id)

        global BUGS
        if BUGS == True:
            error_counter.add(
                1, {"error_type": "bug_triggered", "operation": "get_plants"}
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", "bug_triggered")
            logging.error(
                "What a nasty bug! It flew into the plant service and stopped the list of plants being returned."
            )
            BUGS = False
            return "Failed to add plant", 500

        with tracer.start_as_current_span("database_query_plants") as db_span:
            plants = Plant.query.filter_by(user_id=user_id).all()
            db_span.set_attribute("plants.count", len(plants))
            db_span.set_attribute("result", "success")

        span.set_attribute("plants.count", len(plants))
        span.set_attribute("result", "success")
        logging.info(f"Retrieved {len(plants)} plants for user {user_id}")

        return jsonify(
            [
                {
                    "id": plant.id,
                    "name": plant.name,
                    "plant_type": plant.plant_type,
                    "health_data": plant.health_data,
                }
                for plant in plants
            ]
        )


@app.route("/trigger_bug", methods=["GET"])
def bug():
    with tracer.start_as_current_span("trigger_bug"):
        logging.error("Triggering bug...")
        global BUGS
        BUGS = True
        return "Bug triggered", 200


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5002)
