import os
import logging
import mysql.connector

from decimal import Decimal, InvalidOperation

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    session,
    send_file,
    abort
)

from . import admin_blueprint
from database.db import (
    get_db_connection,
    generate_custom_code,
    get_product_primary_key_column
)
from payment.status import update_sale_payment_status
from utils.product_images import (
    delete_product_image,
    save_product_image
)
from models import Product


logger = logging.getLogger(__name__)


# ==========================================
# ADMIN ACCESS
# ==========================================

@admin_blueprint.before_request
def admin_required():

    if not session.get("user_id"):
        flash(
            "You must log in before accessing the dashboard.",
            "danger"
        )
        return redirect(url_for("auth.login"))

    if session.get("role") != "admin":
        flash(
            "You are not allowed to access this page.",
            "error"
        )

        return redirect(url_for("auth.login"))


# ==========================================
# DATABASE HELPERS
# ==========================================

def close_database(connection, cursor):

    if cursor is not None:
        try:
            cursor.close()
        except mysql.connector.Error:
            logger.exception("DATABASE CURSOR CLOSE ERROR")

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except mysql.connector.Error:
            logger.exception("DATABASE CONNECTION CLOSE ERROR")


def rollback_transaction(connection):

    if connection is not None:
        try:
            connection.rollback()
        except mysql.connector.Error:
            logger.exception("DATABASE ROLLBACK ERROR")


# ==========================================
# PRODUCT VALIDATION
# ==========================================

def validate_product_values(
    product_name,
    category,
    price_input,
    quantity_input,
    min_stock_input,
    max_stock_input=""
):
    product = Product.from_form(
        product_name,
        category,
        price_input,
        quantity_input,
        min_stock_input,
        max_stock_input
    )
    return product.stock_values()


# ==========================================
# PRODUCT STATUS
# ==========================================

def get_product_status(quantity):

    return (
        "Available"
        if quantity > 0
        else "Unavailable"
    )


# ==========================================
# DAILY CATALOG STOCK ADJUSTMENT
# ==========================================

def limit_daily_catalog_quantity(
    cursor,
    product_id,
    actual_quantity
):

    cursor.execute("""
        UPDATE tbl_daily_catalog
        SET available_quantity = LEAST(
            available_quantity,
            %s
        )
        WHERE product_id = %s
          AND catalog_date = CURDATE()
    """, (
        actual_quantity,
        product_id
    ))


def record_product_stock_change(
    cursor,
    product_id,
    change_type,
    previous_quantity,
    changed_quantity,
    new_quantity,
    reason
):
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tbl_stock_history'
    """)
    columns = {
        row["COLUMN_NAME"] if isinstance(row, dict) else row[0]
        for row in cursor.fetchall()
    }

    type_column = (
        "change_type"
        if "change_type" in columns
        else "transaction_type"
    )
    quantity_column = (
        "changed_quantity"
        if "changed_quantity" in columns
        else "quantity"
    )
    required_columns = {
        "stock_code",
        "product_id",
        type_column,
        quantity_column,
        "previous_quantity",
        "new_quantity",
        "reason"
    }

    if not required_columns.issubset(columns):
        raise RuntimeError(
            "The stock history table is missing required product movement columns."
        )

    stock_code = generate_custom_code(cursor, "tbl_stock_history")
    insert_columns = [
        "stock_code",
        "product_id",
        type_column,
        quantity_column,
        "previous_quantity",
        "new_quantity",
        "reason"
    ]
    values = [
        stock_code,
        product_id,
        change_type,
        changed_quantity,
        previous_quantity,
        new_quantity,
        reason
    ]

    if "user_id" in columns:
        insert_columns.insert(2, "user_id")
        values.insert(2, session.get("user_id"))

    column_sql = ", ".join(f"`{column}`" for column in insert_columns)
    placeholders = ", ".join(["%s"] * len(values))
    cursor.execute(
        f"INSERT INTO tbl_stock_history ({column_sql}) "
        f"VALUES ({placeholders})",
        tuple(values)
    )


# ==========================================
# ADMIN DASHBOARD
# ==========================================

@admin_blueprint.route("/dashboard")
def dashboard():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                COUNT(*) AS total_products,

                COALESCE(SUM(
                    CASE
                        WHEN quantity > min_stock
                         AND (
                            max_stock IS NULL
                            OR quantity <= max_stock
                         ) THEN 1
                        ELSE 0
                    END
                ), 0) AS available_products,

                COALESCE(SUM(
                    CASE
                        WHEN quantity > 0
                         AND quantity <= min_stock THEN 1
                        ELSE 0
                    END
                ), 0) AS low_stock,

                COALESCE(SUM(
                    CASE
                        WHEN quantity <= 0 THEN 1
                        ELSE 0
                    END
                ), 0) AS out_of_stock,

                COALESCE(SUM(
                    CASE
                        WHEN max_stock IS NOT NULL
                         AND quantity > max_stock THEN 1
                        ELSE 0
                    END
                ), 0) AS over_stock

            FROM tbl_products
        """)

        inventory_stats = cursor.fetchone()

        cursor.execute("""
            SELECT COUNT(*) AS total_sales
            FROM tbl_sales
            WHERE status != 'Cancelled'
        """)

        total_sales = cursor.fetchone()["total_sales"]

        cursor.execute("""
            SELECT
                COALESCE(SUM(p.amount), 0) AS total_income

            FROM tbl_payments AS p

            INNER JOIN tbl_sales AS s
                ON p.sale_id = s.id

            WHERE p.payment_status = 'Verified'
              AND s.status != 'Cancelled'
        """)

        total_income = cursor.fetchone()["total_income"]

        return render_template(
            "admin/dashboard.html",
            total_products=inventory_stats["total_products"],
            available_products=inventory_stats["available_products"],
            low_stock=inventory_stats["low_stock"],
            out_of_stock=inventory_stats["out_of_stock"],
            over_stock=inventory_stats["over_stock"],
            total_sales=total_sales,
            total_income=total_income
        )

    except mysql.connector.Error:
        logger.exception("ADMIN DASHBOARD ERROR")

        flash(
            "Unable to load the dashboard.",
            "error"
        )

        return redirect(url_for("auth.login"))

    finally:
        close_database(connection, cursor)


# ==========================================
# PRODUCT MANAGEMENT
# ==========================================

@admin_blueprint.route("/products")
def products():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        product_id_column = get_product_primary_key_column(cursor)

        cursor.execute(f"""
            SELECT *, `{product_id_column}` AS id
            FROM tbl_products
            ORDER BY product_name ASC
        """)

        products_list = cursor.fetchall()

        return render_template(
            "admin/products.html",
            products=products_list
        )

    except mysql.connector.Error:
        logger.exception("PRODUCT LIST ERROR")

        flash(
            "Unable to load products.",
            "error"
        )

        return redirect(url_for("admin.dashboard"))

    finally:
        close_database(connection, cursor)


# ==========================================
# ADD PRODUCT
# ==========================================

@admin_blueprint.route(
    "/products/add",
    methods=["GET", "POST"]
)
def add_product():

    if request.method == "GET":
        return render_template("admin/add_product.html")

    product_name = request.form.get(
        "product_name", ""
    ).strip()

    category = request.form.get(
        "category", ""
    ).strip()

    description = request.form.get(
        "description", ""
    ).strip()

    try:
        price, quantity, min_stock, max_stock = validate_product_values(
            product_name,
            category,
            request.form.get("price", "").strip(),
            request.form.get("quantity", "").strip(),
            request.form.get("min_stock", "5").strip(),
            request.form.get("max_stock", "").strip()
        )

    except ValueError as error:
        flash(str(error), "error")

        return redirect(
            url_for("admin.add_product")
        )

    try:
        image_path = save_product_image(
            request.files.get("product_image")
        )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.add_product"))
    except OSError:
        flash("Unable to save the product image.", "error")
        return redirect(url_for("admin.add_product"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()

        cursor = connection.cursor()

        status = get_product_status(quantity)

        # GENERATE PRODUCT CODE
        product_code = generate_custom_code(
            cursor,
            "tbl_products"
        )

        cursor.execute("""
            INSERT INTO tbl_products
            (
                product_code,
                product_name,
                category,
                description,
                image_path,
                price,
                quantity,
                min_stock,
                max_stock,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            product_code,
            product_name,
            category,
            description,
            image_path,
            price,
            quantity,
            min_stock,
            max_stock,
            status
        ))

        product_id = cursor.lastrowid

        if quantity > 0:
            record_product_stock_change(
                cursor,
                product_id,
                "Stock In",
                0,
                quantity,
                quantity,
                "Initial product stock"
            )

        connection.commit()

        flash(
            "Product added successfully.",
            "success"
        )

        return redirect(
            url_for("admin.products")
        )

    except mysql.connector.Error:
        rollback_transaction(connection)
        delete_product_image(image_path)

        logger.exception("ADD PRODUCT ERROR")

        flash(
            "Unable to add the product.",
            "error"
        )

        return redirect(
            url_for("admin.add_product")
        )

    except Exception:
        rollback_transaction(connection)
        delete_product_image(image_path)
        logger.exception("ADD PRODUCT ERROR")
        flash("Unable to add the product.", "error")
        return redirect(url_for("admin.add_product"))

    finally:
        close_database(connection, cursor)


# ==========================================
# EDIT PRODUCT
# ==========================================

@admin_blueprint.route(
    "/products/edit/<int:product_id>",
    methods=["GET", "POST"]
)
def edit_product(product_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if request.method == "GET":

            product_id_column = get_product_primary_key_column(cursor)
            cursor.execute(f"""
                SELECT *
                FROM tbl_products
                WHERE `{product_id_column}` = %s
            """, (product_id,))

            product = cursor.fetchone()

            if not product:
                flash(
                    "Product not found.",
                    "error"
                )

                return redirect(
                    url_for("admin.products")
                )

            return render_template(
                "admin/edit_product.html",
                product=product
            )

        product_name = request.form.get(
            "product_name", ""
        ).strip()

        category = request.form.get(
            "category", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        try:
            price, quantity, min_stock, max_stock = validate_product_values(
                product_name,
                category,
                request.form.get("price", "").strip(),
                request.form.get("quantity", "").strip(),
                request.form.get("min_stock", "5").strip(),
                request.form.get("max_stock", "").strip()
            )

        except ValueError as error:
            flash(str(error), "error")

            return redirect(
                url_for(
                    "admin.edit_product",
                    product_id=product_id
                )
            )

        connection.start_transaction()

        product_id_column = get_product_primary_key_column(cursor)
        cursor.execute(f"""
            SELECT quantity, image_path
            FROM tbl_products
            WHERE `{product_id_column}` = %s
            FOR UPDATE
        """, (product_id,))

        existing_product = cursor.fetchone()

        if not existing_product:
            connection.rollback()

            flash(
                "Product not found.",
                "error"
            )

            return redirect(
                url_for("admin.products")
            )

        previous_quantity = int(
            existing_product["quantity"]
        )

        quantity_difference = (
            quantity - previous_quantity
        )

        status = get_product_status(quantity)
        old_image_path = existing_product["image_path"]

        try:
            uploaded_image_path = save_product_image(
                request.files.get("product_image")
            )
        except ValueError as error:
            connection.rollback()
            flash(str(error), "error")
            return redirect(
                url_for(
                    "admin.edit_product",
                    product_id=product_id
                )
            )
        except OSError:
            connection.rollback()
            flash("Unable to save the product image.", "error")
            return redirect(
                url_for(
                    "admin.edit_product",
                    product_id=product_id
                )
            )

        remove_image = request.form.get("remove_product_image") == "yes"
        image_path = uploaded_image_path or (
            None if remove_image else old_image_path
        )

        cursor.execute(f"""
            UPDATE tbl_products
            SET product_name = %s,
                category = %s,
                description = %s,
                image_path = %s,
                price = %s,
                quantity = %s,
                min_stock = %s,
                max_stock = %s,
                status = %s
            WHERE `{product_id_column}` = %s
        """, (
            product_name,
            category,
            description,
            image_path,
            price,
            quantity,
            min_stock,
            max_stock,
            status,
            product_id
        ))

        if quantity_difference != 0:

            change_type = (
                "Stock In"
                if quantity_difference > 0
                else "Stock Out"
            )

            record_product_stock_change(
                cursor,
                product_id,
                change_type,
                previous_quantity,
                abs(quantity_difference),
                quantity,
                "Product quantity adjusted by admin"
            )

            # Limit today's catalog when stock decreases.
            if quantity_difference < 0:

                limit_daily_catalog_quantity(
                    cursor,
                    product_id,
                    quantity
                )

        connection.commit()

        if uploaded_image_path or remove_image:
            delete_product_image(old_image_path)

        flash(
            "Product updated successfully.",
            "success"
        )

        return redirect(
            url_for("admin.products")
        )

    except mysql.connector.Error:
        rollback_transaction(connection)

        if "uploaded_image_path" in locals():
            delete_product_image(uploaded_image_path)

        logger.exception("EDIT PRODUCT ERROR")

        flash(
            "Unable to update the product.",
            "error"
        )

        return redirect(
            url_for("admin.products")
        )

    except Exception:
        rollback_transaction(connection)
        if "uploaded_image_path" in locals():
            delete_product_image(uploaded_image_path)
        logger.exception("EDIT PRODUCT ERROR")
        flash("Unable to update the product.", "error")
        return redirect(url_for("admin.products"))

    finally:
        close_database(connection, cursor)


# ==========================================
# DELETE PRODUCT
# ==========================================

@admin_blueprint.route(
    "/products/delete/<int:product_id>",
    methods=["POST"]
)
def delete_product(product_id):

    connection = None
    cursor = None

    related_tables = [
        "tbl_daily_catalog",
        "tbl_stock_history",
        "tbl_sale_items",
        "tbl_inventory_losses"
    ]

    try:
        connection = get_db_connection()
        connection.start_transaction()

        cursor = connection.cursor(dictionary=True)

        product_id_column = get_product_primary_key_column(cursor)
        cursor.execute(f"""
            SELECT `{product_id_column}` AS id, image_path
            FROM tbl_products
            WHERE `{product_id_column}` = %s
            FOR UPDATE
        """, (product_id,))

        product = cursor.fetchone()

        if not product:
            connection.rollback()

            flash(
                "Product not found.",
                "error"
            )

            return redirect(
                url_for("admin.products")
            )

        has_related_records = False

        for table_name in related_tables:

            cursor.execute(
                f"""
                SELECT 1
                FROM {table_name}
                WHERE product_id = %s
                LIMIT 1
                """,
                (product_id,)
            )

            if cursor.fetchone():
                has_related_records = True
                break

        if has_related_records:
            connection.rollback()

            flash(
                "This product cannot be deleted because it has existing inventory or transaction records.",
                "error"
            )

            return redirect(
                url_for("admin.products")
            )

        cursor.execute(f"""
            DELETE FROM tbl_products
            WHERE `{product_id_column}` = %s
        """, (product_id,))

        connection.commit()
        delete_product_image(product["image_path"])

        flash(
            "Product deleted successfully.",
            "success"
        )

    except mysql.connector.Error:
        rollback_transaction(connection)

        logger.exception("DELETE PRODUCT ERROR")

        flash(
            "Unable to delete this product. It may have existing records.",
            "error"
        )

    finally:
        close_database(connection, cursor)

    return redirect(
        url_for("admin.products")
    )


# ==========================================
# DAILY CATALOG
# ==========================================

@admin_blueprint.route(
    "/daily-catalog",
    methods=["GET", "POST"]
)
def daily_catalog():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if request.method == "POST":

            try:
                product_id = int(
                    request.form.get(
                        "product_id", ""
                    ).strip()
                )

                available_quantity = int(
                    request.form.get(
                        "available_quantity", ""
                    ).strip()
                )

                if (
                    product_id <= 0
                    or available_quantity < 0
                ):
                    raise ValueError

            except (TypeError, ValueError):
                flash(
                    "Please enter a valid product and quantity.",
                    "error"
                )

                return redirect(
                    url_for("admin.daily_catalog")
                )

            connection.start_transaction()

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
                connection.rollback()

                flash(
                    "Product not found.",
                    "error"
                )

                return redirect(
                    url_for("admin.daily_catalog")
                )

            if available_quantity > int(product["quantity"]):
                connection.rollback()

                flash(
                    "Catalog quantity cannot exceed actual stock.",
                    "error"
                )

                return redirect(
                    url_for("admin.daily_catalog")
                )

            # GENERATE DAILY CATALOG CODE
            catalog_code = generate_custom_code(
                cursor,
                "tbl_daily_catalog"
            )

            cursor.execute("""
                INSERT INTO tbl_daily_catalog
                (
                    catalog_code,
                    product_id,
                    catalog_date,
                    available_quantity
                )
                VALUES (%s, %s, CURDATE(), %s)

                ON DUPLICATE KEY UPDATE
                    available_quantity = VALUES(available_quantity)
            """, (
                catalog_code,
                product_id,
                available_quantity
            ))

            connection.commit()

            flash(
                "Daily catalog updated successfully.",
                "success"
            )

            return redirect(
                url_for("admin.daily_catalog")
            )

        cursor.execute("""
            SELECT
                dc.id,
                dc.catalog_code,
                dc.product_id,
                dc.catalog_date,
                dc.available_quantity,
                p.product_name,
                p.category,
                p.price
            FROM tbl_daily_catalog AS dc
            INNER JOIN tbl_products AS p
                ON dc.product_id = p.id
            WHERE dc.catalog_date = CURDATE()
            ORDER BY p.product_name
        """)

        catalog_list = cursor.fetchall()

        cursor.execute("""
            SELECT
                id,
                product_code,
                product_name,
                quantity
            FROM tbl_products
            ORDER BY product_name
        """)

        products_list = cursor.fetchall()

        return render_template(
            "admin/daily_catalog.html",
            catalog=catalog_list,
            products=products_list
        )

    except mysql.connector.Error:
        rollback_transaction(connection)

        logger.exception("DAILY CATALOG ERROR")

        flash(
            "Unable to load the daily catalog.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(connection, cursor)


# ==========================================
# STOCK MONITORING
# ==========================================

@admin_blueprint.route("/stock-monitoring")
def stock_monitoring():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        product_id_column = get_product_primary_key_column(cursor)

        cursor.execute(f"""
            SELECT
            `{product_id_column}` AS id,
                product_code,
                product_name,
                category,
                price,
                quantity,
                min_stock,
                max_stock,
                status
            FROM tbl_products
            ORDER BY
                CASE
                    WHEN quantity <= 0 THEN 0
                    WHEN quantity <= min_stock THEN 1
                    WHEN max_stock IS NOT NULL
                     AND quantity > max_stock THEN 2
                    ELSE 3
                END,
                quantity ASC,
                product_name ASC
        """)

        products_list = cursor.fetchall()

        cursor.execute(f"""
            SELECT
                sh.id,
                sh.stock_code,
                sh.product_id,
                sh.change_type,
                sh.previous_quantity,
                sh.changed_quantity,
                sh.new_quantity,
                sh.reason,
                sh.created_at,
                p.product_name
            FROM tbl_stock_history AS sh
            INNER JOIN tbl_products AS p
                ON sh.product_id = p.`{product_id_column}`
            ORDER BY sh.created_at DESC, sh.id DESC
            LIMIT 100
        """)

        history_list = cursor.fetchall()

        return render_template(
            "admin/stock_monitoring.html",
            products=products_list,
            history=history_list
        )

    except mysql.connector.Error:
        logger.exception("STOCK MONITORING ERROR")

        flash(
            "Unable to load stock monitoring records.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(connection, cursor)


# INVENTORY RECONCILIATION
@admin_blueprint.route("/inventory-reconciliation")
def inventory_reconciliation():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.id,
                p.product_code,
                p.product_name,
                p.quantity AS current_quantity,
                sh.new_quantity AS latest_recorded_quantity,
                sh.created_at AS latest_movement_at,
                CASE
                    WHEN sh.id IS NULL THEN 'Missing stock history'
                    ELSE 'Quantity mismatch'
                END AS issue
            FROM tbl_products AS p
            LEFT JOIN tbl_stock_history AS sh
                ON sh.id = (
                    SELECT sh_latest.id
                    FROM tbl_stock_history AS sh_latest
                    WHERE sh_latest.product_id = p.id
                    ORDER BY sh_latest.created_at DESC, sh_latest.id DESC
                    LIMIT 1
                )
            WHERE (
                sh.id IS NULL
                AND p.quantity > 0
            )
            OR (
                sh.id IS NOT NULL
                AND sh.new_quantity <> p.quantity
            )
            ORDER BY p.product_name ASC
        """)
        issues = cursor.fetchall()

        return render_template(
            "admin/inventory_reconciliation.html",
            issues=issues
        )

    except mysql.connector.Error:
        logger.exception("INVENTORY RECONCILIATION ERROR")
        flash(
            "Unable to load inventory reconciliation results.",
            "error"
        )
        return redirect(url_for("admin.dashboard"))

    finally:
        close_database(connection, cursor)


# ==========================================
# STOCK HISTORY
# ==========================================

@admin_blueprint.route("/stock-history")
def stock_history():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                sh.id,
                sh.stock_code,
                sh.product_id,
                sh.change_type,
                sh.previous_quantity,
                sh.changed_quantity,
                sh.new_quantity,
                sh.reason,
                sh.created_at,
                p.product_name
            FROM tbl_stock_history AS sh
            INNER JOIN tbl_products AS p
                ON sh.product_id = p.id
            ORDER BY sh.created_at DESC, sh.id DESC
        """)

        history_list = cursor.fetchall()

        return render_template(
            "admin/stock_history.html",
            stock_history=history_list
        )

    except mysql.connector.Error:
        logger.exception("STOCK HISTORY ERROR")

        flash(
            "Unable to load stock history.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(connection, cursor)


# ==========================================
# LOW STOCK
# ==========================================

@admin_blueprint.route("/low-stock")
def low_stock():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM tbl_products
            WHERE quantity <= min_stock
            ORDER BY quantity ASC, product_name ASC
        """)

        low_stock_products = cursor.fetchall()

        return render_template(
            "admin/low_stock.html",
            products=low_stock_products
        )

    except mysql.connector.Error:
        logger.exception("LOW STOCK ERROR")

        flash(
            "Unable to load low-stock records.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(connection, cursor)


# ==========================================
# ADMIN PAYMENT VERIFICATION
# ==========================================

@admin_blueprint.route("/payments")
def payments():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.id,
                p.payment_code,
                p.sale_id,
                p.amount,
                p.payment_method,
                p.payment_status,
                p.payment_date,
                p.reference_number,
                p.proof_image,
                s.total_amount,
                s.status AS order_status,
                s.order_date,
                u.name AS customer_name
            FROM tbl_payments AS p
            INNER JOIN tbl_sales AS s
                ON p.sale_id = s.id
            INNER JOIN tbl_users AS u
                ON s.user_id = u.id
            ORDER BY
                CASE
                    WHEN p.payment_status = 'Pending' THEN 0
                    ELSE 1
                END,
                p.id DESC
        """)

        payments_list = cursor.fetchall()

        return render_template(
            "admin/payments.html",
            payments=payments_list
        )

    except mysql.connector.Error:
        logger.exception("ADMIN PAYMENT LIST ERROR")

        flash(
            "Unable to load payment records.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(connection, cursor)


# ==========================================
# VIEW PAYMENT PROOF
# ==========================================

@admin_blueprint.route(
    "/payments/<int:payment_id>/proof"
)
def view_payment_proof(payment_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT proof_image
            FROM tbl_payments
            WHERE id = %s
              AND payment_method IN (
                  'GCash',
                  'Maya',
                  'Online Banking'
              )
        """, (payment_id,))

        payment = cursor.fetchone()

        if not payment or not payment["proof_image"]:
            abort(404)

        proof_path = os.path.normpath(
            payment["proof_image"]
        )

        if os.path.isabs(proof_path):
            abort(404)

        expected_folder = os.path.realpath(
            os.path.join(
                current_app.instance_path,
                "payment_proofs"
            )
        )

        full_path = os.path.realpath(
            os.path.join(
                current_app.instance_path,
                proof_path
            )
        )

        try:
            if os.path.commonpath(
                [expected_folder, full_path]
            ) != expected_folder:
                abort(404)

        except ValueError:
            abort(404)

        if not os.path.isfile(full_path):
            abort(404)

        extension = os.path.splitext(
            full_path
        )[1].lower()

        allowed_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png"
        }

        if extension not in allowed_types:
            abort(404)

        return send_file(
            full_path,
            mimetype=allowed_types[extension]
        )

    except mysql.connector.Error:
        logger.exception("PAYMENT PROOF ERROR")
        abort(500)

    finally:
        close_database(connection, cursor)


# ==========================================
# UPDATE PAYMENT STATUS
# ==========================================

@admin_blueprint.route(
    "/payments/<int:payment_id>/update",
    methods=["POST"]
)
def update_payment_status(payment_id):

    action = request.form.get(
        "action", ""
    ).strip().lower()

    if action not in ["verify", "reject"]:
        flash(
            "Invalid payment action.",
            "error"
        )

        return redirect(
            url_for("admin.payments")
        )

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()

        cursor = connection.cursor(dictionary=True)

        # GET PAYMENT REFERENCE
        cursor.execute("""
            SELECT sale_id
            FROM tbl_payments
            WHERE id = %s
        """, (payment_id,))

        payment_reference = cursor.fetchone()

        if not payment_reference:
            connection.rollback()

            flash(
                "Payment record not found.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        sale_id = payment_reference["sale_id"]

        # LOCK THE SALE FIRST
        cursor.execute("""
            SELECT
                id,
                status,
                total_amount
            FROM tbl_sales
            WHERE id = %s
            FOR UPDATE
        """, (sale_id,))

        sale = cursor.fetchone()

        if not sale:
            connection.rollback()

            flash(
                "Order record not found.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        if sale["status"] == "Cancelled":
            connection.rollback()

            flash(
                "This order has been cancelled. Its payment can no longer be updated.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        # LOCK THE PAYMENT
        cursor.execute("""
            SELECT
                id,
                sale_id,
                amount,
                payment_method,
                payment_status
            FROM tbl_payments
            WHERE id = %s
              AND sale_id = %s
            FOR UPDATE
        """, (
            payment_id,
            sale_id
        ))

        payment = cursor.fetchone()

        if not payment:
            connection.rollback()

            flash(
                "Payment record not found.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        if payment["payment_status"] != "Pending":
            connection.rollback()

            flash(
                "This payment has already been reviewed.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        # CASH ON PICKUP CONFIRMATION
        if (
            action == "verify"
            and payment["payment_method"] == "Cash on Pickup"
            and request.form.get("cash_received") != "yes"
        ):
            connection.rollback()

            flash(
                "Please confirm that the cash payment has been received before verifying.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        # VALIDATE PAYMENT AMOUNT
        if action == "verify":

            try:
                payment_amount = Decimal(
                    str(payment["amount"])
                )

                total_amount = Decimal(
                    str(sale["total_amount"])
                )

                if (
                    not payment_amount.is_finite()
                    or not total_amount.is_finite()
                    or payment_amount <= 0
                    or total_amount <= 0
                ):
                    raise ValueError

            except (
                InvalidOperation,
                TypeError,
                ValueError
            ):
                connection.rollback()

                flash(
                    "Invalid payment amount. Verification was not completed.",
                    "error"
                )

                return redirect(
                    url_for("admin.payments")
                )

            cursor.execute("""
                SELECT
                    COALESCE(SUM(amount), 0) AS verified_total
                FROM tbl_payments
                WHERE sale_id = %s
                  AND payment_status = 'Verified'
            """, (sale_id,))

            result = cursor.fetchone()

            verified_total = Decimal(
                str(result["verified_total"])
            )

            if (
                not verified_total.is_finite()
                or verified_total < 0
                or verified_total + payment_amount > total_amount
            ):
                connection.rollback()

                flash(
                    "This payment cannot be verified because the verified amount would exceed the order total.",
                    "error"
                )

                return redirect(
                    url_for("admin.payments")
                )

            cursor.execute("""
                UPDATE tbl_payments
                SET payment_status = 'Verified',
                    verified_by = %s,
                    verified_at = NOW()
                WHERE id = %s
                  AND sale_id = %s
                  AND payment_status = 'Pending'
            """, (
                session["user_id"],
                payment_id,
                sale_id
            ))

        else:

            cursor.execute("""
                UPDATE tbl_payments
                SET payment_status = 'Rejected',
                    verified_by = NULL,
                    verified_at = NULL
                WHERE id = %s
                  AND sale_id = %s
                  AND payment_status = 'Pending'
            """, (
                payment_id,
                sale_id
            ))

        if cursor.rowcount != 1:
            connection.rollback()

            flash(
                "Unable to update this payment.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        # UPDATE THE SALE STATUS
        status_updated = update_sale_payment_status(
            cursor,
            sale_id
        )

        if not status_updated:
            connection.rollback()

            flash(
                "Payment status could not be updated. No changes were saved.",
                "error"
            )

            return redirect(
                url_for("admin.payments")
            )

        connection.commit()

        if action == "verify":
            flash(
                "Payment verified successfully.",
                "success"
            )
        else:
            flash(
                "Payment rejected. The customer may submit a new payment.",
                "success"
            )

        return redirect(
            url_for("admin.payments")
        )

    except mysql.connector.Error:
        rollback_transaction(connection)

        logger.exception(
            "ADMIN PAYMENT UPDATE ERROR"
        )

        flash(
            "Unable to update the payment right now.",
            "error"
        )

        return redirect(
            url_for("admin.payments")
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
        KeyError
    ):
        rollback_transaction(connection)

        logger.exception(
            "ADMIN PAYMENT VALIDATION ERROR"
        )

        flash(
            "Invalid payment information.",
            "error"
        )

        return redirect(
            url_for("admin.payments")
        )

    finally:
        close_database(connection, cursor)


# ==========================================
# DATABASE MONITORING
# ==========================================

@admin_blueprint.route("/database-monitoring")
def database_monitoring():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # INVENTORY SUMMARY
        cursor.execute("""
            SELECT
                COUNT(*) AS total_products,
                COALESCE(SUM(quantity), 0) AS total_stock,

                COALESCE(SUM(
                    CASE
                        WHEN quantity > min_stock THEN 1
                        ELSE 0
                    END
                ), 0) AS available_products,

                COALESCE(SUM(
                    CASE
                        WHEN quantity > 0
                         AND quantity <= min_stock
                        THEN 1
                        ELSE 0
                    END
                ), 0) AS low_stock_products,

                COALESCE(SUM(
                    CASE
                        WHEN quantity <= 0 THEN 1
                        ELSE 0
                    END
                ), 0) AS out_of_stock_products

            FROM tbl_products
        """)

        inventory_summary = cursor.fetchone()

        # SALES SUMMARY
        cursor.execute("""
            SELECT
                COUNT(*) AS total_orders,
                COALESCE(SUM(total_amount), 0) AS total_sales
            FROM tbl_sales
            WHERE status != 'Cancelled'
        """)

        sales_summary = cursor.fetchone()

        # VERIFIED PAYMENT SUMMARY
        cursor.execute("""
            SELECT
                COALESCE(SUM(p.amount), 0) AS verified_income,
                COUNT(*) AS verified_payments

            FROM tbl_payments AS p

            INNER JOIN tbl_sales AS s
                ON p.sale_id = s.id

            WHERE p.payment_status = 'Verified'
              AND s.status != 'Cancelled'
        """)

        income_summary = cursor.fetchone()

        # DAILY VERIFIED INCOME - LAST 7 DAYS
        cursor.execute("""
            SELECT
                DATE(p.payment_date) AS payment_day,
                COALESCE(SUM(p.amount), 0) AS daily_income

            FROM tbl_payments AS p

            INNER JOIN tbl_sales AS s
                ON p.sale_id = s.id

            WHERE p.payment_status = 'Verified'
              AND s.status != 'Cancelled'
              AND p.payment_date >= CURDATE() - INTERVAL 6 DAY

            GROUP BY DATE(p.payment_date)

            ORDER BY payment_day ASC
        """)

        daily_income = cursor.fetchall()

        # TOP-SELLING FISH
        cursor.execute("""
            SELECT
                p.product_name,
                COALESCE(SUM(si.quantity), 0) AS total_sold

            FROM tbl_sale_items AS si

            INNER JOIN tbl_products AS p
                ON si.product_id = p.id

            INNER JOIN tbl_sales AS s
                ON si.sale_id = s.id

            WHERE s.status != 'Cancelled'

            GROUP BY
                p.id,
                p.product_name

            ORDER BY total_sold DESC

            LIMIT 5
        """)

        top_products = cursor.fetchall()

        # INVENTORY RECORDS
        cursor.execute("""
            SELECT
                id,
                product_code,
                product_name,
                category,
                price,
                quantity,
                min_stock,

                CASE
                    WHEN quantity <= 0
                        THEN 'Out of Stock'

                    WHEN quantity <= min_stock
                        THEN 'Low Stock'

                    ELSE 'Available'
                END AS stock_status

            FROM tbl_products

            ORDER BY product_name ASC
        """)

        inventory_records = cursor.fetchall()

        # RECENT STOCK HISTORY
        cursor.execute("""
            SELECT
                sh.id,
                sh.stock_code,
                p.product_name,
                sh.change_type,
                sh.previous_quantity,
                sh.changed_quantity,
                sh.new_quantity,
                sh.reason,
                sh.created_at

            FROM tbl_stock_history AS sh

            INNER JOIN tbl_products AS p
                ON sh.product_id = p.id

            ORDER BY
                sh.created_at DESC,
                sh.id DESC

            LIMIT 10
        """)

        stock_history = cursor.fetchall()

        return render_template(
            "admin/database_monitoring.html",
            inventory_summary=inventory_summary,
            sales_summary=sales_summary,
            income_summary=income_summary,
            daily_income=daily_income,
            top_products=top_products,
            inventory_records=inventory_records,
            stock_history=stock_history
        )

    except mysql.connector.Error:
        logger.exception(
            "DATABASE MONITORING ERROR"
        )

        flash(
            "Unable to load database monitoring information.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(connection, cursor)