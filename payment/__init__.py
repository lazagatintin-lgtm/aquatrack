from flask import Blueprint

payment_blueprint = Blueprint(
    "payment",
    __name__,
    url_prefix="/payment"
)

from . import routes