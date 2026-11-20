from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_url() -> str:  # if db not set, build default sqlite
    uri = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{Path(__file__).resolve().parent / 'instance' / 'abc_solutions.db'}",
    )
    # change url scheme for postgresql
    if uri.startswith("postgres://"):
        # old url
        return uri.replace("postgres://", "postgresql+psycopg://", 1)
    if uri.startswith("postgresql://"):
        # new url
        return uri.replace("postgresql://", "postgresql+psycopg://", 1)
    return uri  # leave others unchanged


class Config:
    APP_ENV = os.getenv("APP_ENV", "development").lower()
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MFA_REQUIRED = _bool("MFA_REQUIRED", True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 1800
    WTF_CSRF_ENABLED = False
    AUTO_INIT_DB = _bool("AUTO_INIT_DB", False)
    TRUSTED_HOSTS = [host.strip() for host in os.getenv(
        "TRUSTED_HOSTS", "").split(",") if host.strip()] or None
    MAX_CONTENT_LENGTH = 1024 * 1024


def validate_production(config) -> None:
    if config["APP_ENV"] != "production":
        return
    problems = []  # validation failures
    secret = config.get("SECRET_KEY") or ""
    if len(secret) < 32 or secret.startswith("replace-with-"):
        problems.append(
            "SECRET_KEY must be a random secret with 32+ characters")
    if not config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://"):
        problems.append("DATABASE_URL must use PostgreSQL")
    if not config["SESSION_COOKIE_SECURE"]:
        problems.append("SESSION_COOKIE_SECURE must be true")
    if not config["MFA_REQUIRED"]:
        problems.append("MFA_REQUIRED must be true")
    if not config["TRUSTED_HOSTS"]:
        problems.append("TRUSTED_HOSTS must list the public hostname")
    if config["AUTO_INIT_DB"]:
        problems.append(
            "AUTO_INIT_DB must be false; run database setup as a release step")
    if problems:
        raise RuntimeError(
            "Invalid production configuration: " + "; ".join(problems))
