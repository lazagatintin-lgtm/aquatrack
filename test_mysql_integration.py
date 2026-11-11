import os
import unittest

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

import mysql.connector

from config import Config


TEST_DATABASE = os.getenv("AQUATRACK_TEST_DATABASE", "").strip()


@unittest.skipUnless(
    TEST_DATABASE,
    "Set AQUATRACK_TEST_DATABASE to run read-only MySQL integration checks."
)
class MySQLSchemaIntegrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if (
            not TEST_DATABASE.startswith("aquatrack_test_")
            or TEST_DATABASE == Config.MYSQL_DATABASE
        ):
            raise RuntimeError(
                "AQUATRACK_TEST_DATABASE must be a dedicated "
                "aquatrack_test_* database and differ from MYSQL_DATABASE."
            )

        cls.connection = mysql.connector.connect(
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=TEST_DATABASE,
            charset="utf8mb4",
            use_unicode=True,
            connection_timeout=10
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "connection", None) is not None:
            cls.connection.close()

    def test_migrations_and_expected_runtime_columns_exist(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute("""
                SELECT TABLE_NAME
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
            """)
            tables = {row[0] for row in cursor.fetchall()}

            required_tables = {
                "tbl_schema_migrations",
                "tbl_login_rate_limits",
                "tbl_products",
                "tbl_email_otps",
                "tbl_stock_history",
                "tbl_sales",
                "tbl_payments"
            }
            self.assertTrue(
                required_tables.issubset(tables),
                f"Missing tables: {sorted(required_tables - tables)}"
            )

            cursor.execute("""
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'tbl_products'
            """)
            product_columns = {row[0] for row in cursor.fetchall()}
            self.assertTrue(
                {"price", "quantity", "min_stock", "max_stock"}
                .issubset(product_columns)
            )

            cursor.execute("""
                SELECT 1
                FROM tbl_email_otps
                WHERE user_id = %s
                  AND purpose = %s
                  AND is_used = 0
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """, (-1, "login"))
            self.assertIsNone(cursor.fetchone())
        finally:
            cursor.close()


if __name__ == "__main__":
    unittest.main()
