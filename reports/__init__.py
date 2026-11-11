from flask import Blueprint

reports_blueprint = Blueprint(
    "reports",
    __name__,
    url_prefix="/reports"
)

from . import routes