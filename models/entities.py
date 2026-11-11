from decimal import Decimal, InvalidOperation

from werkzeug.security import check_password_hash, generate_password_hash


class User:
    """Encapsulate an AquaTrack user account and password operations."""

    def __init__(self, name, email, role, password_hash):
        self._name = name.strip()
        self._email = email.strip().lower()
        self._role = role
        self.__password_hash = password_hash

    @classmethod
    def from_password(cls, name, email, role, password):
        return cls(
            name,
            email,
            role,
            generate_password_hash(password)
        )

    @classmethod
    def from_row(cls, row):
        return cls(
            row["name"],
            row["email"],
            row["role"],
            row["password"]
        )

    @property
    def name(self):
        return self._name

    @property
    def email(self):
        return self._email

    @property
    def role(self):
        return self._role

    def verify_password(self, password):
        return check_password_hash(self.__password_hash, password)

    def insert_values(self, user_code):
        return (
            user_code,
            self.name,
            self.email,
            self.__password_hash,
            self.role
        )

    def password_hash_for_storage(self):
        return self.__password_hash


class Product:
    """Represent a validated inventory product."""

    MAX_PRICE = Decimal("99999999.99")
    MAX_QUANTITY = 2147483647

    def __init__(
        self,
        name,
        category,
        price,
        quantity,
        min_stock,
        max_stock=None
    ):
        self.name = name.strip()
        self.category = category.strip()
        self.price = Decimal(str(price))
        self.quantity = int(quantity)
        self.min_stock = int(min_stock)
        self.max_stock = (
            int(max_stock)
            if max_stock is not None
            else None
        )
        self.validate()

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
            raise ValueError(
                "Product name and category are required."
            )
        if len(name) > 100:
            raise ValueError(
                "Product name must not exceed 100 characters."
            )
        if len(category) > 50:
            raise ValueError(
                "Category must not exceed 50 characters."
            )

        try:
            price = Decimal(str(price_input))
            quantity = int(quantity_input)
            min_stock = int(min_stock_input)
            max_stock_text = str(max_stock_input or "").strip()
            max_stock = int(max_stock_text) if max_stock_text else None
            return cls(
                name,
                category,
                price,
                quantity,
                min_stock,
                max_stock
            )
        except (
            InvalidOperation,
            TypeError,
            ValueError,
            OverflowError
        ) as error:
            raise ValueError(
                "Please enter valid product values."
            ) from error

    def validate(self):
        if (
            not self.price.is_finite()
            or self.price <= 0
            or self.price > self.MAX_PRICE
            or self.price.as_tuple().exponent < -2
            or self.quantity < 0
            or self.min_stock < 0
            or self.quantity > self.MAX_QUANTITY
            or self.min_stock > self.MAX_QUANTITY
            or (
                self.max_stock is not None
                and (
                    self.max_stock < self.min_stock
                    or self.max_stock > self.MAX_QUANTITY
                )
            )
        ):
            raise ValueError("Please enter valid product values.")

    @property
    def status(self):
        return "Available" if self.quantity > 0 else "Unavailable"

    def stock_values(self):
        return self.price, self.quantity, self.min_stock, self.max_stock
