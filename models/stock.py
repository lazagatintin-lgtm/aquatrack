from abc import abstractmethod

from .base import BaseEntity


class StockMovement(BaseEntity):
    """A recorded change to a product's stock (abstract parent)."""

    CHANGE_TYPE = None
    MAX_REASON_LENGTH = 255

    def __init__(self, product_id, quantity, reason, entity_id=None, code=None):
        super().__init__(entity_id, code)
        self._product_id = product_id
        self._quantity = quantity
        self._reason = (reason or "").strip()
        self.validate()

    @property
    def product_id(self):
        return self._product_id

    @property
    def quantity(self):
        return self._quantity

    @property
    def reason(self):
        return self._reason

    @property
    def change_type(self):
        return self.CHANGE_TYPE

    @property
    def is_loss(self):
        return False

    def validate(self):
        if self._product_id is None or self._product_id <= 0:
            raise ValueError("Please select a valid product.")
        if self._quantity is None or self._quantity <= 0:
            raise ValueError("Please enter a valid quantity.")
        if not self._reason:
            raise ValueError("Please provide a reason.")
        if len(self._reason) > self.MAX_REASON_LENGTH:
            raise ValueError("Reason must not exceed 255 characters.")

    @abstractmethod
    def apply_to(self, product):
        """Change the product's stock and return the new quantity."""


class StockIn(StockMovement):
    CHANGE_TYPE = "Stock In"

    def apply_to(self, product):
        return product.add_stock(self._quantity)


class StockOut(StockMovement):
    CHANGE_TYPE = "Stock Out"

    def apply_to(self, product):
        return product.remove_stock(self._quantity)


class InventoryLoss(StockOut):
    """Stock that disappeared (missing, dead, damaged).

    It reduces stock like a Stock Out but is also logged as a loss.
    """

    @property
    def is_loss(self):
        return True