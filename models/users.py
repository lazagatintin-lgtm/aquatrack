from werkzeug.security import check_password_hash, generate_password_hash

from .base import BaseEntity


class User(BaseEntity):
    """An AquaTrack account. The password hash is private (encapsulation)."""

    ROLE = None
    DASHBOARD_ENDPOINT = "auth.login"

    def __init__(
        self,
        name,
        email,
        role,
        password_hash,
        entity_id=None,
        code=None
    ):
        super().__init__(entity_id, code)
        self._name = (name or "").strip()
        self._email = (email or "").strip().lower()
        self._role = role
        self.__password_hash = password_hash
        self.validate()

    # ---------- construction ----------

    @staticmethod
    def class_for_role(role):
        """Pick the subclass that matches a role (factory helper)."""
        return {
            Customer.ROLE: Customer,
            Admin.ROLE: Admin
        }.get(role, User)

    @classmethod
    def from_password(cls, name, email, role, password):
        return User.class_for_role(role)(
            name,
            email,
            role,
            generate_password_hash(password)
        )

    @classmethod
    def from_row(cls, row):
        return User.class_for_role(row["role"])(
            row["name"],
            row["email"],
            row["role"],
            row["password"],
            entity_id=row.get("id"),
            code=row.get("user_code")
        )

    # ---------- read-only attributes ----------

    @property
    def name(self):
        return self._name

    @property
    def email(self):
        return self._email

    @property
    def role(self):
        return self._role

    @property
    def dashboard_endpoint(self):
        """Flask endpoint of this user's dashboard (polymorphic)."""
        return self.DASHBOARD_ENDPOINT

    def can_manage_inventory(self):
        return False

    # ---------- behaviour ----------

    def validate(self):
        if not self._name:
            raise ValueError("Name is required.")
        if "@" not in self._email:
            raise ValueError("A valid email address is required.")

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


class Customer(User):
    """A shopper who browses the catalog and places orders."""

    ROLE = "customer"
    DASHBOARD_ENDPOINT = "customer.dashboard"


class Admin(User):
    """The shop owner who manages products, stock and reports."""

    ROLE = "admin"
    DASHBOARD_ENDPOINT = "admin.dashboard"

    def can_manage_inventory(self):
        return True