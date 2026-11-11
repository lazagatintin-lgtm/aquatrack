from database.migrations.helpers import (
    add_column_if_missing,
    ensure_legacy_code
)


def upgrade(cursor):
    cursor.execute("""
        SELECT DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tbl_payments'
          AND COLUMN_NAME = 'payment_method'
        LIMIT 1
    """)
    payment_method_type = cursor.fetchone()
    if payment_method_type and payment_method_type[0].lower() != "varchar":
        cursor.execute("""
            ALTER TABLE tbl_payments
            MODIFY COLUMN payment_method
                VARCHAR(50) NOT NULL DEFAULT 'Cash on Pickup'
        """)

    cursor.execute("""
        UPDATE tbl_payments
        SET payment_method = 'Cash on Pickup'
        WHERE payment_method = 'Cash'
    """)

    add_column_if_missing(
        cursor,
        "tbl_products",
        "image_path",
        "VARCHAR(255) DEFAULT NULL"
    )
    add_column_if_missing(
        cursor,
        "tbl_products",
        "max_stock",
        "INT DEFAULT NULL"
    )

    legacy_codes = (
        (
            "tbl_users", "user_code",
            "uq_users_user_code", "LEGACY-U-"
        ),
        (
            "tbl_products", "product_code",
            "uq_products_product_code", "LEGACY-P-"
        ),
        (
            "tbl_daily_catalog", "catalog_code",
            "uq_catalog_code", "LEGACY-C-"
        ),
        (
            "tbl_sales", "order_code",
            "uq_sales_order_code", "LEGACY-O-"
        ),
        (
            "tbl_payments", "payment_code",
            "uq_payments_payment_code", "LEGACY-PAY-"
        ),
        (
            "tbl_stock_history", "stock_code",
            "uq_stock_history_stock_code", "LEGACY-SH-"
        ),
        (
            "tbl_sale_items", "item_code",
            "uq_sale_items_item_code", "LEGACY-I-"
        ),
        (
            "tbl_inventory_losses", "loss_code",
            "uq_inventory_losses_loss_code", "LEGACY-L-"
        ),
        (
            "tbl_email_otps", "otp_code",
            "uq_email_otps_otp_code", "LEGACY-T-"
        )
    )

    for table_name, column_name, index_name, prefix in legacy_codes:
        ensure_legacy_code(
            cursor,
            table_name,
            column_name,
            index_name,
            prefix
        )

    cursor.execute("""
        SELECT COUNT(*)
        FROM tbl_products
        WHERE max_stock IS NOT NULL
          AND max_stock < min_stock
    """)
    if cursor.fetchone()[0]:
        raise RuntimeError(
            "Some products have max_stock below min_stock. "
            "Correct those rows before applying the max-stock constraint."
        )

    if not constraint_exists(
        cursor,
        "tbl_products",
        "chk_products_max_stock"
    ):
        cursor.execute("""
            ALTER TABLE tbl_products
            ADD CONSTRAINT chk_products_max_stock
            CHECK (max_stock IS NULL OR max_stock >= min_stock)
        """)
