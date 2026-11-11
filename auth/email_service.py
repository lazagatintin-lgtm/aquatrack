import logging
import re

from flask import current_app
from flask_mail import Message


logger = logging.getLogger(__name__)


# ==========================================
# EMAIL SETTINGS
# ==========================================

VALID_OTP_PURPOSES = ("login", "payment")


# ==========================================
# EMAIL VALIDATION
# ==========================================

def is_valid_email(email):
    """Check whether the recipient email has a valid format."""

    if not isinstance(email, str) or not email or len(email) > 100:
        return False

    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

    return re.fullmatch(pattern, email) is not None


# ==========================================
# OTP EMAIL CONTENT
# ==========================================

def build_otp_email(otp, purpose="login"):
    """Create the subject and body of an OTP email."""

    if purpose == "payment":
        subject = "AquaTrack - Payment Verification Code"

        body = f"""
Hello,

You requested a verification code for your payment transaction.

Your verification code is:

{otp}

This code is valid for 5 minutes.

Do not share this code with anyone.

If you did not request this code, you may ignore this email.

Thank you,
AquaTrack - JRJ PETSHOP
"""

    elif purpose == "login":
        subject = "AquaTrack - Login Verification Code"

        body = f"""
Hello,

You requested to log in to your AquaTrack account.

Your verification code is:

{otp}

This code is valid for 5 minutes.

Do not share this code with anyone.

If you did not request this code, you may ignore this email.

Thank you,
AquaTrack - JRJ PETSHOP
"""

    else:
        raise ValueError("Invalid OTP purpose.")

    return subject, body


# ==========================================
# SEND OTP EMAIL
# ==========================================

def send_otp_email(recipient_email, otp, purpose="login"):
    """Send an OTP verification email."""

    if not is_valid_email(recipient_email):
        logger.warning(
            "OTP email was not sent because the recipient is invalid."
        )
        return False

    if purpose not in VALID_OTP_PURPOSES:
        logger.warning(
            "OTP email was not sent because the purpose is invalid."
        )
        return False

    if not isinstance(otp, str) or not re.fullmatch(r"\d{6}", otp):
        logger.warning(
            "OTP email was not sent because the OTP format is invalid."
        )
        return False

    try:
        mail = current_app.extensions.get("mail")

        if mail is None:
            logger.error("Flask-Mail has not been initialized.")
            return False

        subject, body = build_otp_email(otp, purpose)

        sender = current_app.config.get("MAIL_DEFAULT_SENDER")
        if (
            not sender
            and current_app.config.get("MAIL_SERVER", "").lower()
            != "smtp.resend.com"
        ):
            sender = current_app.config.get("MAIL_USERNAME")

        if not sender:
            logger.error("No default email sender is configured.")
            return False

        message = Message(
            subject=subject,
            recipients=[recipient_email],
            body=body,
            sender=sender
        )

        mail.send(message)

        logger.info("OTP email sent successfully.")
        return True

    except Exception:
        logger.exception("Failed to send OTP email.")
        return False