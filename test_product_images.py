import os
import unittest
from io import BytesIO
from pathlib import Path

from flask import session

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

from werkzeug.datastructures import FileStorage

from app import app
from admin.routes import (
    record_product_stock_change,
    validate_product_values
)
from database.db import get_product_primary_key_column
from utils.product_images import (
    MAX_PRODUCT_IMAGE_SIZE,
    MAX_PROFILE_IMAGE_SIZE,
    delete_product_image,
    delete_profile_image,
    save_product_image,
    save_profile_image
)


class FakeStockCursor:

    def __init__(self, columns):
        self.columns = columns
        self.statements = []

    def execute(self, query, parameters=None):
        self.statements.append((query, parameters))

    def fetchall(self):
        return [(column,) for column in self.columns]

    def fetchone(self):
        return None


class ProductImageTests(unittest.TestCase):

    def test_product_stock_levels_allow_optional_maximum(self):
        values = validate_product_values(
            "Goldfish",
            "Fish",
            "10.00",
            "7",
            "5",
            "12"
        )

        self.assertEqual(values[1:], (7, 5, 12))

        without_maximum = validate_product_values(
            "Goldfish",
            "Fish",
            "10.00",
            "0",
            "5"
        )
        self.assertIsNone(without_maximum[3])

    def test_product_maximum_must_not_be_below_minimum(self):
        with self.assertRaisesRegex(ValueError, "valid product values"):
            validate_product_values(
                "Goldfish",
                "Fish",
                "10.00",
                "7",
                "5",
                "4"
            )

    def test_product_price_must_be_chargeable_and_fit_database_column(self):
        for price in ("0", "100000000.00"):
            with self.subTest(price=price):
                with self.assertRaisesRegex(
                    ValueError,
                    "valid product values"
                ):
                    validate_product_values(
                        "Goldfish",
                        "Fish",
                        price,
                        "7",
                        "5"
                    )

    def test_saves_and_deletes_a_png_upload(self):
        upload = FileStorage(
            stream=BytesIO(b"\x89PNG\r\n\x1a\nPNG payload"),
            filename="fish.png",
            content_type="image/png"
        )

        with app.app_context():
            relative_path = save_product_image(upload)
            full_path = Path(app.static_folder) / relative_path
            try:
                self.assertTrue(relative_path.startswith("uploads/products/"))
                self.assertEqual(full_path.suffix, ".png")
                self.assertTrue(full_path.is_file())
            finally:
                delete_product_image(relative_path)

            self.assertFalse(full_path.exists())

    def test_rejects_non_image_upload(self):
        upload = FileStorage(
            stream=BytesIO(b"not an image"),
            filename="fish.txt",
            content_type="text/plain"
        )

        with app.app_context():
            with self.assertRaisesRegex(ValueError, "valid JPG, PNG, or WebP"):
                save_product_image(upload)

    def test_rejects_upload_larger_than_limit(self):
        upload = FileStorage(
            stream=BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_PRODUCT_IMAGE_SIZE),
            filename="large.png",
            content_type="image/png"
        )

        with app.app_context():
            with self.assertRaisesRegex(ValueError, "must not exceed 5 MB"):
                save_product_image(upload)

    def test_saves_and_deletes_a_profile_photo(self):
        upload = FileStorage(
            stream=BytesIO(b"\x89PNG\r\n\x1a\nPNG payload"),
            filename="avatar.png",
            content_type="image/png"
        )

        with app.app_context():
            relative_path = save_profile_image(upload)
            full_path = Path(app.static_folder) / relative_path
            try:
                self.assertTrue(relative_path.startswith("uploads/profiles/"))
                self.assertTrue(full_path.is_file())
            finally:
                delete_profile_image(relative_path)

            self.assertFalse(full_path.exists())

    def test_rejects_profile_photo_larger_than_five_megabytes(self):
        upload = FileStorage(
            stream=BytesIO(
                b"\x89PNG\r\n\x1a\n" + b"x" * MAX_PROFILE_IMAGE_SIZE
            ),
            filename="large-avatar.png",
            content_type="image/png"
        )

        with app.app_context():
            with self.assertRaisesRegex(ValueError, "must not exceed 5 MB"):
                save_profile_image(upload)

    def test_admin_add_product_form_accepts_image_uploads(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False
        )
        client = app.test_client()
        with client.session_transaction() as user_session:
            user_session["user_id"] = 1
            user_session["role"] = "admin"

        response = client.get("/admin/products/add")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'enctype="multipart/form-data"', response.data)
        self.assertIn(b'name="product_image"', response.data)
        self.assertIn(b'name="max_stock"', response.data)

    def test_product_stock_history_supports_both_database_layouts(self):
        layouts = (
            (
                {
                    "stock_code", "product_id", "change_type",
                    "previous_quantity", "changed_quantity",
                    "new_quantity", "reason"
                },
                ("change_type", "changed_quantity")
            ),
            (
                {
                    "stock_code", "product_id", "user_id",
                    "transaction_type", "quantity",
                    "previous_quantity", "new_quantity", "reason"
                },
                ("transaction_type", "quantity")
            )
        )

        with app.test_request_context("/"):
            session["user_id"] = 7
            for columns, expected_fields in layouts:
                cursor = FakeStockCursor(columns)
                record_product_stock_change(
                    cursor,
                    12,
                    "Stock In",
                    0,
                    6,
                    6,
                    "Test stock"
                )
                insert_query, values = cursor.statements[-1]
                self.assertIn(expected_fields[0], insert_query)
                self.assertIn(expected_fields[1], insert_query)
                self.assertEqual(values[1], 12)


if __name__ == "__main__":
    unittest.main()
