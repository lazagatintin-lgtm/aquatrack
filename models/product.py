from decimal import Decimal, InvalidOperation

from .base import BaseEntity


class Product(BaseEntity):
    """An inventory product that protects its own stock level.

    ``quantity`` can only change through ``add_stock`` / ``remove_stock``,
    so it can never become negative (encapsulation).
    """

    MAX_PRICE = Decimal("99999999.99")
    MAX_QUANTITY = 2147483647

    def __init__(
        self,
        name,
        category,
        price,
        quantity,
        min_stock,
        max_stock=None,
        entity_id=None,
        code=None
    ):
        super().__init__(entity_id, code)
        self._name = name.strip()
        self._category = category.strip()
        self._price = Decimal(str(price))
        self._quantity = int(quantity)
        self._min_stock = int(min_stock)
        self._max_stock = (
            int(max_stock)
            if max_stock is not None
            else None
        )
        self.validate()

    # ---------- construction ----------

    @classmethod
    def from_form(
        cls,
        name,
        category,
        price_input,
        quantity_input,
        min_stock_input,
        max_stock_input=""
    ):
        name = (name or "").strip()
        category = (category or "").strip()
        if not name or not category:
            raise ValueError("Product name and category are required.")
        if len(name) > 100:
            raise ValueError("Product name must not exceed 100 characters.")
        if len(category) > 50:
            raise ValueError("Category must not exceed 50 characters.")

        try:
            max_stock_text = str(max_stock_input or "").strip()
            return cls(
                name,
                category,
                Decimal(str(price_input)),
                int(quantity_input),
                int(min_stock_input),
                int(max_stock_text) if max_stock_text else None
            )
        except (
            InvalidOperation,
            TypeError,
            ValueError,
            OverflowError
        ) as error:
            raise ValueError("Please enter valid product values.") from error

    @classmethod
    def from_row(cls, row):
        """Build a product from a dictionary database row."""
        return cls(
            row["product_name"],
            row["category"],
            row["price"],
            row["quantity"],
            row["min_stock"],
            row.get("max_stock"),
            entity_id=row.get("id"),
            code=row.get("product_code")
        )

    # ---------- read-only attributes ----------

    @property
    def name(self):
        return self._name

    @property
    def category(self):
        return self._category

    @property
    def price(self):
        return self._price

    @property
    def quantity(self):
        return self._quantity

    @property
    def min_stock(self):
        return self._min_stock

    @property
    def max_stock(self):
        return self._max_stock

    # ---------- validation ----------

    def validate(self):
        if (
            not self._price.is_finite()
            or self._price <= 0
            or self._price > self.MAX_PRICE
            or self._price.as_tuple().exponent < -2
            or self._quantity < 0
            or self._min_stock < 0
            or self._quantity > self.MAX_QUANTITY
            or self._min_stock > self.MAX_QUANTITY
            or (
                self._max_stock is not None
                and (
                    self._max_stock < self._min_stock
                    or self._max_stock > self.MAX_QUANTITY
                )
            )
        ):
            raise ValueError("Please enter valid product values.")

    # ---------- stock behaviour ----------

    @staticmethod
    def status_for(quantity):
        return "Available" if quantity > 0 else "Unavailable"

    @property
    def status(self):
        return self.status_for(self._quantity)

    def add_stock(self, amount):
        amount = self._check_amount(amount)
        if self._quantity + amount > self.MAX_QUANTITY:
            raise ValueError("The stock quantity is too large.")
        self._quantity += amount
        return self._quantity

    def remove_stock(self, amount):
        amount = self._check_amount(amount)
        if amount > self._quantity:
            raise ValueError(
                "The entered quantity cannot exceed the available stock."
            )
        self._quantity -= amount
        return self._quantity

    @staticmethod
    def _check_amount(amount):
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError("Please enter a valid quantity.")
        return amount

    def is_out_of_stock(self):
        return self._quantity == 0

    def is_low_stock(self):
        return 0 < self._quantity <= self._min_stock

    def is_over_stock(self):
        return (
            self._max_stock is not None
            and self._quantity > self._max_stock
        )

    def excess_units(self):
        if not self.is_over_stock():
            return 0
        return self._quantity - self._max_stock

    def inventory_value(self):
        return self._price * self._quantity

    def stock_values(self):
        return (
            self._price,
            self._quantity,
            self._min_stock,
            self._max_stock
        )