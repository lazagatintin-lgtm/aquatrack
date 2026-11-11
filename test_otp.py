import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

from app import app
from auth.otp import (
    OTP_MAX_ATTEMPTS,
    generate_otp,
    verify_otp
)
from auth.email_service import send_otp_email
from werkzeug.security import generate_password_hash


class FakeOtpCursor:

    def __init__(self, record):
        self.record = record
        self.statements = []
        self.rowcount = 1

    def execute(self, query, parameters=None):
        self.statements.append((query, parameters))

    def fetchone(self):
        return self.record

    def close(self):
        pass


class FakeOtpConnection:

    def __init__(self, cursor):
        self.otp_cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, dictionary=False):
        return self.otp_cursor

    def start_transaction(self):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def is_connected(self):
        return not self.closed

    def close(self):
        self.closed = True


class OtpVerificationTests(unittest.TestCase):

    def verify_with_record(
        self,
        attempts=0,
        expires_at=None,
        otp="012345",
        entered_otp="012345"
    ):
        cursor = FakeOtpCursor({
            "id": 13,
            "otp_hash": generate_password_hash(otp),
            "expires_at": expires_at or datetime.now() + timedelta(minutes=5),
            "attempts": attempts,
            "is_used": 0
        })
        connection = FakeOtpConnection(cursor)

        with app.app_context(), patch(
            "auth.otp.get_db_connection",
            return_value=connection
        ):
            result = verify_otp(7, entered_otp, "login")

        return result, connection, cursor

    def test_generated_otp_is_six_digits_and_keeps_leading_zeroes(self):
        with patch("auth.otp.secrets.randbelow", return_value=7):
            self.assertEqual(generate_otp(), "000007")

    def test_valid_otp_is_consumed_and_committed(self):
        result, connection, cursor = self.verify_with_record()

        self.assertEqual(result, (True, "OTP verified successfully."))
        self.assertEqual(connection.commits, 1)
        self.assertTrue(connection.closed)
        self.assertIn("SET is_used = 1", cursor.statements[-1][0])

    def test_incorrect_otp_increments_attempt_count(self):
        cursor = FakeOtpCursor({
            "id": 13,
            "otp_hash": generate_password_hash("012345"),
            "expires_at": datetime.now() + timedelta(minutes=5),
            "attempts": 1,
            "is_used": 0
        })
        connection = FakeOtpConnection(cursor)

        with app.app_context(), patch(
            "auth.otp.get_db_connection",
            return_value=connection
        ):
            result = verify_otp(7, "999999", "login")

        self.assertEqual(result, (False, "Incorrect OTP. Please try again."))
        self.assertEqual(
            cursor.statements[-1][1],
            (2, 0, 13)
        )
        self.assertEqual(connection.commits, 1)

    def test_final_incorrect_attempt_invalidates_otp(self):
        result, connection, cursor = self.verify_with_record(
            attempts=OTP_MAX_ATTEMPTS - 1,
            otp="012345",
            entered_otp="999999"
        )

        self.assertEqual(
            result,
            (
                False,
                "Too many incorrect attempts. Please request a new code."
            )
        )
        self.assertEqual(
            cursor.statements[-1][1],
            (OTP_MAX_ATTEMPTS, 1, 13)
        )
        self.assertEqual(connection.commits, 1)

    def test_expired_otp_is_invalidated(self):
        result, connection, cursor = self.verify_with_record(
            expires_at=datetime.now() - timedelta(seconds=1)
        )

        self.assertEqual(
            result,
            (
                False,
                "Your OTP has expired. Please request a new code."
            )
        )
        self.assertEqual(cursor.statements[-1][1], (13,))
        self.assertEqual(connection.commits, 1)

    def test_invalid_purpose_does_not_access_database(self):
        with app.app_context(), patch(
            "auth.otp.get_db_connection"
        ) as get_connection:
            result = verify_otp(7, "012345", "unknown")

        self.assertEqual(result, (False, "Invalid OTP request."))
        get_connection.assert_not_called()


class OtpEmailTests(unittest.TestCase):

    def test_sends_login_code_using_configured_mail_extension(self):
        previous_sender = app.config.get("MAIL_DEFAULT_SENDER")
        previous_mail = app.extensions.get("mail")
        mail_mock = Mock()
        app.extensions["mail"] = mail_mock
        app.config["MAIL_DEFAULT_SENDER"] = "noreply@example.com"

        try:
            with app.app_context():
                sent = send_otp_email(
                    "customer@example.com",
                    "000007",
                    purpose="login"
                )
        finally:
            app.extensions["mail"] = previous_mail
            app.config["MAIL_DEFAULT_SENDER"] = previous_sender

        self.assertTrue(sent)
        message = mail_mock.send.call_args.args[0]
        self.assertEqual(message.recipients, ["customer@example.com"])
        self.assertIn("000007", message.body)

    def test_resend_requires_an_explicit_sender(self):
        previous_config = {
            key: app.config.get(key)
            for key in (
                "MAIL_SERVER",
                "MAIL_USERNAME",
                "MAIL_DEFAULT_SENDER"
            )
        }
        previous_mail = app.extensions.get("mail")
        mail_mock = Mock()
        app.extensions["mail"] = mail_mock
        app.config.update(
            MAIL_SERVER="smtp.resend.com",
            MAIL_USERNAME="resend",
            MAIL_DEFAULT_SENDER=None
        )

        try:
            with app.app_context():
                sent = send_otp_email(
                    "customer@example.com",
                    "000007",
                    purpose="login"
                )
        finally:
            app.extensions["mail"] = previous_mail
            app.config.update(previous_config)

        self.assertFalse(sent)
        mail_mock.send.assert_not_called()

    def test_rejects_malformed_code_without_sending_email(self):
        mail_mock = Mock()
        previous_mail = app.extensions.get("mail")
        app.extensions["mail"] = mail_mock

        try:
            with app.app_context():
                sent = send_otp_email(
                    "customer@example.com",
                    "12345",
                    purpose="login"
                )
        finally:
            app.extensions["mail"] = previous_mail

        self.assertFalse(sent)
        mail_mock.send.assert_not_called()


class LoginOtpRouteTests(unittest.TestCase):

    def setUp(self):
        self.old_testing = app.config.get("TESTING")
        self.old_csrf = app.config.get("WTF_CSRF_ENABLED")
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()

    def tearDown(self):
        app.config.update(
            TESTING=self.old_testing,
            WTF_CSRF_ENABLED=self.old_csrf
        )

    def test_valid_login_otp_creates_authenticated_session(self):
        with self.client.session_transaction() as user_session:
            user_session["pending_user_id"] = 7
            user_session["pending_email"] = "owner@example.com"
            user_session["pending_role"] = "admin"

        with patch(
            "auth.routes.verify_otp",
            return_value=(True, "OTP verified successfully.")
        ) as verify, patch(
            "auth.routes.get_user_by_email",
            return_value={
                "id": 7,
                "name": "Store Owner",
                "email": "owner@example.com",
                "role": "admin"
            }
        ):
            response = self.client.post(
                "/auth/verify-otp",
                data={"otp": "000007"}
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/dashboard", response.headers["Location"])
        verify.assert_called_once_with(7, "000007", purpose="login")
        with self.client.session_transaction() as user_session:
            self.assertEqual(user_session["user_id"], 7)
            self.assertEqual(user_session["role"], "admin")
            self.assertNotIn("pending_user_id", user_session)

    def test_invalid_login_otp_does_not_authenticate_session(self):
        with self.client.session_transaction() as user_session:
            user_session["pending_user_id"] = 7
            user_session["pending_email"] = "owner@example.com"
            user_session["pending_role"] = "admin"

        with patch(
            "auth.routes.verify_otp",
            return_value=(False, "Incorrect OTP. Please try again.")
        ):
            response = self.client.post(
                "/auth/verify-otp",
                data={"otp": "999999"}
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/verify-otp", response.headers["Location"])
        with self.client.session_transaction() as user_session:
            self.assertNotIn("user_id", user_session)


class PaymentOtpResendTests(unittest.TestCase):

    def test_malformed_payment_code_does_not_consume_attempt_or_open_db(self):
        old_testing = app.config.get("TESTING")
        old_csrf = app.config.get("WTF_CSRF_ENABLED")
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = app.test_client()

        try:
            with client.session_transaction() as user_session:
                user_session["user_id"] = 7
                user_session["role"] = "customer"
                user_session["pending_payment"] = {
                    "sale_id": 12,
                    "payments": [{
                        "payment_method": "Cash on Pickup",
                        "amount": "10.00",
                        "reference_number": "",
                        "proof_path": None
                    }]
                }

            with patch(
                "payment.routes.get_db_connection"
            ) as get_connection:
                response = client.post(
                    "/payment/verify-otp",
                    data={"otp": "123"}
                )
        finally:
            app.config.update(
                TESTING=old_testing,
                WTF_CSRF_ENABLED=old_csrf
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/payment/verify-otp", response.headers["Location"])
        get_connection.assert_not_called()

    def test_verify_page_offers_csrf_protected_resend_action(self):
        old_testing = app.config.get("TESTING")
        old_csrf = app.config.get("WTF_CSRF_ENABLED")
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = app.test_client()

        try:
            with client.session_transaction() as user_session:
                user_session["user_id"] = 7
                user_session["role"] = "customer"
                user_session["pending_payment"] = {
                    "sale_id": 12,
                    "payments": [{
                        "payment_method": "Cash on Pickup",
                        "amount": "10.00",
                        "reference_number": "",
                        "proof_path": None
                    }]
                }

            response = client.get("/payment/verify-otp")
        finally:
            app.config.update(
                TESTING=old_testing,
                WTF_CSRF_ENABLED=old_csrf
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/payment/resend-otp", response.data)
        self.assertIn(b"Resend Verification Code", response.data)

    def test_resend_sends_new_code_for_owned_pending_payment(self):
        cursor = FakeOtpCursor(None)
        cursor.fetchone = lambda: {
            "id": 12,
            "status": "Pending",
            "email": "customer@example.com"
        }
        connection = FakeOtpConnection(cursor)
        old_testing = app.config.get("TESTING")
        old_csrf = app.config.get("WTF_CSRF_ENABLED")
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = app.test_client()

        with patch(
            "payment.routes.can_resend_otp",
            return_value=True
        ), patch(
            "payment.routes.get_db_connection",
            return_value=connection
        ), patch(
            "payment.routes.generate_otp",
            return_value="000007"
        ), patch(
            "payment.routes.save_otp",
            return_value=True
        ) as save, patch(
            "payment.routes.send_otp_email",
            return_value=True
        ) as send:
            try:
                with client.session_transaction() as user_session:
                    user_session["user_id"] = 7
                    user_session["role"] = "customer"
                    user_session["pending_payment"] = {
                        "sale_id": 12,
                        "payments": [{
                            "payment_method": "Cash on Pickup",
                            "amount": "10.00",
                            "reference_number": "",
                            "proof_path": None
                        }]
                    }

                response = client.post("/payment/resend-otp")
            finally:
                app.config.update(
                    TESTING=old_testing,
                    WTF_CSRF_ENABLED=old_csrf
                )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/payment/verify-otp", response.headers["Location"])
        save.assert_called_once_with(7, "000007", purpose="payment")
        send.assert_called_once_with(
            "customer@example.com",
            "000007",
            purpose="payment"
        )
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
