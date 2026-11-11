from flask import Blueprint

analytics_blueprint = Blueprint(
    "analytics",
    __name__,
    url_prefix="/analytics"
)

from . import routes