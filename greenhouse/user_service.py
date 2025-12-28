# user_service.py

import logging

from config import Config
from flask import Flask, jsonify, request, session
from flask_sqlalchemy import SQLAlchemy
from loggingfw import CustomOtelFW
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

# Initialize OpenTelemetry framework
otelFW = CustomOtelFW(service_name="user_service", instance_id="1")

# Setup logging
handler = otelFW.setup_logging()
logging.getLogger().addHandler(handler)

# Setup tracing
tracer = otelFW.setup_tracing()

# Setup metrics
meter = otelFW.setup_metrics()

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = f"{Config.DATABASE_URL}/user_service_db"
db = SQLAlchemy(app)

# Instrument Flask app and requests library
otelFW.instrument_flask_app(app)
otelFW.instrument_requests()
with app.app_context():
    otelFW.instrument_sqlalchemy(db.engine)

# Create custom metrics
signup_counter = meter.create_counter(
    name="user_service.signups.count",
    description="Total number of signup attempts",
    unit="1",
)

login_counter = meter.create_counter(
    name="user_service.logins.count",
    description="Total number of login attempts",
    unit="1",
)

user_operations_counter = meter.create_counter(
    name="user_service.operations.count",
    description="Total number of user operations",
    unit="1",
)

error_counter = meter.create_counter(
    name="user_service.errors.count", description="Total number of errors", unit="1"
)

BUGS = False


class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


@app.route("/signup", methods=["POST"])
def signup():
    with tracer.start_as_current_span("signup") as span:
        signup_counter.add(1)
        user_operations_counter.add(1, {"operation": "signup"})

        username = request.form["username"]
        password = request.form["password"]
        span.set_attribute("username", username)

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_password)

        global BUGS
        if BUGS == True:
            error_counter.add(1, {"error_type": "bug_triggered", "operation": "signup"})
            span.set_attribute("error", True)
            span.set_attribute("error.type", "bug_triggered")
            logging.error(
                "What a nasty bug! It flew into the user service and stopped the user being created."
            )
            BUGS = False
            return "Failed to create user", 500

        try:
            with tracer.start_as_current_span("database_create_user"):
                db.session.add(new_user)
                db.session.commit()

            span.set_attribute("user.id", new_user.id)
            span.set_attribute("result", "success")
            logging.info(f"New user created: {username}")
            return jsonify({"message": "Signup successful"}), 200
        except IntegrityError:
            error_counter.add(
                1, {"error_type": "duplicate_username", "operation": "signup"}
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", "duplicate_username")
            db.session.rollback()
            logging.error(f"Signup failed: Username '{username}' already exists.")
            return jsonify(
                {"error": "That username is already taken, please choose another."}
            ), 400
        except Exception as e:
            error_counter.add(1, {"error_type": "unexpected", "operation": "signup"})
            span.set_attribute("error", True)
            span.set_attribute("error.type", "unexpected")
            span.set_attribute("error.message", str(e))
            db.session.rollback()
            logging.error(f"An unexpected error occurred during signup:{str(e)}")
            return jsonify(
                {"error": "An unexpected error occurred. Please try again."}
            ), 500


@app.route("/login", methods=["POST"])
def login():
    with tracer.start_as_current_span("login") as span:
        login_counter.add(1)
        user_operations_counter.add(1, {"operation": "login"})

        global BUGS
        if BUGS == True:
            error_counter.add(1, {"error_type": "bug_triggered", "operation": "login"})
            span.set_attribute("error", True)
            span.set_attribute("error.type", "bug_triggered")
            logging.error(
                "What a nasty bug! It flew into the user service and stopped the user being created."
            )
            BUGS = False
            return "Failed to login", 500

        username = request.form["username"]
        password = request.form["password"]
        span.set_attribute("username", username)

        with tracer.start_as_current_span("database_query_user"):
            user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            span.set_attribute("user.id", user.id)
            span.set_attribute("result", "success")
            return jsonify({"user_id": user.id}), 200

        error_counter.add(
            1, {"error_type": "invalid_credentials", "operation": "login"}
        )
        span.set_attribute("error", True)
        span.set_attribute("error.type", "invalid_credentials")
        return jsonify({"error": "Login failed"}), 401


@app.route("/logout", methods=["GET"])
def logout():
    with tracer.start_as_current_span("logout") as span:
        user_operations_counter.add(1, {"operation": "logout"})
        session.pop("user_id", None)
        span.set_attribute("result", "success")
        return jsonify({"message": "Logout successful"}), 200


@app.route("/user/<int:user_id>", methods=["GET"])
def get_user(user_id):
    with tracer.start_as_current_span("get_user") as span:
        user_operations_counter.add(1, {"operation": "get_user"})
        span.set_attribute("user.id", user_id)

        with tracer.start_as_current_span("database_query_user"):
            user = User.query.get(user_id)

        if not user:
            error_counter.add(
                1, {"error_type": "user_not_found", "operation": "get_user"}
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", "user_not_found")
            return jsonify({"error": "User not found"}), 404

        span.set_attribute("username", user.username)
        span.set_attribute("result", "success")
        return jsonify({"id": user.id, "username": user.username}), 200


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
    app.run(host="0.0.0.0", port=5001)
