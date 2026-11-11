from decimal import Decimal, InvalidOperation


def clean_text(value):
    """Remove unnecessary spaces from text input."""

    if value is None:
        return ""

    return str(value).strip()


def is_valid_email(email):
    """Check whether an email has a basic valid format."""

    email = clean_text(email)

    if not email or " " in email:
        return False

    if email.count("@") != 1:
        return False

    username, domain = email.split("@")

    if not username or not domain:
        return False

    if "." not in domain:
        return False

    if domain.startswith(".") or domain.endswith("."):
        return False

    return True


def is_valid_quantity(value):
    """Check whether a quantity is a positive whole number."""

    try:
        quantity = int(value)
        return quantity > 0

    except (TypeError, ValueError):
        return False


def is_valid_non_negative_quantity(value):
    """Check whether a quantity is zero or a positive whole number."""

    try:
        quantity = int(value)
        return quantity >= 0

    except (TypeError, ValueError):
        return False


def is_valid_price(value):
    """Check whether a price is a valid non-negative amount."""

    try:
        price = Decimal(str(value))

        return (
            price.is_finite()
            and price >= Decimal("0.00")
        )

    except (InvalidOperation, TypeError, ValueError):
        return False


def format_currency(value):
    """Format a numeric amount as Philippine peso."""

    try:
        amount = Decimal(str(value))

        if not amount.is_finite():
            return "₱0.00"

        return f"₱{amount:,.2f}"

    except (InvalidOperation, TypeError, ValueError):
        return "₱0.00"