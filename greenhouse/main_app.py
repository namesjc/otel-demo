# main_app.py

import logging

import requests
from config import Config
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from loggingfw import CustomOtelFW

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY

# Initialize OpenTelemetry framework
otelFW = CustomOtelFW(service_name="main_app", instance_id="1")

# Setup logging
handler = otelFW.setup_logging()
logging.getLogger().addHandler(handler)

# Setup tracing
tracer = otelFW.setup_tracing()

# Setup metrics
meter = otelFW.setup_metrics()

# Instrument Flask app and requests library
otelFW.instrument_flask_app(app)
otelFW.instrument_requests()

# Create custom metrics
request_counter = meter.create_counter(
    name="main_app.requests.count", description="Total number of requests", unit="1"
)

error_counter = meter.create_counter(
    name="main_app.errors.count", description="Total number of errors", unit="1"
)

dashboard_views = meter.create_counter(
    name="main_app.dashboard.views", description="Number of dashboard views", unit="1"
)

login_attempts = meter.create_counter(
    name="main_app.login.attempts", description="Number of login attempts", unit="1"
)

signup_attempts = meter.create_counter(
    name="main_app.signup.attempts", description="Number of signup attempts", unit="1"
)

USER_SERVICE_URL = "http://user_service:5001"
PLANT_SERVICE_URL = "http://plant_service:5002"
SIMULATION_SERVICE_URL = "http://simulation_service:5003"
WEBSOCKET_SERVICE_URL = "http://websocket_service:5004"
BUG_SERVICE_URL = "http://bug_service:5010"


@app.route("/")
def index():
    with tracer.start_as_current_span("index_page") as span:
        request_counter.add(1, {"endpoint": "index"})
        span.set_attribute("page", "index")
        logging.info("Rendering index page...")
        return render_template("index.html")


@app.route("/dashboard", methods=["GET"])
def dashboard():
    with tracer.start_as_current_span("dashboard_page") as span:
        request_counter.add(1, {"endpoint": "dashboard"})
        dashboard_views.add(1)

        if "user_id" not in session:
            error_counter.add(
                1, {"error_type": "unauthorized", "endpoint": "dashboard"}
            )
            span.set_attribute("error", "unauthorized")
            logging.error("Unauthorized access to dashboard")
            return redirect(url_for("login"))

        user_id = session["user_id"]
        span.set_attribute("user.id", user_id)

        # Fetch user data
        with tracer.start_as_current_span("fetch_user_data") as user_span:
            user_span.set_attribute("user.id", user_id)
            user_response = requests.get(f"{USER_SERVICE_URL}/user/{user_id}")
            if user_response.status_code != 200:
                error_counter.add(
                    1, {"error_type": "fetch_user_failed", "endpoint": "dashboard"}
                )
                user_span.set_attribute("error", True)
                logging.error("Failed to fetch user data")
                return "Failed to fetch user data", 500
            user = user_response.json()

        # Fetch plants data
        with tracer.start_as_current_span("fetch_plants_data") as plant_span:
            plant_span.set_attribute("user.id", user_id)
            plant_response = requests.get(f"{PLANT_SERVICE_URL}/plants/{user_id}")
            if plant_response.status_code != 200:
                error_counter.add(
                    1, {"error_type": "fetch_plants_failed", "endpoint": "dashboard"}
                )
                plant_span.set_attribute("error", True)
                logging.error("Failed to fetch plants data")
                return "Failed to fetch plants data", 500
            plants = plant_response.json()
            plant_span.set_attribute("plants.count", len(plants))

        # Start simulation for this user
        with tracer.start_as_current_span("start_simulation") as sim_span:
            sim_span.set_attribute("user.id", user_id)
            simulation_response = requests.post(
                f"{SIMULATION_SERVICE_URL}/start_simulation", json={"user_id": user_id}
            )
            if simulation_response.status_code != 200:
                error_counter.add(
                    1,
                    {"error_type": "start_simulation_failed", "endpoint": "dashboard"},
                )
                sim_span.set_attribute("error", True)
                logging.error("Failed to start simulation")
                return "Failed to start simulation", 500
            sim_span.set_attribute("result", "success")

        span.set_attribute("result", "success")
        logging.info(f"Dashboard loaded successfully for user {user_id}")
        return render_template("dashboard.html", user=user, plants=plants)


@app.route("/toggle_error_mode", methods=["POST"])
def toggle_error_mode():
    with tracer.start_as_current_span("toggle_error_mode") as span:
        request_counter.add(1, {"endpoint": "toggle_error_mode"})
        # Toggle bug mode in the bug service
        response = requests.post(f"{BUG_SERVICE_URL}/toggle_bug_mode")
        if response.status_code == 200:
            span.set_attribute("result", "success")
            logging.info("Toggled error mode")
            return redirect(request.referrer or url_for("index"))
        else:
            error_counter.add(
                1, {"error_type": "toggle_failed", "endpoint": "toggle_error_mode"}
            )
            span.set_attribute("error", True)
            logging.error("Failed to toggle error mode")
            return "Failed to toggle bug mode", 500


@app.route("/signup", methods=["GET", "POST"])
def signup():
    with tracer.start_as_current_span("signup") as span:
        request_counter.add(1, {"endpoint": "signup", "method": request.method})

        if request.method == "POST":
            signup_attempts.add(1)
            span.set_attribute("username", request.form.get("username", ""))

            with tracer.start_as_current_span("user_service_signup"):
                response = requests.post(
                    f"{USER_SERVICE_URL}/signup", data=request.form
                )

            if response.status_code == 200:
                span.set_attribute("result", "success")
                logging.info(
                    f"User signup successful for {request.form.get('username', '')}"
                )
                return redirect(url_for("login"))
            else:
                error_counter.add(
                    1, {"error_type": "signup_failed", "endpoint": "signup"}
                )
                span.set_attribute("error", True)
                logging.error(f"Signup failed for {request.form.get('username', '')}")
            return response.text

        return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    with tracer.start_as_current_span("login") as span:
        request_counter.add(1, {"endpoint": "login", "method": request.method})

        if request.method == "POST":
            login_attempts.add(1)
            span.set_attribute("username", request.form.get("username", ""))

            with tracer.start_as_current_span("user_service_login"):
                response = requests.post(f"{USER_SERVICE_URL}/login", data=request.form)

            if response.status_code == 200:
                user_id = response.json().get("user_id")
                span.set_attribute("result", "success")
                span.set_attribute("user.id", user_id)
                logging.info(f"User {user_id} logged in")
                session["user_id"] = user_id
                return redirect(url_for("dashboard"))
            else:
                error_counter.add(
                    1, {"error_type": "login_failed", "endpoint": "login"}
                )
                span.set_attribute("error", True)
            return response.text

        return render_template("login.html")


@app.route("/logout")
def logout():
    with tracer.start_as_current_span("logout") as span:
        request_counter.add(1, {"endpoint": "logout"})

        with tracer.start_as_current_span("user_service_logout"):
            response = requests.get(f"{USER_SERVICE_URL}/logout")

        if response.status_code == 200:
            span.set_attribute("result", "success")
            logging.info("User logged out")
            session.pop("user_id", None)
        else:
            error_counter.add(1, {"error_type": "logout_failed", "endpoint": "logout"})
            span.set_attribute("error", True)
            logging.error("Failed to logout user")

        return redirect(url_for("index"))


@app.route("/bug_mode_status", methods=["GET"])
def bug_mode_status():
    with tracer.start_as_current_span("bug_mode_status") as span:
        request_counter.add(1, {"endpoint": "bug_mode_status"})
        # Toggle bug mode in the bug service
        response = requests.get(f"{BUG_SERVICE_URL}/bug_mode_status")
        logging.info(response.json())
        if response.status_code == 200:
            span.set_attribute("result", "success")
            logging.info("Fetched bug mode status")
            return jsonify(response.json())
        else:
            error_counter.add(
                1, {"error_type": "fetch_status_failed", "endpoint": "bug_mode_status"}
            )
            span.set_attribute("error", True)
            logging.error("Failed to fetch bug mode status")
            return "Failed to get bug mode status", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)
