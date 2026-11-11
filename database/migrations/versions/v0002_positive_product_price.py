from database.migrations.helpers import (
    check_clause,
    constraint_exists
)


def upgrade(cursor):
    cursor.execute("""
        SELECT COUNT(*)
        FROM tbl_products
        WHERE price <= 0
    """)
    if cursor.fetchone()[0]:
        raise RuntimeError(
            "Zero-priced products exist. Assign a positive price to each "
            "product before applying the positive-price constraint."
        )

    constraint_name = "chk_products_price"
    if constraint_exists(cursor, "tbl_products", constraint_name):
        existing_clause = check_clause(
            cursor,
            "tbl_products",
            constraint_name
        )
        normalized_clause = (
            str(existing_clause or "")
            .replace("`", "")
            .replace("(", "")
            .replace(")", "")
            .replace(" ", "")
            .lower()
        )
        if "price>0" in normalized_clause:
            return

        cursor.execute(
            "ALTER TABLE tbl_products "
            "DROP CHECK chk_products_price"
        )

    cursor.execute("""
        ALTER TABLE tbl_products
        ADD CONSTRAINT chk_products_price
        CHECK (price > 0)
    """)
