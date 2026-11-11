import logging
import secrets

import mysql.connector
from mysql.connector import Error

from config import Config


logger = logging.getLogger(__name__)


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db_connection():
    """Create and return a MySQL database connection."""

    try:
        connection = mysql.connector.connect(
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE,
            charset="utf8mb4",
            use_unicode=True,
            connection_timeout=10
        )

        return connection

    except Error:
        logger.exception("Database connection failed.")
        raise


def get_product_primary_key_column(cursor):
    """Return the product primary-key column used by the connected database."""

    cursor.execute("""
        SELECT COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tbl_products'
          AND CONSTRAINT_NAME = 'PRIMARY'
    """)
    row = cursor.fetchone()

    if isinstance(row, dict):
        column_name = row.get("COLUMN_NAME")
    else:
        column_name = row[0] if row else None

    if column_name not in {"id", "product_id"}:
        raise RuntimeError(
            "The tbl_products primary key must be named id or product_id."
        )

    return column_name


# ==========================================
# CUSTOM ID CONFIGURATION
# ==========================================

CUSTOM_ID_CONFIG = {
    "tbl_users": ("user_code", (2, 5)),
    "tbl_products": ("product_code", (3, 4)),
    "tbl_sales": ("order_code", (4, 3)),
    "tbl_payments": ("payment_code", (2, 2, 3)),
    "tbl_daily_catalog": ("catalog_code", (5, 2)),
    "tbl_stock_history": ("stock_code", (1, 3, 3)),
    "tbl_inventory_losses": ("loss_code", (3, 2, 3)),
    "tbl_sale_items": ("item_code", (2, 3, 2)),
    "tbl_email_otps": ("otp_code", (4, 2, 1)),
}


# ==========================================
# CUSTOM ID GENERATOR
# ==========================================

def generate_custom_code(cursor, table_name):
    """
    Generate a unique custom ID based on the
    configured table and segment lengths.
    """

    if table_name not in CUSTOM_ID_CONFIG:
        raise ValueError(
            f"Unsupported table name: {table_name}"
        )

    column_name, segments = CUSTOM_ID_CONFIG[table_name]

    max_attempts = 100

    for _ in range(max_attempts):

        code_parts = [
            str(secrets.randbelow(10 ** length)).zfill(length)
            for length in segments
        ]

        generated_code = "-".join(code_parts)

        query = (
            f"SELECT 1 FROM `{table_name}` "
            f"WHERE `{column_name}` = %s "
            f"LIMIT 1"
        )

        cursor.execute(query, (generated_code,))

        if cursor.fetchone() is None:
            return generated_code

    raise RuntimeError(
        f"Unable to generate a unique code for {table_name} "
        f"after {max_attempts} attempts."
    )