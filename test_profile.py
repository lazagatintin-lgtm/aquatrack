import os
import unittest
from io import BytesIO
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

from app import app
from auth.routes import is_secure_password
from werkzeug.security import check_password_hash, generate_password_hash


class ProfileCursor:

    def __init__(self, user):
        self.user = user
        self.statements = []

    def execute(self, query, parameters=None):
        self.statements.append((query, parameters))

    def fetchone(self):
        return self.user

    def close(self):
        pass


class ProfileConnection:

    def __init__(self, cursor):
        self.profile_cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, dictionary=False):
        return self.profile_cursor

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


class ProfileRouteTests(unittest.TestCase):

    def test_password_policy_requires_mixed_character_types(self):
        self.assertTrue(is_secure_password("Strong-Pass1"))
        for password in (
            "short1!",
            "lowercase1!",
            "UPPERCASE1!",
            "NoNumber!",
            "NoSymbol12"
        ):
            with self.subTest(password=password):
                self.assertFalse(is_secure_password(password))

    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()
        self.user = {
            "id": 17,
            "name": "Aqua Customer",
            "email": "customer@example.com",
            "password": generate_password_hash("current-password"),
            "role": "customer",
            "profile_image_path": None
        }

    def sign_in(self):
        with self.client.session_transaction() as user_session:
            user_session["user_id"] = self.user["id"]
            user_session["role"] = self.user["role"]

    def test_public_home_introduces_system_audiences_and_account_actions(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"AquaTrack", response.data)
        self.assertIn(b"CUSTOMERS", response.data)
        self.assertIn(b"SHOP OWNER", response.data)
        self.assertIn(b'href="/auth/register"', response.data)
        self.assertIn(b'href="/auth/login"', response.data)
        self.assertIn(b'href="/auth/owner/login"', response.data)

    def test_shared_login_form_uses_html5_required_validation(self):
        response = self.client.get("/auth/login")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"novalidate", response.data)
        self.assertIn(b'id="modal-login-email"', response.data)
        self.assertIn(b'id="modal-login-password"', response.data)
        self.assertIn(b'type="email"', response.data)
        self.assertIn(b'type="password"', response.data)

    def test_customer_account_pages_remain_and_staff_registration_is_disabled(self):
        customer_login = self.client.get("/auth/login")
        customer_register = self.client.get("/auth/register")
        owner_login = self.client.get("/auth/owner/login")

        self.assertEqual(customer_login.status_code, 200)
        self.assertEqual(customer_register.status_code, 200)
        self.assertEqual(owner_login.status_code, 200)
        self.assertIn(b"auth-direct-overlay", customer_login.data)
        self.assertIn(b'data-initial-panel="login"', customer_login.data)
        self.assertIn(b"show-register", customer_register.data)
        self.assertIn(
            b'data-initial-panel="register"',
            customer_register.data
        )
        self.assertNotIn(b"auth-direct-overlay", owner_login.data)
        self.assertIn(b"Owner Login", owner_login.data)
        self.assertEqual(
            self.client.get("/auth/staff/login").status_code,
            302
        )
        self.assertNotIn(b"Owner/Staff", customer_login.data)
        self.assertEqual(
            self.client.get("/auth/staff/signup").status_code,
            404
        )
        self.assertEqual(
            self.client.get("/auth/staff/register").status_code,
            404
        )

    def test_registration_collects_minimum_fields_and_hashes_password(self):
        registration_page = self.client.get("/auth/register")
        self.assertIn(b'name="first_name"', registration_page.data)
        self.assertIn(b'name="middle_name"', registration_page.data)
        self.assertIn(b'name="last_name"', registration_page.data)
        self.assertIn(b'name="email"', registration_page.data)
        self.assertIn(b'name="password"', registration_page.data)
        self.assertNotIn(b'name="confirm_password"', registration_page.data)

        cursor = ProfileCursor(None)
        connection = ProfileConnection(cursor)

        with patch(
            "auth.routes.get_db_connection",
            return_value=connection
        ), patch(
            "auth.routes.generate_custom_code",
            return_value="CUS-TEST-1"
        ):
            response = self.client.post(
                "/auth/register",
                data={
                    "first_name": "Jordan",
                    "email": "jordan@example.com",
                    "last_name": "Sample",
                    "password": "Strong-password1!"
                }
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(connection.commits, 1)
        query, values = cursor.statements[-1]
        self.assertIn("INSERT INTO tbl_users", query)
        self.assertEqual(values[1], "Jordan Sample")
        stored_password = values[3]
        self.assertNotEqual(stored_password, "Strong-password1!")
        self.assertTrue(
            check_password_hash(stored_password, "Strong-password1!")
        )

    def test_incorrect_login_password_shows_safe_error_without_authenticating(self):
        with patch(
            "auth.routes.is_login_blocked",
            return_value=False
        ), patch(
            "auth.routes.get_user_by_email",
            return_value=self.user
        ), patch("auth.routes.record_failed_login") as record_failure:
            response = self.client.post(
                "/auth/login",
                data={
                    "email": self.user["email"],
                    "password": "incorrect-password"
                },
                follow_redirects=True
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Incorrect password. Please try again.", response.data)
        self.assertNotIn(b"Traceback", response.data)
        self.assertNotIn(b"Internal Server Error", response.data)
        record_failure.assert_called_once()
        with self.client.session_transaction() as user_session:
            self.assertNotIn("user_id", user_session)

    def test_profile_requires_authentication(self):
        response = self.client.get("/auth/profile")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["Location"])

    def test_existing_staff_session_is_logged_out(self):
        with self.client.session_transaction() as user_session:
            user_session["user_id"] = 23
            user_session["role"] = "staff"

        response = self.client.get("/auth/profile")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["Location"])
        with self.client.session_transaction() as user_session:
            self.assertNotIn("user_id", user_session)

    def test_session_cookie_encrypts_contents_and_round_trips(self):
        private_value = "session-private-marker"
        with self.client.session_transaction() as user_session:
            user_session["user_id"] = self.user["id"]
            user_session["private_value"] = private_value

        cookie = self.client.get_cookie(app.config["SESSION_COOKIE_NAME"])

        self.assertIsNotNone(cookie)
        self.assertNotIn(private_value, cookie.value)
        with self.client.session_transaction() as user_session:
            self.assertEqual(user_session["private_value"], private_value)

    def test_authenticated_response_is_not_cached(self):
        self.sign_in()

        response = self.client.get("/")

        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Pragma"], "no-cache")

    def test_logout_clears_authenticated_session(self):
        with self.client.session_transaction() as user_session:
            user_session["user_id"] = self.user["id"]
            user_session["role"] = "customer"
            user_session["email"] = self.user["email"]
            user_session["pending_payment"] = {"sale_id": 9}

        response = self.client.post("/auth/logout")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["Location"])
        with self.client.session_transaction() as user_session:
            self.assertNotIn("user_id", user_session)
            self.assertNotIn("role", user_session)
            self.assertNotIn("email", user_session)
            self.assertNotIn("pending_payment", user_session)

    def test_profile_displays_authenticated_users_details(self):
        self.sign_in()
        connection = ProfileConnection(ProfileCursor(self.user))

        with patch(
            "auth.routes.get_db_connection",
            return_value=connection
        ):
            response = self.client.get("/auth/profile")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"customer@example.com", response.data)
        self.assertIn(b"My Profile", response.data)

    def test_profile_updates_only_the_session_account(self):
        self.sign_in()
        cursor = ProfileCursor(self.user)
        connection = ProfileConnection(cursor)

        with patch(
            "auth.routes.get_db_connection",
            return_value=connection
        ):
            response = self.client.post(
                "/auth/profile",
                data={
                    "name": "Updated Customer",
                    "email": "updated@example.com",
                    "current_password": "current-password",
                    "new_password": "",
                    "confirm_password": ""
                }
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(connection.commits, 1)
        update_query, update_values = cursor.statements[-1]
        self.assertIn("UPDATE tbl_users", update_query)
        self.assertEqual(
            update_values,
            (
                "Updated Customer",
                "updated@example.com",
                self.user["password"],
                None,
                self.user["id"]
            )
        )

    def test_profile_photo_replaces_only_the_session_users_photo(self):
        self.sign_in()
        old_image = "uploads/profiles/old-photo.png"
        new_image = "uploads/profiles/new-photo.png"
        profile_user = {**self.user, "profile_image_path": old_image}
        cursor = ProfileCursor(profile_user)
        connection = ProfileConnection(cursor)

        with patch(
            "auth.routes.get_db_connection",
            return_value=connection
        ), patch(
            "auth.routes.save_profile_image",
            return_value=new_image
        ) as save_image, patch(
            "auth.routes.delete_profile_image"
        ) as delete_image:
            response = self.client.post(
                "/auth/profile",
                data={
                    "name": "Aqua Customer",
                    "email": "customer@example.com",
                    "current_password": "current-password",
                    "new_password": "",
                    "confirm_password": "",
                    "profile_image": (BytesIO(b"image data"), "avatar.png")
                },
                content_type="multipart/form-data"
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(connection.commits, 1)
        save_image.assert_called_once()
        delete_image.assert_called_once_with(old_image)
        self.assertEqual(cursor.statements[-1][1][-2], new_image)


if __name__ == "__main__":
    unittest.main()
