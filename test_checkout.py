import os
import unittest
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

from flask import session

from app import app
from customer.routes import get_product_ids, get_valid_cart
from payment.routes import ONLINE_PAYMENT_METHODS, PAYMENT_METHODS


ROOT = Path(__file__).resolve().parent


class CustomerCartTests(unittest.TestCase):

    def test_only_cash_and_gcash_are_available_payment_methods(self):
        self.assertEqual(
            PAYMENT_METHODS,
            {"Cash on Pickup", "GCash"}
        )
        self.assertEqual(ONLINE_PAYMENT_METHODS, {"GCash"})

    def setUp(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=True
        )
        self.client = app.test_client()

    def test_cart_discards_invalid_product_ids_and_quantities(self):
        with app.test_request_context("/"):
            session["cart"] = {
                "2": "3",
                "0": "4",
                "-1": "2",
                "bad": "1",
                "4": "0",
                "5": "-2",
                "6": "not-a-number"
            }

            self.assertEqual(
                get_valid_cart(),
                {"2": 3}
            )

    def test_product_ids_are_converted_to_integers(self):
        self.assertEqual(
            get_product_ids({"2": 3, "8": 1}),
            (2, 8)
        )

    def test_customer_pages_redirect_anonymous_visitors(self):
        response = self.client.get("/customer/checkout")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["Location"])

    def test_post_rejects_missing_csrf_token(self):
        response = self.client.post("/customer/place-order")

        self.assertEqual(response.status_code, 400)

    def test_customer_stylesheets_exist_at_their_template_urls(self):
        stylesheet_paths = {
            "catalog.html": "css/catalog.css",
            "checkout.html": "css/checkout.css"
        }

        for template_name, stylesheet_path in stylesheet_paths.items():
            with self.subTest(template=template_name):
                template = (
                    ROOT / "templates" / "customer" / template_name
                ).read_text(encoding="utf-8")
                stylesheet = ROOT / "static" / stylesheet_path

                self.assertIn(
                    f"filename='{stylesheet_path}'",
                    template
                )
                self.assertTrue(stylesheet.is_file())

    def test_request_size_limit_allows_two_payment_proofs(self):
        self.assertEqual(
            app.config["MAX_CONTENT_LENGTH"],
            11 * 1024 * 1024
        )


if __name__ == "__main__":
    unittest.main()
