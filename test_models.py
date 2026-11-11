import unittest

from models import Product, User


class UserEntityTests(unittest.TestCase):

    def test_password_is_hashed_and_can_be_verified(self):
        user = User.from_password(
            "  Aqua Track  ",
            " CUSTOMER@example.com ",
            "customer",
            "secure-password"
        )

        self.assertEqual(user.name, "Aqua Track")
        self.assertEqual(user.email, "customer@example.com")
        self.assertEqual(user.role, "customer")
        self.assertNotEqual(
            user.password_hash_for_storage(),
            "secure-password"
        )
        self.assertTrue(user.verify_password("secure-password"))
        self.assertFalse(user.verify_password("wrong-password"))


class ProductEntityTests(unittest.TestCase):

    def test_product_tracks_stock_and_availability(self):
        product = Product.from_form(
            "  Guppy ",
            " Fish ",
            "12.50",
            "4",
            "2",
            "10"
        )

        self.assertEqual(product.status, "Available")
        self.assertEqual(
            product.stock_values(),
            (product.price, 4, 2, 10)
        )

    def test_product_rejects_price_precision_over_two_decimal_places(self):
        with self.assertRaises(ValueError):
            Product.from_form(
                "Guppy",
                "Fish",
                "12.501",
                "4",
                "2"
            )

    def test_product_rejects_maximum_below_minimum_stock(self):
        with self.assertRaises(ValueError):
            Product.from_form(
                "Guppy",
                "Fish",
                "12.50",
                "4",
                "5",
                "3"
            )


if __name__ == "__main__":
    unittest.main()
