import os
from dotenv import load_dotenv


# ==========================================
# LOAD ENVIRONMENT VARIABLES
# ==========================================

load_dotenv()


def get_env_bool(name, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in ("true", "1", "yes", "on")


def get_env_int(name, default):
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"Invalid integer value for environment variable: {name}"
        )


class Config:

    # ==========================================
    # FLASK SECURITY
    # ==========================================

    APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

    SECRET_KEY = os.getenv("SECRET_KEY")

    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is missing. Please set it in your .env file."
        )

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = get_env_bool(
        "SESSION_COOKIE_SECURE",
        APP_ENV == "production"
    )
    MAX_CONTENT_LENGTH = 11 * 1024 * 1024

    PERMANENT_SESSION_LIFETIME = get_env_int(
        "PERMANENT_SESSION_LIFETIME", 3600
    )

    # ==========================================
    # MYSQL DATABASE SETTINGS
    # ==========================================

    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = get_env_int("MYSQL_PORT", 3306)
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "aquatrack_db")

    # ==========================================
    # EMAIL / GMAIL SMTP SETTINGS
    # ==========================================

    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
    MAIL_PORT = get_env_int("MAIL_PORT", 587)

    MAIL_USE_TLS = get_env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = get_env_bool("MAIL_USE_SSL", False)

    MAIL_TIMEOUT = get_env_int("MAIL_TIMEOUT", 30)

    MAIL_USERNAME = (
        "resend"
        if MAIL_SERVER.lower() == "smtp.resend.com"
        else os.getenv(
            "MAIL_USERNAME",
            "rowenasalabsabin23@gmail.com"
        )
    )
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")

    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER") or (
        None
        if MAIL_SERVER.lower() == "smtp.resend.com"
        else MAIL_USERNAME
    )
    GCASH_QR_IMAGE = os.getenv("GCASH_QR_IMAGE", "").strip()

    # ==========================================
    # CSRF SECURITY
    # ==========================================

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600