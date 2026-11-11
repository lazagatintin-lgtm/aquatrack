import os
import re
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

from database.db import (
    CUSTOM_ID_CONFIG,
    generate_custom_code,
    get_product_primary_key_column
)


ROOT = Path(__file__).resolve().parent


class CodeGeneratorTests(unittest.TestCase):

    def test_generated_codes_match_configured_segment_lengths(self):
        cursor = Mock()
        cursor.fetchone.return_value = None

        for table_name, (column_name, segments) in CUSTOM_ID_CONFIG.items():
            with self.subTest(table=table_name):
                generated = generate_custom_code(cursor, table_name)
                self.assertEqual(
                    [len(segment) for segment in generated.split("-")],
                    list(segments)
                )
                self.assertTrue(
                    all(segment.isdigit() for segment in generated.split("-"))
                )
                self.assertIn(f"`{column_name}`", cursor.execute.call_args[0][0])

    def test_unsupported_table_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_custom_code(Mock(), "tbl_unlisted")

    def test_product_primary_key_supports_current_and_schema_sql_names(self):
        for result, expected in (
            (("product_id",), "product_id"),
            (("id",), "id")
        ):
            with self.subTest(column=expected):
                cursor = Mock()
                cursor.fetchone.return_value = result
                self.assertEqual(
                    get_product_primary_key_column(cursor),
                    expected
                )

    def test_unknown_product_primary_key_is_rejected(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("fish_id",)

        with self.assertRaises(RuntimeError):
            get_product_primary_key_column(cursor)


class SchemaConsistencyTests(unittest.TestCase):

    def test_all_generated_code_columns_exist_and_are_unique(self):
        schema = (ROOT / "database" / "schema.sql").read_text(
            encoding="utf-8"
        )

        table_for_code = {
            "user_code": "tbl_users",
            "product_code": "tbl_products",
            "order_code": "tbl_sales",
            "payment_code": "tbl_payments",
            "catalog_code": "tbl_daily_catalog",
            "stock_code": "tbl_stock_history",
            "loss_code": "tbl_inventory_losses",
            "item_code": "tbl_sale_items",
            "otp_code": "tbl_email_otps"
        }

        for column, table in table_for_code.items():
            with self.subTest(column=column):
                table_match = re.search(
                    rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\) ENGINE=InnoDB;",
                    schema,
                    flags=re.DOTALL
                )
                self.assertIsNotNone(table_match)
                definition = table_match.group(1)
                self.assertRegex(
                    definition,
                    rf"\b{column} VARCHAR\(20\) NOT NULL"
                )
                self.assertRegex(
                    definition,
                    rf"UNIQUE KEY [a-zA-Z0-9_]+ \({column}\)"
                )

        products_definition = re.search(
            r"CREATE TABLE IF NOT EXISTS tbl_products \((.*?)\) ENGINE=InnoDB;",
            schema,
            flags=re.DOTALL
        ).group(1)
        self.assertRegex(
            products_definition,
            r"\bimage_path VARCHAR\(255\) DEFAULT NULL"
        )
        self.assertRegex(
            products_definition,
            r"\bmax_stock INT DEFAULT NULL"
        )
        self.assertRegex(
            schema,
            r"CREATE TABLE IF NOT EXISTS tbl_login_rate_limits"
        )


if __name__ == "__main__":
    unittest.main()
