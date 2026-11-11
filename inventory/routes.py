import mysql.connector

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    current_app
)

from . import inventory_blueprint
from database.db import (
    get_db_connection,
    generate_custom_code
)


# ADMIN ACCESS PROTECTION
@inventory_blueprint.before_request
def require_admin():

    if (
        not session.get("user_id")
        or session.get("role") != "admin"
    ):
        flash(
            "You must be logged in as an administrator to access this page.",
            "danger"
        )

        return redirect(url_for("auth.login"))


# DATABASE CLEANUP
def close_database(connection, cursor):

    if cursor is not None:
        try:
            cursor.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "DATABASE CURSOR CLOSE ERROR"
            )

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "DATABASE CONNECTION CLOSE ERROR"
            )


# SAFE DATABASE ROLLBACK
def rollback_database(connection):

    if connection is not None:
        try:
            connection.rollback()
        except mysql.connector.Error:
            current_app.logger.exception(
                "DATABASE ROLLBACK ERROR"
            )


# UPDATE TODAY'S DAILY CATALOG
def update_daily_catalog_quantity(
    cursor,
    product_id,
    quantity,
    operation
):
    if operation not in ("in", "out"):
        raise ValueError("Invalid stock operation.")

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    # GET ACTUAL PRODUCT QUANTITY
    cursor.execute("""
        SELECT quantity
        FROM tbl_products
        WHERE id = %s
    """, (product_id,))

    product = cursor.fetchone()

    if not product:
        raise ValueError("Product not found.")

    actual_quantity = int(product["quantity"])

    # LOCK TODAY'S CATALOG RECORD
    cursor.execute("""
        SELECT
            id,
            available_quantity
        FROM tbl_daily_catalog
        WHERE product_id = %s
          AND catalog_date = CURDATE()
        FOR UPDATE
    """, (product_id,))

    catalog = cursor.fetchone()

    # Do not automatically create a catalog record.
    if not catalog:
        return

    current_quantity = int(
        catalog["available_quantity"]
    )

    if current_quantity < 0:
        raise ValueError(
            "Invalid daily catalog quantity."
        )

    if operation == "in":

        new_catalog_quantity = min(
            current_quantity + quantity,
            actual_quantity
        )

    else:

        new_catalog_quantity = min(
            max(0, current_quantity - quantity),
            actual_quantity
        )

    cursor.execute("""
        UPDATE tbl_daily_catalog
        SET available_quantity = %s
        WHERE id = %s
    """, (
        new_catalog_quantity,
        catalog["id"]
    ))


# VALIDATE STOCK FORM
def validate_stock_form():

    product_id = request.form.get(
        "product_id",
        type=int
    )

    quantity = request.form.get(
        "quantity",
        type=int
    )

    reason = request.form.get(
        "reason",
        ""
    ).strip()

    if product_id is None or product_id <= 0:
        raise ValueError(
            "Please select a valid product."
        )

    if quantity is None or quantity <= 0:
        raise ValueError(
            "Please enter a valid quantity."
        )

    if not reason:
        raise ValueError(
            "Please provide a reason."
        )

    if len(reason) > 255:
        raise ValueError(
            "Reason must not exceed 255 characters."
        )

    return product_id, quantity, reason


# LOAD PRODUCTS FOR STOCK FORMS
def get_inventory_products():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                product_name,
                quantity
            FROM tbl_products
            ORDER BY product_name ASC
        """)

        return cursor.fetchall()

    finally:
        close_database(connection, cursor)


# STOCK IN
@inventory_blueprint.route(
    "/stock-in",
    methods=["GET", "POST"]
)
def stock_in():

    if request.method == "POST":

        try:
            product_id, quantity, reason = validate_stock_form()

        except ValueError as error:
            flash(str(error), "error")

            return redirect(
                url_for("inventory.stock_in")
            )

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            connection.start_transaction()

            # LOCK PRODUCT RECORD
            cursor.execute("""
                SELECT
                    id,
                    quantity
                FROM tbl_products
                WHERE id = %s
                FOR UPDATE
            """, (product_id,))

            product = cursor.fetchone()

            if not product:
                raise ValueError("Product not found.")

            previous_quantity = int(
                product["quantity"]
            )

            if previous_quantity < 0:
                raise ValueError(
                    "The product has an invalid stock quantity."
                )

            new_quantity = previous_quantity + quantity

            new_status = (
                "Available"
                if new_quantity > 0
                else "Unavailable"
            )

            # UPDATE ACTUAL PRODUCT STOCK
            cursor.execute("""
                UPDATE tbl_products
                SET quantity = %s,
                    status = %s
                WHERE id = %s
            """, (
                new_quantity,
                new_status,
                product_id
            ))

            # UPDATE TODAY'S CATALOG IF IT EXISTS
            update_daily_catalog_quantity(
                cursor,
                product_id,
                quantity,
                "in"
            )

            # GENERATE CUSTOM STOCK HISTORY CODE
            stock_code = generate_custom_code(
                cursor,
                "tbl_stock_history"
            )

            # RECORD STOCK HISTORY
            cursor.execute("""
                INSERT INTO tbl_stock_history
                (
                    stock_code,
                    product_id,
                    change_type,
                    previous_quantity,
                    changed_quantity,
                    new_quantity,
                    reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                stock_code,
                product_id,
                "Stock In",
                previous_quantity,
                quantity,
                new_quantity,
                reason
            ))

            connection.commit()

            flash(
                "Stock added successfully!",
                "success"
            )

            return redirect(
                url_for("inventory.stock_in")
            )

        except ValueError as error:

            rollback_database(connection)

            flash(str(error), "error")

        except Exception:

            rollback_database(connection)

            current_app.logger.exception(
                "STOCK IN ERROR"
            )

            flash(
                "Unable to add stock. Please try again.",
                "error"
            )

        finally:
            close_database(connection, cursor)

        return redirect(
            url_for("inventory.stock_in")
        )

    try:
        products = get_inventory_products()

        return render_template(
            "admin/stock_in.html",
            products=products
        )

    except Exception:

        current_app.logger.exception(
            "LOAD STOCK IN ERROR"
        )

        flash(
            "Unable to load stock products.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )


# SHARED STOCK REDUCTION PROCESS
def process_stock_reduction(
    product_id,
    quantity,
    reason,
    is_inventory_loss=False
):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        connection.start_transaction()

        # LOCK PRODUCT BEFORE DEDUCTING STOCK
        cursor.execute("""
            SELECT
                id,
                quantity
            FROM tbl_products
            WHERE id = %s
            FOR UPDATE
        """, (product_id,))

        product = cursor.fetchone()

        if not product:
            raise ValueError("Product not found.")

        previous_quantity = int(
            product["quantity"]
        )

        if previous_quantity < 0:
            raise ValueError(
                "The product has an invalid stock quantity."
            )

        if quantity > previous_quantity:
            raise ValueError(
                "The entered quantity cannot exceed the available stock."
            )

        new_quantity = previous_quantity - quantity

        new_status = (
            "Available"
            if new_quantity > 0
            else "Unavailable"
        )

        # DEDUCT ACTUAL PRODUCT STOCK
        cursor.execute("""
            UPDATE tbl_products
            SET quantity = %s,
                status = %s
            WHERE id = %s
        """, (
            new_quantity,
            new_status,
            product_id
        ))

        # UPDATE TODAY'S CATALOG IF IT EXISTS
        update_daily_catalog_quantity(
            cursor,
            product_id,
            quantity,
            "out"
        )

        # GENERATE CUSTOM STOCK HISTORY CODE
        stock_code = generate_custom_code(
            cursor,
            "tbl_stock_history"
        )

        # RECORD STOCK MOVEMENT
        cursor.execute("""
            INSERT INTO tbl_stock_history
            (
                stock_code,
                product_id,
                change_type,
                previous_quantity,
                changed_quantity,
                new_quantity,
                reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            stock_code,
            product_id,
            "Stock Out",
            previous_quantity,
            quantity,
            new_quantity,
            reason
        ))

        # RECORD INVENTORY LOSS SEPARATELY
        if is_inventory_loss:

            # GENERATE CUSTOM INVENTORY LOSS CODE
            loss_code = generate_custom_code(
                cursor,
                "tbl_inventory_losses"
            )

            cursor.execute("""
                INSERT INTO tbl_inventory_losses
                (
                    loss_code,
                    product_id,
                    quantity,
                    reason,
                    loss_date
                )
                VALUES (%s, %s, %s, %s, CURDATE())
            """, (
                loss_code,
                product_id,
                quantity,
                reason
            ))

        # SAVE ALL CHANGES TOGETHER
        connection.commit()

    except Exception:

        rollback_database(connection)
        raise

    finally:
        close_database(connection, cursor)


# GENERAL STOCK OUT
@inventory_blueprint.route(
    "/stock-out",
    methods=["GET", "POST"]
)
def stock_out():

    if request.method == "POST":

        try:
            product_id, quantity, reason = validate_stock_form()

            process_stock_reduction(
                product_id,
                quantity,
                reason,
                is_inventory_loss=False
            )

            flash(
                "Stock Out recorded successfully!",
                "success"
            )

        except ValueError as error:

            flash(str(error), "error")

        except Exception:

            current_app.logger.exception(
                "STOCK OUT ERROR"
            )

            flash(
                "Unable to record Stock Out. Please try again.",
                "error"
            )

        return redirect(
            url_for("inventory.stock_out")
        )

    try:
        products = get_inventory_products()

        return render_template(
            "admin/stock_out.html",
            products=products
        )

    except Exception:

        current_app.logger.exception(
            "LOAD STOCK OUT ERROR"
        )

        flash(
            "Unable to load stock products.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )


# INVENTORY LOSS
@inventory_blueprint.route(
    "/inventory-loss",
    methods=["GET", "POST"]
)
def inventory_loss():

    if request.method == "POST":

        try:
            product_id, quantity, reason = validate_stock_form()

            process_stock_reduction(
                product_id,
                quantity,
                reason,
                is_inventory_loss=True
            )

            flash(
                "Inventory loss recorded and stock updated successfully!",
                "success"
            )

        except ValueError as error:

            flash(str(error), "error")

        except Exception:

            current_app.logger.exception(
                "INVENTORY LOSS ERROR"
            )

            flash(
                "Unable to record inventory loss. Please try again.",
                "error"
            )

        return redirect(
            url_for("inventory.inventory_loss")
        )

    try:
        products = get_inventory_products()

        return render_template(
            "admin/inventory_loss.html",
            products=products
        )

    except Exception:

        current_app.logger.exception(
            "LOAD INVENTORY LOSS PRODUCTS ERROR"
        )

        flash(
            "Unable to load inventory loss products.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )