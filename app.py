import logging

import click

from flask import Flask, render_template, session
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from werkzeug.exceptions import HTTPException
from jinja2 import TemplateNotFound

from config import Config

from auth import auth_blueprint
from customer import customer_blueprint
from admin import admin_blueprint
from analytics import analytics_blueprint
from inventory import inventory_blueprint
from payment import payment_blueprint
from reports import reports_blueprint
from database.db import get_db_connection, generate_custom_code
from database.migrations import apply_migrations
from utils.encrypted_session import EncryptedCookieSessionInterface


# ==========================================
# LOGGING CONFIGURATION
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# FLASK APPLICATION
# ==========================================

app = Flask(__name__)
app.config.from_object(Config)
app.session_interface = EncryptedCookieSessionInterface(
    app.config["SECRET_KEY"]
)


@app.after_request
def prevent_authenticated_page_caching(response):
    if (
        session.get("user_id")
        or session.get("pending_user_id")
        or session.get("pending_payment")
    ):
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# ==========================================
# EXTENSIONS INITIALIZATION
# ==========================================

csrf = CSRFProtect(app)

mail = Mail(app)


# ==========================================
# BLUEPRINT REGISTRATION
# ==========================================

blueprints = [
    auth_blueprint,
    customer_blueprint,
    admin_blueprint,
    analytics_blueprint,
    inventory_blueprint,
    payment_blueprint,
    reports_blueprint
]

for blueprint in blueprints:
    app.register_blueprint(blueprint)


@app.cli.command("migrate-database")
def migrate_database():
    """Apply pending, versioned database migrations."""

    connection = None
    try:
        connection = get_db_connection()
        applied = apply_migrations(connection)
        if not applied:
            click.echo("Database schema is already up to date.")
            return
        click.echo(
            "Applied database migrations: "
            + ", ".join(applied)
        )
    except Exception as error:
        logger.exception("Database migration failed.")
        if isinstance(error, RuntimeError):
            raise click.ClickException(str(error)) from error
        raise click.ClickException(
            "Database migration failed. Check the application logs."
        ) from error
    finally:
        if connection is not None and connection.is_connected():
            connection.close()


@app.cli.command("check-mail")
def check_mail():
    """Test SMTP connection and authentication without sending email."""

    if not app.config.get("MAIL_USERNAME") or not app.config.get("MAIL_PASSWORD"):
        raise click.ClickException(
            "SMTP username or password is not configured."
        )
    if (
        app.config.get("MAIL_USE_TLS")
        and app.config.get("MAIL_USE_SSL")
    ):
        raise click.ClickException(
            "Configure either SMTP TLS or SSL, not both."
        )

    try:
        with mail.connect() as connection:
            if connection.host is None:
                raise click.ClickException(
                    "SMTP connection is suppressed in the current configuration."
                )
            response_code, _ = connection.host.noop()
            if response_code != 250:
                raise click.ClickException(
                    "SMTP server did not confirm the connection."
                )
        click.echo(
            "SMTP connection and authentication succeeded. No email was sent."
        )
    except click.ClickException:
        raise
    except Exception as error:
        logger.exception("SMTP connection check failed.")
        raise click.ClickException(
            "SMTP connection failed. Check SMTP host, port, TLS/SSL, and credentials."
        ) from error


@app.cli.command("check-config")
def check_config():
    """Validate deployment settings without printing secret values."""

    problems = []
    production = app.config.get("APP_ENV") == "production"
    secret_key = app.config.get("SECRET_KEY") or ""

    if production and len(secret_key) < 32:
        problems.append(
            "Production SECRET_KEY must contain at least 32 characters."
        )
    if production and not app.config.get("SESSION_COOKIE_SECURE"):
        problems.append(
            "Production SESSION_COOKIE_SECURE must be enabled."
        )
    if app.config.get("MAIL_USE_TLS") and app.config.get("MAIL_USE_SSL"):
        problems.append("MAIL_USE_TLS and MAIL_USE_SSL cannot both be enabled.")
    if production and (
        not app.config.get("MAIL_USERNAME")
        or not app.config.get("MAIL_PASSWORD")
        or not app.config.get("MAIL_DEFAULT_SENDER")
    ):
        problems.append(
            "Production SMTP username, password, and sender must be configured."
        )

    if problems:
        for problem in problems:
            click.echo(f"ERROR: {problem}", err=True)
        raise click.ClickException(
            "Configuration validation failed."
        )

    click.echo(
        "Configuration checks passed. Secret values were not displayed."
    )


@app.cli.command("create-owner")
@click.option("--name", prompt=True)
@click.option("--email", prompt=True)
def create_owner(name, email):
    """Provision the first owner account without public registration."""

    from auth.routes import (
        MAX_NAME_LENGTH,
        MIN_PASSWORD_LENGTH,
        is_valid_email,
        is_valid_name
    )
    from werkzeug.security import generate_password_hash

    name = name.strip()
    email = email.strip().lower()
    password = click.prompt(
        "Password",
        hide_input=True,
        confirmation_prompt=True
    )

    if not is_valid_name(name) or len(name) > MAX_NAME_LENGTH:
        raise click.ClickException("Please enter a valid owner name.")

    if not is_valid_email(email):
        raise click.ClickException("Please enter a valid email address.")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise click.ClickException(
            "Password must contain at least 8 characters."
        )

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT 1
            FROM tbl_users
            WHERE role = 'admin'
            LIMIT 1
            FOR UPDATE
        """)

        if cursor.fetchone():
            raise click.ClickException(
                "An owner/admin account already exists. "
                "Use the staff approval page to authorize staff registration."
            )

        cursor.execute("""
                SELECT 1
            FROM tbl_users
            WHERE email = %s
            LIMIT 1
        """, (email,))

        if cursor.fetchone():
            raise click.ClickException(
                "This email address is already registered."
            )

        user_code = generate_custom_code(cursor, "tbl_users")
        cursor.execute("""
            INSERT INTO tbl_users
            (
                user_code,
                name,
                email,
                password,
                role
            )
            VALUES (%s, %s, %s, %s, 'admin')
        """, (
            user_code,
            name,
            email,
            generate_password_hash(password)
        ))

        connection.commit()
        click.echo(
            "Owner account created. Sign in at /auth/staff/login."
        )

    except click.ClickException:
        if connection is not None:
            connection.rollback()
        raise

    except Exception as error:
        if connection is not None:
            connection.rollback()
        logger.exception("Failed to provision the initial owner account.")
        raise click.ClickException(
            "Unable to create the owner account. Check the application logs."
        ) from error

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/")
def home():

    return render_template("index.html")


# ==========================================
# ERROR HANDLING
# ==========================================

def handle_http_error(error):

    error_code = getattr(error, "code", 500)

    if not isinstance(error_code, int):
        error_code = 500

    logger.warning(
        "HTTP error %s: %s",
        error_code,
        error
    )

    try:
        return render_template(
            f"errors/{error_code}.html"
        ), error_code

    except TemplateNotFound:

        logger.warning(
            "Error template for HTTP %s was not found.",
            error_code
        )

        return (
            f"An error occurred. (HTTP {error_code})",
            error_code
        )


@app.errorhandler(Exception)
def handle_unexpected_error(error):

    if isinstance(error, HTTPException):
        return handle_http_error(error)

    logger.exception(
        "Unexpected application error occurred."
    )

    try:
        return render_template(
            "errors/500.html"
        ), 500

    except TemplateNotFound:

        logger.error(
            "The 500 error template was not found."
        )

        return (
            "An unexpected server error occurred.",
            500
        )


# ==========================================
# REGISTER HTTP ERROR HANDLERS
# ==========================================

error_codes = [
    400,
    401,
    403,
    404,
    405,
    409,
    413,
    429,
    500
]

for error_code in error_codes:

    app.register_error_handler(
        error_code,
        handle_http_error
    )


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )