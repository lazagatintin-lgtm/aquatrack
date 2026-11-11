from flask import Blueprint


customer_blueprint = Blueprint(
    "customer",
    __name__,
    url_prefix="/customer"
)


from . import routes