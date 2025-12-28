import os

from dotenv import load_dotenv

load_dotenv(".env")

# basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "you-will-never-guess"
    # SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URI") or "sqlite:///" + os.path.join(basedir, "app.db")
    DATABASE_URL = (
        os.environ.get("DATABASE_URL") or "postgresql://user:password@localhost:5432"
    )
    # SQLALCHEMY_DATABASE_URI = "mysql+pymysql://root:password@localhost:3306/microblog"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    OTEL_EXPORTER_OTLP_ENDPOINT = (
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "localhost:4317"
    )
