import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

import app as app_module
from app import app
from auth.rate_limit import (
    is_login_blocked,
    record_failed_login
)
from database.migrations import discover_migrations
from database.migrations.versions import v0002_positive_product_price
from werkzeug.security import generate_password_hash


class FakeRateLimitCursor:

    def __init__(self, blocked=False):
        self.blocked = blocked
        self.statements = []

    def execute(self, query, parameters=None):
        self.statements.append((query, parameters))

    def fetchone(self):
        return (int(self.blocked),)

    def close(self):
        pass


class FakeRateLimitConnection:

    def __init__(self, cursor):
        self.rate_cursor = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.rate_cursor

    def start_transaction(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def is_connected(self):
        return not self.closed

    def close(self):
        self.closed = True


class FakeMigrationCursor:

    def __init__(self, existing_clause=None, zero_price_count=0):
        self.existing_clause = existing_clause
        self.zero_price_count = zero_price_count
        self.statements = []

    def execute(self, query, parameters=None):
        self.statements.append((query, parameters))

    def fetchone(self):
        query = self.statements[-1][0]
        if "SELECT COUNT(*)" in query:
            return (self.zero_price_count,)
        if "CHECK_CLAUSE" in query:
            return (self.existing_clause,) if self.existing_clause else None
        return (1,) if self.existing_clause else None


class OperationsTests(unittest.TestCase):

    def test_create_owner_checks_do_not_require_id_column(self):
        connection = Mock()
        connection.is_connected.return_value = True
        cursor = Mock()
        cursor.fetchone.return_value = None
        connection.cursor.return_value = cursor

        with patch.object(
            app_module,
            "get_db_connection",
            return_value=connection
        ):
            result = app.test_cli_runner().invoke(
                args=[
                    "create-owner",
                    "--name", "Test Owner",
                    "--email", "owner@example.com"
                ],
                input="test-password\ntest-password\n"
            )

        self.assertEqual(result.exit_code, 0, result.output)
        user_queries = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if "FROM tbl_users" in call.args[0]
        ]
        self.assertEqual(len(user_queries), 2)
        self.assertTrue(all("SELECT 1" in query for query in user_queries))

    def test_versioned_migrations_are_ordered(self):
        self.assertEqual(
            discover_migrations(),
            [
                "v0001_legacy_schema",
                "v0002_positive_product_price",
                "v0003_login_rate_limits",
                "v0004_staff_registration_approvals",
                "v0005_profile_photos"
            ]
        )

    def test_positive_price_migration_refuses_zero_price_products(self):
        cursor = FakeMigrationCursor(zero_price_count=2)

        with self.assertRaisesRegex(RuntimeError, "Zero-priced products"):
            v0002_positive_product_price.upgrade(cursor)

        self.assertEqual(len(cursor.statements), 1)

    def test_positive_price_migration_does_not_duplicate_current_check(self):
        cursor = FakeMigrationCursor(
            existing_clause="(`price` > 0)"
        )

        v0002_positive_product_price.upgrade(cursor)

        self.assertEqual(len(cursor.statements), 3)
        self.assertFalse(any(
            "ALTER TABLE" in query
            for query, _ in cursor.statements
        ))

    def test_migration_cli_reports_applied_versions(self):
        connection = Mock()
        connection.is_connected.return_value = True
        with patch.object(
            app_module,
            "get_db_connection",
            return_value=connection
        ), patch.object(
            app_module,
            "apply_migrations",
            return_value=["v0001_legacy_schema"]
        ):
            result = app.test_cli_runner().invoke(
                args=["migrate-database"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("v0001_legacy_schema", result.output)
        connection.close.assert_called_once()

    def test_login_blocking_uses_hashed_email_and_ip_keys(self):
        cursor = FakeRateLimitCursor(blocked=True)
        connection = FakeRateLimitConnection(cursor)

        with app.app_context(), patch(
            "auth.rate_limit.get_db_connection",
            return_value=connection
        ):
            blocked = is_login_blocked(
                "owner@example.com",
                "192.0.2.10"
            )

        self.assertTrue(blocked)
        query, parameters = cursor.statements[0]
        self.assertIn("bucket_hash IN", query)
        self.assertEqual(len(parameters[0]), 64)
        self.assertEqual(len(parameters[1]), 64)
        self.assertNotIn("owner@example.com", str(parameters))
        self.assertTrue(connection.closed)

    def test_login_route_stops_when_rate_limited(self):
        client = app.test_client()
        with patch(
            "auth.routes.is_login_blocked",
            return_value=True
        ), patch(
            "auth.routes.get_user_by_email"
        ) as get_user:
            response = client.post(
                "/auth/login",
                data={
                    "email": "owner@example.com",
                    "password": "wrong-password"
                }
            )

        self.assertEqual(response.status_code, 302)
        get_user.assert_not_called()

    def test_failed_password_records_email_and_address_buckets(self):
        client = app.test_client()
        with patch(
            "auth.routes.is_login_blocked",
            return_value=False
        ), patch(
            "auth.routes.get_user_by_email",
            return_value={
                "id": 4,
                "email": "owner@example.com",
                "password": generate_password_hash("correct-password"),
                "role": "customer"
            }
        ), patch(
            "auth.routes.record_failed_login"
        ) as record:
            response = client.post(
                "/auth/login",
                data={
                    "email": "owner@example.com",
                    "password": "wrong-password"
                }
            )

        self.assertEqual(response.status_code, 302)
        record.assert_called_once_with("owner@example.com", "127.0.0.1")

    def test_failed_login_updates_email_and_ip_buckets(self):
        cursor = FakeRateLimitCursor()
        connection = FakeRateLimitConnection(cursor)

        with app.app_context(), patch(
            "auth.rate_limit.get_db_connection",
            return_value=connection
        ):
            record_failed_login(
                "owner@example.com",
                "192.0.2.10"
            )

        inserts = [
            item
            for item in cursor.statements
            if "INSERT INTO tbl_login_rate_limits" in item[0]
        ]
        self.assertEqual(len(inserts), 2)
        self.assertTrue(all(
            len(item[1][0]) == 64
            for item in inserts
        ))
        self.assertTrue(connection.committed)
        self.assertTrue(connection.closed)

    def test_config_cli_does_not_print_secret_value(self):
        runner = app.test_cli_runner()
        result = runner.invoke(args=["check-config"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn(app.config["SECRET_KEY"], result.output)

    def test_mail_check_performs_smtp_noop_without_sending_message(self):
        smtp = Mock()
        smtp.noop.return_value = (250, b"OK")
        connection = Mock()
        connection.host = smtp
        context = Mock()
        context.__enter__ = Mock(return_value=connection)
        context.__exit__ = Mock(return_value=False)
        previous_config = {
            key: app.config.get(key)
            for key in ("MAIL_USERNAME", "MAIL_PASSWORD")
        }

        with patch.object(app_module, "mail") as mail_extension:
            mail_extension.connect.return_value = context
            app.config["MAIL_USERNAME"] = "test-user"
            app.config["MAIL_PASSWORD"] = "test-password"
            try:
                result = app.test_cli_runner().invoke(args=["check-mail"])
            finally:
                for key, value in previous_config.items():
                    app.config[key] = value

        self.assertEqual(result.exit_code, 0, result.output)
        smtp.noop.assert_called_once_with()
        connection.send.assert_not_called()

    def test_inventory_reconciliation_is_admin_only_and_read_only(self):
        cursor = Mock()
        cursor.fetchall.return_value = [{
            "product_code": "P-001",
            "product_name": "Goldfish",
            "current_quantity": 8,
            "latest_recorded_quantity": 6,
            "latest_movement_at": None,
            "issue": "Quantity mismatch"
        }]
        connection = Mock()
        connection.cursor.return_value = cursor
        connection.is_connected.return_value = True
        client = app.test_client()

        with client.session_transaction() as user_session:
            user_session["user_id"] = 1
            user_session["role"] = "admin"

        with patch(
            "admin.routes.get_db_connection",
            return_value=connection
        ):
            response = client.get("/admin/inventory-reconciliation")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Goldfish", response.data)
        self.assertIn(b"Quantity mismatch", response.data)
        query = cursor.execute.call_args.args[0]
        self.assertIn("latest_recorded_quantity", query)
        self.assertNotIn("UPDATE tbl_products", query)
        self.assertNotIn("DELETE FROM", query)


if __name__ == "__main__":
    unittest.main()
