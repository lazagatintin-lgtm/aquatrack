import re
import secrets
from datetime import datetime, timedelta

import mysql.connector

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from flask import current_app

from database.db import (
    get_db_connection,
    generate_custom_code
)


# ==========================================
# OTP SETTINGS
# ==========================================

OTP_EXPIRATION_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60

VALID_PURPOSES = ("login", "payment")


# ==========================================
# DATABASE CLEANUP
# ==========================================

def close_database(connection, cursor):

    if cursor is not None:
        try:
            cursor.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "OTP CURSOR CLOSE ERROR"
            )

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "OTP CONNECTION CLOSE ERROR"
            )


# ==========================================
# INPUT VALIDATION
# ==========================================

def is_valid_user_id(user_id):

    return (
        isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and user_id > 0
    )


def is_valid_purpose(purpose):

    return (
        isinstance(purpose, str)
        and purpose in VALID_PURPOSES
    )


def is_valid_otp(otp):

    return (
        isinstance(otp, str)
        and re.fullmatch(r"\d{6}", otp) is not None
    )


# ==========================================
# GENERATE OTP
# ==========================================

def generate_otp():
    """Generate a cryptographically secure six-digit OTP."""

    return f"{secrets.randbelow(1000000):06d}"


# ==========================================
# SAVE OTP
# ==========================================

def save_otp(user_id, otp, purpose="login"):
    """
    Save a hashed OTP and invalidate previous active OTPs.

    The user row is locked to prevent simultaneous OTP
    requests from creating multiple active OTP records.

    The resend cooldown is also enforced inside this
    transaction.
    """

    if (
        not is_valid_user_id(user_id)
        or not is_valid_purpose(purpose)
        or not is_valid_otp(otp)
    ):
        return False

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()

        cursor = connection.cursor()

        # LOCK USER ROW
        cursor.execute("""
            SELECT id
            FROM tbl_users
            WHERE id = %s
            FOR UPDATE
        """, (user_id,))

        user = cursor.fetchone()

        if not user:
            connection.rollback()
            return False

        # CHECK RESEND COOLDOWN
        cursor.execute("""
            SELECT created_at
            FROM tbl_email_otps
            WHERE user_id = %s
              AND purpose = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        """, (
            user_id,
            purpose
        ))

        last_otp = cursor.fetchone()

        if last_otp and last_otp[0]:

            cooldown_end = last_otp[0] + timedelta(
                seconds=OTP_RESEND_COOLDOWN_SECONDS
            )

            if datetime.now() < cooldown_end:
                connection.rollback()
                return False

        # GENERATE HASH AND EXPIRATION
        otp_hash = generate_password_hash(otp)

        expires_at = datetime.now() + timedelta(
            minutes=OTP_EXPIRATION_MINUTES
        )

        # INVALIDATE PREVIOUS ACTIVE OTPs
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

        # GENERATE CUSTOM OTP RECORD CODE
        otp_code = generate_custom_code(
            cursor,
            "tbl_email_otps"
        )

        # INSERT NEW OTP
        cursor.execute("""
            INSERT INTO tbl_email_otps
            (
                otp_code,
                user_id,
                otp_hash,
                expires_at,
                attempts,
                is_used,
                purpose
            )
            VALUES (%s, %s, %s, %s, 0, 0, %s)
        """, (
            otp_code,
            user_id,
            otp_hash,
            expires_at,
            purpose
        ))

        connection.commit()

        return True

    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "OTP SAVE DATABASE ERROR"
        )

        return False

    except Exception:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "OTP SAVE UNEXPECTED ERROR"
        )

        return False

    finally:
        close_database(connection, cursor)


# ==========================================
# VERIFY OTP USING EXISTING TRANSACTION
# ==========================================

def verify_otp_for_transaction(
    cursor,
    user_id,
    entered_otp,
    purpose="payment"
):
    """
    Verify OTP inside an existing database transaction.

    The caller must:
    1. Start the transaction.
    2. Use a dictionary cursor.
    3. Commit or roll back the transaction.

    A valid OTP is not consumed here.
    The caller must mark it as used only after all
    related operations have succeeded.
    """

    if (
        not is_valid_user_id(user_id)
        or not is_valid_purpose(purpose)
    ):
        return (
            False,
            "Invalid OTP request.",
            None
        )

    # LOCK THE LATEST ACTIVE OTP
    cursor.execute("""
        SELECT
            id,
            otp_hash,
            expires_at,
            attempts,
            is_used
        FROM tbl_email_otps
        WHERE user_id = %s
          AND purpose = %s
          AND is_used = 0
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        FOR UPDATE
    """, (
        user_id,
        purpose
    ))

    otp_record = cursor.fetchone()

    if not otp_record:
        return (
            False,
            "No active OTP found. Please request a new code.",
            None
        )

    otp_id = otp_record["id"]

    # CHECK EXPIRATION
    if otp_record["expires_at"] <= datetime.now():

        cursor.execute("""
            UPDATE tbl_email_otps
            SET is_used = 1
            WHERE id = %s
              AND is_used = 0
        """, (otp_id,))

        return (
            False,
            "Your OTP has expired. Please request a new code.",
            None
        )

    # CHECK MAXIMUM ATTEMPTS
    attempts = int(otp_record["attempts"] or 0)

    if attempts >= OTP_MAX_ATTEMPTS:

        cursor.execute("""
            UPDATE tbl_email_otps
            SET is_used = 1
            WHERE id = %s
              AND is_used = 0
        """, (otp_id,))

        return (
            False,
            "Too many incorrect attempts. Please request a new code.",
            None
        )

    # CHECK OTP FORMAT AND HASH
    valid_otp = False

    if is_valid_otp(entered_otp):

        try:
            valid_otp = check_password_hash(
                otp_record["otp_hash"],
                entered_otp
            )

        except (TypeError, ValueError):
            current_app.logger.exception(
                "OTP HASH VERIFICATION ERROR"
            )

            valid_otp = False

    # HANDLE INCORRECT OTP
    if not valid_otp:

        new_attempts = attempts + 1

        cursor.execute("""
            UPDATE tbl_email_otps
            SET attempts = %s,
                is_used = %s
            WHERE id = %s
              AND is_used = 0
        """, (
            new_attempts,
            1 if new_attempts >= OTP_MAX_ATTEMPTS else 0,
            otp_id
        ))

        if new_attempts >= OTP_MAX_ATTEMPTS:
            return (
                False,
                "Too many incorrect attempts. Please request a new code.",
                None
            )

        return (
            False,
            "Incorrect OTP. Please try again.",
            None
        )

    # VALID OTP
    # DO NOT CONSUME IT HERE.
    return (
        True,
        "OTP verified successfully.",
        otp_id
    )


# ==========================================
# VERIFY AND CONSUME OTP
# ==========================================

def verify_otp(user_id, entered_otp, purpose="login"):
    """
    Verify and consume an OTP using its own transaction.
    """

    if (
        not is_valid_user_id(user_id)
        or not is_valid_purpose(purpose)
    ):
        return (
            False,
            "Invalid OTP request."
        )

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()

        cursor = connection.cursor(dictionary=True)

        otp_valid, otp_message, otp_id = (
            verify_otp_for_transaction(
                cursor,
                user_id,
                entered_otp,
                purpose
            )
        )

        if otp_valid:

            cursor.execute("""
                UPDATE tbl_email_otps
                SET is_used = 1
                WHERE id = %s
                  AND user_id = %s
                  AND purpose = %s
                  AND is_used = 0
            """, (
                otp_id,
                user_id,
                purpose
            ))

            if cursor.rowcount != 1:
                connection.rollback()

                return (
                    False,
                    "Unable to verify OTP. Please request a new code."
                )

        connection.commit()

        return (
            otp_valid,
            otp_message
        )

    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "OTP VERIFICATION DATABASE ERROR"
        )

        return (
            False,
            "Unable to verify OTP. Please try again."
        )

    except Exception:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "OTP VERIFICATION UNEXPECTED ERROR"
        )

        return (
            False,
            "Unable to verify OTP. Please try again."
        )

    finally:
        close_database(connection, cursor)


# ==========================================
# RESEND OTP COOLDOWN
# ==========================================

def can_resend_otp(user_id, purpose="login"):
    """
    Check the resend cooldown for a specific user
    and OTP purpose.
    """

    if (
        not is_valid_user_id(user_id)
        or not is_valid_purpose(purpose)
    ):
        return False

    connection = None
    cursor = None

    try:
        connection = get_db_connection()

        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT created_at
            FROM tbl_email_otps
            WHERE user_id = %s
              AND purpose = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        """, (
            user_id,
            purpose
        ))

        last_otp = cursor.fetchone()

        if not last_otp:
            return True

        created_at = last_otp["created_at"]

        if not created_at:
            return False

        cooldown_end = created_at + timedelta(
            seconds=OTP_RESEND_COOLDOWN_SECONDS
        )

        return datetime.now() >= cooldown_end

    except mysql.connector.Error:
        current_app.logger.exception(
            "OTP COOLDOWN DATABASE ERROR"
        )

        return False

    except Exception:
        current_app.logger.exception(
            "OTP COOLDOWN UNEXPECTED ERROR"
        )

        return False

    finally:
        close_database(connection, cursor)