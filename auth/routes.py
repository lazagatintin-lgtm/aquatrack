import re
import logging

from mysql.connector import Error, IntegrityError

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from auth import auth_blueprint

from auth.otp import (
    generate_otp,
    save_otp,
    verify_otp,
    can_resend_otp
)

from auth.email_service import send_otp_email
from auth.rate_limit import (
    clear_login_failures,
    is_login_blocked,
    record_failed_login
)

from database.db import (
    get_db_connection,
    generate_custom_code
)
from models import User
from utils.product_images import (
    delete_profile_image,
    save_profile_image
)


logger = logging.getLogger(__name__)


@auth_blueprint.before_app_request
def expire_legacy_staff_session():
    if session.get("user_id") and session.get("role") == "staff":
        session.clear()
        flash(
            "Staff accounts are no longer active. Please log in as the owner or a customer.",
            "warning"
        )
        return redirect(url_for("auth.login"))


# ==========================================
# AUTHENTICATION SETTINGS
# ==========================================

VALID_ROLES = ("admin", "customer")

OTP_PURPOSE = "login"

MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 100
MIN_PASSWORD_LENGTH = 8
PASSWORD_REQUIREMENTS_MESSAGE = (
    "Password must be at least 8 characters and include an uppercase letter, "
    "a lowercase letter, a number, and a symbol."
)


def is_secure_password(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return False

    return (
        any(character.isupper() for character in password)
        and any(character.islower() for character in password)
        and any(character.isdigit() for character in password)
        and any(
            not character.isalnum() and not character.isspace()
            for character in password
        )
    )


# ==========================================
# DATABASE CLEANUP
# ==========================================

def close_database(connection=None, cursor=None):
    """Safely close database resources."""

    if cursor is not None:
        try:
            cursor.close()
        except Error:
            logger.exception(
                "Failed to close database cursor."
            )

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except Error:
            logger.exception(
                "Failed to close database connection."
            )


# ==========================================
# USER LOOKUP
# ==========================================

def get_user_by_email(email):
    """Retrieve a user using their email address."""

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                name,
                email,
                password,
                role
            FROM tbl_users
            WHERE email = %s
            LIMIT 1
        """, (email,))

        return cursor.fetchone()

    except Error:
        logger.exception(
            "Failed to retrieve user by email."
        )
        raise

    finally:
        close_database(connection, cursor)


# ==========================================
# OTP SESSION HELPERS
# ==========================================

def invalidate_active_otps(user_id, purpose=OTP_PURPOSE):
    """Invalidate active OTPs for a specific user and purpose."""

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE tbl_email_otps
            SET is_used = 1
            WHERE user_id = %s
              AND purpose = %s
              AND is_used = 0
        """, (
            user_id,
            purpose
        ))

        connection.commit()

        return True

    except Error:
        if connection is not None:
            connection.rollback()

        logger.exception(
            "Failed to invalidate previous OTPs."
        )

        return False

    finally:
        close_database(connection, cursor)


def clear_pending_login():
    """Remove temporary login information from the session."""

    session.pop("pending_user_id", None)
    session.pop("pending_email", None)
    session.pop("pending_role", None)


# ==========================================
# ROLE-BASED REDIRECTION
# ==========================================

def redirect_user_by_role(role):
    """Redirect authenticated users to the correct dashboard."""

    if role == "admin":
        return redirect(
            url_for("admin.dashboard")
        )

    if role == "customer":
        return redirect(
            url_for("customer.dashboard")
        )

    flash(
        "Invalid user account role.",
        "error"
    )

    return redirect(
        url_for("auth.login")
    )


def get_login_endpoint(role):
    return (
        "auth.owner_login"
        if role == "admin"
        else "auth.login"
    )


def redirect_to_login(role):
    return redirect(
        url_for(get_login_endpoint(role))
    )


# ==========================================
# INPUT VALIDATION
# ==========================================

def is_valid_email(email):
    """Validate email format and length."""

    if (
        not isinstance(email, str)
        or not email
        or len(email) > MAX_EMAIL_LENGTH
    ):
        return False

    pattern = (
        r"^[A-Za-z0-9._%+-]+@"
        r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    )

    return re.fullmatch(pattern, email) is not None


def is_valid_name(name):
    """Validate a person's name."""

    if (
        not isinstance(name, str)
        or not name
        or len(name) > MAX_NAME_LENGTH
    ):
        return False

    return (
        re.fullmatch(
            r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]*",
            name
        )
        is not None
    )


# ==========================================
# LOGIN
# ==========================================

@auth_blueprint.route(
    "/login",
    methods=["GET", "POST"]
)
def login():
    return authenticate_account("customer")


@auth_blueprint.route(
    "/owner/login",
    methods=["GET", "POST"]
)
def owner_login():
    return authenticate_account("owner")


@auth_blueprint.route(
    "/staff/login",
    methods=["GET", "POST"]
)
def legacy_staff_login():
    return redirect(url_for("auth.owner_login"))


def authenticate_account(expected_role):

    login_endpoint = get_login_endpoint(expected_role)
    account_type = expected_role
    allowed_roles = (
        ("admin",)
        if expected_role == "owner"
        else ("customer",)
    )

    if session.get("user_id"):
        return redirect_user_by_role(
            session.get("role")
        )

    if request.method == "GET":
        template = (
            "auth/login.html"
            if expected_role == "owner"
            else "auth/customer_auth.html"
        )
        return render_template(
            template,
            account_type=account_type
        )

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    if not email or not password:
        if not email:
            flash("Please enter your email address.", "danger")
        if not password:
            flash("Please enter your password.", "danger")

        return redirect(
            url_for(login_endpoint)
        )

    if not is_valid_email(email):
        flash(
            "Please enter a valid email address.",
            "danger"
        )

        return redirect(
            url_for(login_endpoint)
        )

    try:
        remote_address = request.remote_addr or ""
        if is_login_blocked(email, remote_address):
            flash(
                "Too many unsuccessful sign-in attempts. Please wait 15 minutes before trying again.",
                "danger"
            )
            return redirect(url_for(login_endpoint))

        user = get_user_by_email(email)

        if not user:
            record_failed_login(email, remote_address)
            flash(
                "Account not found. Please check your email or create an account.",
                "danger"
            )

            return redirect(
                url_for(login_endpoint)
            )

        if user["role"] not in allowed_roles:
            if expected_role != "owner":
                message = (
                    "This is an owner account. "
                    "Please use the owner login."
                )
            else:
                message = (
                    "This is not an owner account. "
                    "Please use the customer login."
                )

            flash(message, "danger")
            return redirect(url_for(login_endpoint))

        if not check_password_hash(user["password"], password):
            record_failed_login(email, remote_address)
            flash(
                "Incorrect password. Please try again.",
                "danger"
            )

            return redirect(
                url_for(login_endpoint)
            )

        clear_login_failures(email, remote_address)

        if user["role"] not in VALID_ROLES:
            flash(
                "Invalid user account role.",
                "danger"
            )

            return redirect(
                url_for(login_endpoint)
            )

        # CLEAR OLD TEMPORARY LOGIN DATA

        clear_pending_login()

        session["pending_user_id"] = user["id"]
        session["pending_email"] = user["email"]
        session["pending_role"] = user["role"]

        # CHECK RESEND COOLDOWN

        if not can_resend_otp(
            user["id"],
            OTP_PURPOSE
        ):
            flash(
                "Please wait before requesting another OTP.",
                "warning"
            )

            return redirect(
                url_for("auth.verify_otp_route")
            )

        # GENERATE OTP

        otp = generate_otp()

        # SAVE OTP

        if not save_otp(
            user["id"],
            otp,
            purpose=OTP_PURPOSE
        ):
            clear_pending_login()

            flash(
                "Unable to create your verification code. Please try again.",
                "danger"
            )

            return redirect(
                url_for(login_endpoint)
            )

        # SEND OTP EMAIL

        if not send_otp_email(
            user["email"],
            otp,
            purpose=OTP_PURPOSE
        ):
            invalidate_active_otps(
                user["id"],
                OTP_PURPOSE
            )

            clear_pending_login()

            flash(
                "Unable to send the verification code. Please try again.",
                "danger"
            )

            return redirect(
                url_for(login_endpoint)
            )

        flash(
            "A verification code has been sent to your email.",
            "success"
        )

        return redirect(
            url_for("auth.verify_otp_route")
        )

    except Error:
        logger.exception(
            "Database error during login."
        )

        clear_pending_login()

        flash(
            "A database error occurred. Please try again.",
            "danger"
        )

        return redirect(
            url_for(login_endpoint)
        )

    except Exception:
        logger.exception(
            "Unexpected error during login."
        )

        clear_pending_login()

        flash(
            "Something went wrong. Please try again.",
            "danger"
        )

        return redirect(
            url_for(login_endpoint)
        )


# ==========================================
# VERIFY LOGIN OTP
# ==========================================

@auth_blueprint.route(
    "/verify-otp",
    methods=["GET", "POST"]
)
def verify_otp_route():

    user_id = session.get("pending_user_id")
    email = session.get("pending_email")
    pending_role = session.get("pending_role")

    if not user_id or not email or pending_role not in VALID_ROLES:
        clear_pending_login()
        flash(
            "Please log in first to request a verification code.",
            "warning"
        )

        return redirect_to_login(pending_role)

    if request.method == "GET":
        return render_template(
            "auth/verify_otp.html",
            account_type=(
                "owner"
                if pending_role == "admin"
                else "customer"
            )
        )

    otp = request.form.get(
        "otp",
        ""
    ).strip()

    if not re.fullmatch(r"\d{6}", otp):
        flash(
            "Please enter a valid 6-digit verification code.",
            "warning"
        )

        return redirect(
            url_for("auth.verify_otp_route")
        )

    try:
        # VERIFY AND CONSUME OTP

        otp_valid, otp_message = verify_otp(
            user_id,
            otp,
            purpose=OTP_PURPOSE
        )

        if not otp_valid:
            flash(
                otp_message,
                "danger"
            )

            return redirect(
                url_for("auth.verify_otp_route")
            )

        # RECHECK USER ACCOUNT

        user = get_user_by_email(email)

        if not user or user["id"] != user_id:
            clear_pending_login()

            flash(
                "User account could not be verified. Please log in again.",
                "danger"
            )

            return redirect_to_login(pending_role)

        if (
            user["role"] not in VALID_ROLES
            or user["role"] != pending_role
        ):
            clear_pending_login()

            flash(
                "The account type could not be verified. Please log in again.",
                "danger"
            )

            return redirect_to_login(pending_role)

        # CLEAR OLD SESSION DATA

        session.clear()

        # CREATE AUTHENTICATED SESSION

        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["email"] = user["email"]
        session["role"] = user["role"]

        flash(
            "Login successful. Welcome!",
            "success"
        )

        return redirect_user_by_role(
            user["role"]
        )

    except Error:
        logger.exception(
            "Database error during OTP verification."
        )

        flash(
            "A database error occurred. Please try again.",
            "danger"
        )

        return redirect(
            url_for("auth.verify_otp_route")
        )

    except Exception:
        logger.exception(
            "Unexpected error during OTP verification."
        )

        flash(
            "Something went wrong. Please try again.",
            "danger"
        )

        return redirect(
            url_for("auth.verify_otp_route")
        )


# ==========================================
# RESEND LOGIN OTP
# ==========================================

@auth_blueprint.route(
    "/resend-otp",
    methods=["POST"]
)
def resend_otp():

    user_id = session.get("pending_user_id")
    email = session.get("pending_email")
    pending_role = session.get("pending_role")

    if not user_id or not email or pending_role not in VALID_ROLES:
        clear_pending_login()
        flash(
            "Please log in first before requesting another code.",
            "warning"
        )

        return redirect_to_login(pending_role)

    try:
        # CHECK RESEND COOLDOWN

        if not can_resend_otp(
            user_id,
            OTP_PURPOSE
        ):
            flash(
                "Please wait 60 seconds before requesting another code.",
                "warning"
            )

            return redirect(
                url_for("auth.verify_otp_route")
            )

        # RECHECK USER

        user = get_user_by_email(email)

        if not user or user["id"] != user_id:
            clear_pending_login()

            flash(
                "User account could not be verified. Please log in again.",
                "danger"
            )

            return redirect_to_login(pending_role)

        if (
            user["role"] not in VALID_ROLES
            or user["role"] != pending_role
        ):
            clear_pending_login()

            flash(
                "The account type could not be verified. Please log in again.",
                "danger"
            )

            return redirect_to_login(pending_role)

        # GENERATE NEW OTP

        otp = generate_otp()

        # SAVE NEW OTP

        if not save_otp(
            user_id,
            otp,
            purpose=OTP_PURPOSE
        ):
            flash(
                "Unable to create a new verification code. Please try again.",
                "danger"
            )

            return redirect(
                url_for("auth.verify_otp_route")
            )

        # SEND NEW OTP

        if not send_otp_email(
            email,
            otp,
            purpose=OTP_PURPOSE
        ):
            invalidate_active_otps(
                user_id,
                OTP_PURPOSE
            )

            flash(
                "Unable to send a new verification code. Please try again.",
                "danger"
            )

            return redirect(
                url_for("auth.verify_otp_route")
            )

        flash(
            "A new verification code has been sent to your email.",
            "success"
        )

        return redirect(
            url_for("auth.verify_otp_route")
        )

    except Error:
        logger.exception(
            "Database error while resending OTP."
        )

        flash(
            "A database error occurred. Please try again.",
            "danger"
        )

        return redirect(
            url_for("auth.verify_otp_route")
        )

    except Exception:
        logger.exception(
            "Unexpected error while resending OTP."
        )

        flash(
            "Something went wrong. Please try again.",
            "danger"
        )

        return redirect(
            url_for("auth.verify_otp_route")
        )


# ==========================================
# CUSTOMER REGISTRATION
# ==========================================

@auth_blueprint.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if session.get("user_id"):
        return redirect_user_by_role(
            session.get("role")
        )

    if request.method == "GET":
        return render_template(
            "auth/customer_auth.html"
        )

    # GET REGISTRATION DETAILS

    first_name = " ".join(request.form.get(
        "first_name",
        ""
    ).split())

    middle_name = " ".join(request.form.get(
        "middle_name",
        ""
    ).split())

    last_name = " ".join(request.form.get(
        "last_name",
        ""
    ).split())

    full_name = " ".join(
        part
        for part in (first_name, middle_name, last_name)
        if part
    )

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    if not first_name or not last_name or not is_valid_name(full_name):
        flash(
            "Please enter a valid full name.",
            "warning"
        )

        return redirect(
            url_for("auth.register")
        )

    # ==========================================
    # EMAIL VALIDATION
    # ==========================================

    if not is_valid_email(email):
        flash(
            "Please enter a valid email address.",
            "warning"
        )

        return redirect(
            url_for("auth.register")
        )

    # ==========================================
    # PASSWORD VALIDATION
    # ==========================================

    if not is_secure_password(password):
        flash(
            PASSWORD_REQUIREMENTS_MESSAGE,
            "warning"
        )

        return redirect(
            url_for("auth.register")
        )

    # ==========================================
    # SAVE CUSTOMER ACCOUNT
    # ==========================================

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()

        cursor = connection.cursor()

        user = User.from_password(
            full_name,
            email,
            "customer",
            password
        )

        # GENERATE CUSTOM USER CODE

        user_code = generate_custom_code(
            cursor,
            "tbl_users"
        )

        cursor.execute("""
            INSERT INTO tbl_users
            (
                user_code,
                name,
                email,
                password,
                role
            )
            VALUES (%s, %s, %s, %s, %s)
        """, user.insert_values(user_code))

        connection.commit()

        flash(
            "Registration successful! You can now log in.",
            "success"
        )

        return redirect(
            url_for("auth.login")
        )

    except IntegrityError:
        if connection is not None:
            connection.rollback()

        flash(
            "This email address is already registered.",
            "warning"
        )

        return redirect(
            url_for("auth.register")
        )

    except Error:
        if connection is not None:
            connection.rollback()

        logger.exception(
            "Database error during registration."
        )

        flash(
            "Unable to complete registration. Please try again.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )

    except Exception:
        if connection is not None:
            connection.rollback()

        logger.exception(
            "Unexpected error during registration."
        )

        flash(
            "Something went wrong. Please try again.",
            "danger"
        )

        return redirect(
            url_for("auth.register")
        )

    finally:
        close_database(
            connection,
            cursor
        )


@auth_blueprint.route(
    "/profile",
    methods=["GET", "POST"]
)
def profile():
    user_id = session.get("user_id")
    if not user_id:
        flash("Please log in to manage your profile.", "warning")
        return redirect(url_for("auth.login"))

    connection = None
    cursor = None
    new_profile_image_path = None
    old_profile_image_path = None
    profile_update_committed = False

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        if request.method == "GET":
            cursor.execute("""
                SELECT id, name, email, role, profile_image_path
                FROM tbl_users
                WHERE id = %s
                LIMIT 1
            """, (user_id,))
            user_row = cursor.fetchone()
            if not user_row:
                session.clear()
                flash("Your account could not be found. Please log in again.", "warning")
                return redirect(url_for("auth.login"))
            profile_user = {
                "name": user_row["name"],
                "email": user_row["email"],
                "role": user_row["role"],
                "profile_image_path": user_row.get("profile_image_path")
            }
            return render_template(
                "auth/profile.html",
                profile_user=profile_user
            )

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not is_valid_name(name) or len(name) > MAX_NAME_LENGTH:
            flash("Please enter a valid name.", "warning")
            return redirect(url_for("auth.profile"))
        if not is_valid_email(email):
            flash("Please enter a valid email address.", "warning")
            return redirect(url_for("auth.profile"))
        if new_password and not is_secure_password(new_password):
            flash(PASSWORD_REQUIREMENTS_MESSAGE, "warning")
            return redirect(url_for("auth.profile"))
        if new_password != confirm_password:
            flash("New passwords do not match.", "warning")
            return redirect(url_for("auth.profile"))
        if not current_password:
            flash("Enter your current password to save profile changes.", "warning")
            return redirect(url_for("auth.profile"))

        connection.start_transaction()
        cursor.execute("""
            SELECT id, name, email, password, role, profile_image_path
            FROM tbl_users
            WHERE id = %s
            FOR UPDATE
        """, (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            connection.rollback()
            session.clear()
            flash("Your account could not be found. Please log in again.", "warning")
            return redirect(url_for("auth.login"))

        user = User.from_row(user_row)
        if not user.verify_password(current_password):
            connection.rollback()
            flash("Your current password is incorrect.", "danger")
            return redirect(url_for("auth.profile"))

        old_profile_image_path = user_row.get("profile_image_path")
        uploaded_profile_image = request.files.get("profile_image")
        if uploaded_profile_image and uploaded_profile_image.filename:
            new_profile_image_path = save_profile_image(
                uploaded_profile_image
            )

        password_hash = (
            generate_password_hash(new_password)
            if new_password
            else user.password_hash_for_storage()
        )
        cursor.execute("""
            UPDATE tbl_users
            SET name = %s,
                email = %s,
                password = %s,
                profile_image_path = %s
            WHERE id = %s
        """, (
            name,
            email,
            password_hash,
            new_profile_image_path or old_profile_image_path,
            user_id
        ))
        connection.commit()
        profile_update_committed = True

        if new_profile_image_path and old_profile_image_path:
            delete_profile_image(old_profile_image_path)

        flash("Profile updated successfully.", "success")
        return redirect(url_for("auth.profile"))
    except ValueError as error:
        if connection is not None:
            connection.rollback()
        flash(str(error), "warning")
        return redirect(url_for("auth.profile"))
    except IntegrityError:
        if connection is not None:
            connection.rollback()
        flash("That email address is already in use.", "warning")
        return redirect(url_for("auth.profile"))
    except Error:
        if connection is not None:
            connection.rollback()
        logger.exception("Database error while updating profile.")
        flash("Unable to update your profile. Please try again.", "danger")
        return redirect(url_for("auth.profile"))
    except OSError:
        if connection is not None:
            connection.rollback()
        logger.exception("Unable to save profile photo.")
        flash("Unable to save your profile photo. Please try again.", "danger")
        return redirect(url_for("auth.profile"))
    finally:
        if new_profile_image_path and not profile_update_committed:
            delete_profile_image(new_profile_image_path)
        close_database(connection, cursor)


# ==========================================
# LOGOUT
# ==========================================

@auth_blueprint.route(
    "/logout",
    methods=["POST"]
)
def logout():

    account_role = (
        session.get("role")
        or session.get("pending_role")
    )
    session.clear()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect_to_login(account_role)