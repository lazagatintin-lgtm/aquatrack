from flask import Blueprint

inventory_blueprint = Blueprint(
    "inventory",
    __name__,
    url_prefix="/inventory"
)

from . import routes