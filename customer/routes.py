import logging
from decimal import Decimal

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from . import customer_blueprint
from database.db import (
    get_db_connection,
    generate_custom_code,
    get_product_primary_key_column
)


logger = logging.getLogger(__name__)


# ==========================================
# CUSTOMER ACCESS PROTECTION
# ==========================================

@customer_blueprint.before_request
def require_customer():

    if not session.get("user_id"):
        flash("You must log in before accessing this page.", "danger")
        return redirect(url_for("auth.login"))

    if session.get("role") != "customer":
        flash("You are not allowed to access this page.", "danger")
        return redirect(url_for("auth.login"))


# ==========================================
# DATABASE CLEANUP
# ==========================================

def close_database(connection=None, cursor=None):

    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            logger.exception("Failed to close database cursor.")

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except Exception:
            logger.exception("Failed to close database connection.")


# ==========================================
# VALIDATE CART DATA
# ==========================================

def get_valid_cart():

    cart = session.get("cart", {})

    if not isinstance(cart, dict):
        return {}

    valid_cart = {}

    for product_id, quantity in cart.items():

        try:
            product_id = int(product_id)
            quantity = int(quantity)

            if product_id > 0 and quantity > 0:
                valid_cart[str(product_id)] = quantity

        except (TypeError, ValueError):
            continue

    return valid_cart


# ==========================================
# GET PRODUCT IDS
# ==========================================

def get_product_ids(cart):

    return tuple(
        int(product_id)
        for product_id in cart.keys()
    )


# ==========================================
# CUSTOMER DASHBOARD
# ==========================================

@customer_blueprint.route("/dashboard")
def dashboard():

    return render_template("customer/dashboard.html")


# ==========================================
# PRODUCT CATALOG
# ==========================================

@customer_blueprint.route("/catalog")
def catalog():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        product_id_column = get_product_primary_key_column(cursor)

        cursor.execute(f"""
            SELECT
                p.`{product_id_column}` AS id,
                p.product_name,
                p.category,
                p.description,
                p.image_path,
                p.price,
                dc.available_quantity,
                dc.catalog_date
            FROM tbl_daily_catalog AS dc
            INNER JOIN tbl_products AS p
                ON dc.product_id = p.`{product_id_column}`
            WHERE dc.catalog_date = CURDATE()
              AND dc.available_quantity > 0
              AND p.quantity > 0
              AND p.status = 'Available'
            ORDER BY p.product_name ASC
        """)

        products = cursor.fetchall()

        return render_template(
            "customer/catalog.html",
            products=products
        )

    except Exception:
        logger.exception("Customer catalog error.")

        flash(
            "Unable to load the product catalog.",
            "danger"
        )

        return redirect(url_for("customer.dashboard"))

    finally:
        close_database(connection, cursor)


# ==========================================
# PRODUCT DETAILS
# ==========================================

@customer_blueprint.route("/product/<int:product_id>")
def product_details(product_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        product_id_column = get_product_primary_key_column(cursor)

        cursor.execute(f"""
            SELECT
                p.`{product_id_column}` AS id,
                p.product_name,
                p.category,
                p.description,
                p.image_path,
                p.price,
                p.status,
                p.quantity,
                dc.available_quantity,
                dc.catalog_date
            FROM tbl_products AS p
            LEFT JOIN tbl_daily_catalog AS dc
                ON p.`{product_id_column}` = dc.product_id
                AND dc.catalog_date = CURDATE()
            WHERE p.`{product_id_column}` = %s
        """, (product_id,))

        product = cursor.fetchone()

        if not product:
            flash("Product not found.", "warning")
            return redirect(url_for("customer.catalog"))

        return render_template(
            "customer/product.html",
            product=product
        )

    except Exception:
        logger.exception("Product details error.")

        flash(
            "Unable to load product details.",
            "danger"
        )

        return redirect(url_for("customer.catalog"))

    finally:
        close_database(connection, cursor)


# ==========================================
# ADD PRODUCT TO CART
# ==========================================

@customer_blueprint.route("/cart/add", methods=["POST"])
def add_to_cart():

    product_id = request.form.get("product_id", type=int)
    quantity = request.form.get("quantity", type=int)

    if (
        product_id is None
        or quantity is None
        or product_id <= 0
        or quantity < 1
    ):
        flash(
            "Please enter a valid product quantity.",
            "warning"
        )
        return redirect(url_for("customer.catalog"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        product_id_column = get_product_primary_key_column(cursor)

        cursor.execute(f"""
            SELECT
                p.`{product_id_column}` AS id,
                p.quantity,
                p.status,
                dc.available_quantity
            FROM tbl_products AS p
            INNER JOIN tbl_daily_catalog AS dc
                ON p.`{product_id_column}` = dc.product_id
            WHERE p.`{product_id_column}` = %s
              AND dc.catalog_date = CURDATE()
        """, (product_id,))

        product = cursor.fetchone()

        if (
            not product
            or product["status"] != "Available"
            or product["quantity"] <= 0
            or product["available_quantity"] <= 0
        ):
            flash(
                "This product is not available today.",
                "warning"
            )

            return redirect(url_for("customer.catalog"))

        cart = get_valid_cart()

        product_key = str(product_id)
        current_quantity = cart.get(product_key, 0)

        maximum_quantity = min(
            int(product["quantity"]),
            int(product["available_quantity"])
        )

        if current_quantity + quantity > maximum_quantity:
            flash(
                "The requested quantity is more than the available stock.",
                "warning"
            )

            return redirect(url_for("customer.catalog"))

        cart[product_key] = current_quantity + quantity
        session["cart"] = cart

        flash(
            "Product added to cart successfully.",
            "success"
        )

        return redirect(url_for("customer.cart"))

    except Exception:
        logger.exception("Add to cart error.")

        flash(
            "Unable to add the product to your cart.",
            "danger"
        )

        return redirect(url_for("customer.catalog"))

    finally:
        close_database(connection, cursor)


# ==========================================
# SHOPPING CART
# ==========================================

@customer_blueprint.route("/cart")
def cart():

    cart_items = []
    total = Decimal("0.00")

    cart_data = get_valid_cart()
    session["cart"] = cart_data

    connection = None
    cursor = None

    try:
        if cart_data:

            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            product_ids = get_product_ids(cart_data)
            product_id_column = get_product_primary_key_column(cursor)

            placeholders = ", ".join(
                ["%s"] * len(product_ids)
            )

            cursor.execute(f"""
                SELECT
                    p.`{product_id_column}` AS id,
                    p.product_name,
                    p.category,
                    p.price,
                    p.quantity,
                    p.status,
                    dc.available_quantity
                FROM tbl_products AS p
                LEFT JOIN tbl_daily_catalog AS dc
                    ON p.`{product_id_column}` = dc.product_id
                    AND dc.catalog_date = CURDATE()
                WHERE p.`{product_id_column}` IN ({placeholders})
                ORDER BY p.product_name ASC
            """, product_ids)

            products = cursor.fetchall()

            for product in products:

                product_id = str(product["id"])
                quantity = cart_data[product_id]

                price = Decimal(str(product["price"]))
                subtotal = price * quantity

                daily_quantity = (
                    int(product["available_quantity"])
                    if product["available_quantity"] is not None
                    else 0
                )

                available_quantity = min(
                    int(product["quantity"]),
                    daily_quantity
                )

                is_available = (
                    product["status"] == "Available"
                    and available_quantity >= quantity
                )

                cart_items.append({
                    "id": product["id"],
                    "product_name": product["product_name"],
                    "category": product["category"],
                    "price": price,
                    "quantity": quantity,
                    "subtotal": subtotal,
                    "available": is_available
                })

                total += subtotal

        return render_template(
            "customer/cart.html",
            cart_items=cart_items,
            total=total
        )

    except Exception:
        logger.exception("Shopping cart error.")

        flash(
            "Unable to load your shopping cart.",
            "danger"
        )

        return redirect(url_for("customer.catalog"))

    finally:
        close_database(connection, cursor)


# ==========================================
# REMOVE PRODUCT FROM CART
# ==========================================

@customer_blueprint.route(
    "/cart/remove/<int:product_id>",
    methods=["POST"]
)
def remove_from_cart(product_id):

    cart_data = get_valid_cart()

    cart_data.pop(str(product_id), None)

    session["cart"] = cart_data

    flash(
        "Product removed from cart.",
        "success"
    )

    return redirect(url_for("customer.cart"))


# ==========================================
# CUSTOMER CHECKOUT
# ==========================================

@customer_blueprint.route("/checkout")
def checkout():

    cart_data = get_valid_cart()
    session["cart"] = cart_data

    if not cart_data:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("customer.catalog"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        product_ids = get_product_ids(cart_data)
        product_id_column = get_product_primary_key_column(cursor)

        placeholders = ", ".join(
            ["%s"] * len(product_ids)
        )

        cursor.execute(f"""
            SELECT
                p.`{product_id_column}` AS id,
                p.product_name,
                p.category,
                p.price,
                p.quantity,
                p.status,
                dc.available_quantity
            FROM tbl_products AS p
            INNER JOIN tbl_daily_catalog AS dc
                ON p.`{product_id_column}` = dc.product_id
            WHERE p.`{product_id_column}` IN ({placeholders})
              AND dc.catalog_date = CURDATE()
            ORDER BY p.`{product_id_column}`
        """, product_ids)

        products = cursor.fetchall()

        if len(products) != len(cart_data):
            flash(
                "Some products in your cart are no longer available.",
                "warning"
            )

            return redirect(url_for("customer.cart"))

        cart_items = []
        total = Decimal("0.00")

        for product in products:

            product_id = str(product["id"])
            quantity = cart_data[product_id]

            if product["status"] != "Available":
                flash(
                    f"{product['product_name']} is unavailable.",
                    "warning"
                )

                return redirect(url_for("customer.cart"))

            available_quantity = min(
                int(product["quantity"]),
                int(product["available_quantity"])
            )

            if quantity > available_quantity:
                flash(
                    f"Not enough stock for {product['product_name']}.",
                    "warning"
                )

                return redirect(url_for("customer.cart"))

            price = Decimal(str(product["price"]))
            subtotal = price * quantity

            cart_items.append({
                "id": product["id"],
                "product_name": product["product_name"],
                "category": product["category"],
                "price": price,
                "quantity": quantity,
                "subtotal": subtotal
            })

            total += subtotal

        return render_template(
            "customer/checkout.html",
            cart_items=cart_items,
            total=total,
            customer_name=session.get("name", "Customer"),
            pickup_only=True
        )

    except Exception:
        logger.exception("Customer checkout error.")

        flash(
            "Unable to load checkout.",
            "danger"
        )

        return redirect(url_for("customer.cart"))

    finally:
        close_database(connection, cursor)


# ==========================================
# PLACE ORDER
# ==========================================

@customer_blueprint.route("/place-order", methods=["POST"])
def place_order():

    cart_data = get_valid_cart()

    if not cart_data:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("customer.catalog"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        connection.start_transaction()

        product_ids = get_product_ids(cart_data)
        product_id_column = get_product_primary_key_column(cursor)

        placeholders = ", ".join(
            ["%s"] * len(product_ids)
        )

        cursor.execute(f"""
            SELECT
                p.`{product_id_column}` AS id,
                p.product_name,
                p.price,
                p.quantity,
                p.status,
                dc.available_quantity
            FROM tbl_products AS p
            INNER JOIN tbl_daily_catalog AS dc
                ON p.`{product_id_column}` = dc.product_id
            WHERE p.`{product_id_column}` IN ({placeholders})
              AND dc.catalog_date = CURDATE()
            ORDER BY p.`{product_id_column}`
            FOR UPDATE
        """, product_ids)

        products = cursor.fetchall()

        if len(products) != len(cart_data):
            raise ValueError(
                "Some products are no longer available."
            )

        order_items = []
        total = Decimal("0.00")

        for product in products:

            product_id = product["id"]
            quantity = cart_data[str(product_id)]

            if product["status"] != "Available":
                raise ValueError(
                    f"{product['product_name']} is unavailable."
                )

            if (
                quantity > product["quantity"]
                or quantity > product["available_quantity"]
            ):
                raise ValueError(
                    f"Not enough stock for {product['product_name']}."
                )

            price = Decimal(str(product["price"]))
            subtotal = price * quantity

            order_items.append({
                "id": product_id,
                "quantity": quantity,
                "price": price,
                "subtotal": subtotal,
                "previous_quantity": int(product["quantity"]),
                "product_name": product["product_name"]
            })

            total += subtotal

        if total <= Decimal("0.00"):
            raise ValueError("Invalid order total.")

        # GENERATE CUSTOM ORDER CODE
        order_code = generate_custom_code(
            cursor,
            "tbl_sales"
        )

        # CREATE ORDER
        cursor.execute("""
            INSERT INTO tbl_sales
            (
                order_code,
                user_id,
                total_amount,
                status
            )
            VALUES (%s, %s, %s, %s)
        """, (
            order_code,
            session["user_id"],
            total,
            "Pending"
        ))

        sale_id = cursor.lastrowid

        for item in order_items:

            # GENERATE CUSTOM SALE ITEM CODE
            item_code = generate_custom_code(
                cursor,
                "tbl_sale_items"
            )

            # CREATE ORDER ITEM
            cursor.execute("""
                INSERT INTO tbl_sale_items
                (
                    item_code,
                    sale_id,
                    product_id,
                    quantity,
                    price,
                    subtotal
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                item_code,
                sale_id,
                item["id"],
                item["quantity"],
                item["price"],
                item["subtotal"]
            ))

            new_quantity = (
                item["previous_quantity"] - item["quantity"]
            )

            new_status = (
                "Available"
                if new_quantity > 0
                else "Unavailable"
            )

            # UPDATE PRODUCT STOCK
            cursor.execute("""
                UPDATE tbl_products
                SET quantity = %s,
                    status = %s
                WHERE id = %s
            """, (
                new_quantity,
                new_status,
                item["id"]
            ))

            # UPDATE DAILY CATALOG STOCK
            cursor.execute("""
                UPDATE tbl_daily_catalog
                SET available_quantity =
                    available_quantity - %s
                WHERE product_id = %s
                  AND catalog_date = CURDATE()
                  AND available_quantity >= %s
            """, (
                item["quantity"],
                item["id"],
                item["quantity"]
            ))

            if cursor.rowcount != 1:
                raise ValueError(
                    f"Daily catalog stock changed for "
                    f"{item['product_name']}. Please review your cart."
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
                item["id"],
                "Stock Out",
                item["previous_quantity"],
                item["quantity"],
                new_quantity,
                f"Customer order {order_code}"
            ))

        connection.commit()

        session.pop("cart", None)

        flash(
            f"Your order {order_code} has been placed successfully.",
            "success"
        )

        return redirect(
            url_for(
                "payment.checkout",
                sale_id=sale_id
            )
        )

    except ValueError as error:

        if connection is not None:
            connection.rollback()

        flash(str(error), "warning")

        return redirect(url_for("customer.cart"))

    except Exception:
        if connection is not None:
            connection.rollback()

        logger.exception("Place order error.")

        flash(
            "Something went wrong while placing your order. Please try again.",
            "danger"
        )

        return redirect(url_for("customer.cart"))

    finally:
        close_database(connection, cursor)


# ==========================================
# CUSTOMER ORDER CANCELLATION
# ==========================================

@customer_blueprint.route(
    "/orders/<int:sale_id>/cancel",
    methods=["POST"]
)
def cancel_order(sale_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        connection.start_transaction()

        cursor.execute("""
            SELECT
                id,
                order_code,
                user_id,
                total_amount,
                status
            FROM tbl_sales
            WHERE id = %s
              AND user_id = %s
            FOR UPDATE
        """, (
            sale_id,
            session["user_id"]
        ))

        sale = cursor.fetchone()

        if not sale:
            raise ValueError("Order not found.")

        order_code = sale["order_code"]

        if sale["status"] == "Cancelled":
            raise ValueError(
                "This order has already been cancelled."
            )

        cursor.execute("""
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN payment_status = 'Verified'
                            THEN amount
                            ELSE 0
                        END
                    ), 0
                ) AS verified_total,
                COALESCE(
                    SUM(
                        CASE
                            WHEN payment_status = 'Pending'
                            THEN amount
                            ELSE 0
                        END
                    ), 0
                ) AS pending_total
            FROM tbl_payments
            WHERE sale_id = %s
        """, (sale_id,))

        payment_totals = cursor.fetchone()

        verified_total = Decimal(
            str(payment_totals["verified_total"])
        )

        pending_total = Decimal(
            str(payment_totals["pending_total"])
        )

        if verified_total > 0:
            raise ValueError(
                "This order has a verified payment. "
                "Please contact the shop for assistance."
            )

        if pending_total > 0:
            raise ValueError(
                "Your payment is still being checked. "
                "Please wait for the result before cancelling."
            )

        if sale["status"] not in (
            "Pending",
            "Payment Rejected"
        ):
            raise ValueError(
                "This order cannot be cancelled at its current status."
            )

        cursor.execute("""
            SELECT
                product_id,
                quantity
            FROM tbl_sale_items
            WHERE sale_id = %s
            ORDER BY product_id
            FOR UPDATE
        """, (sale_id,))

        order_items = cursor.fetchall()

        if not order_items:
            raise ValueError(
                "No order items were found. Please contact the shop."
            )

        for item in order_items:

            product_id = item["product_id"]
            quantity_to_restore = int(item["quantity"])

            if quantity_to_restore <= 0:
                raise ValueError("Invalid order quantity.")

            cursor.execute("""
                SELECT
                    id,
                    product_name,
                    quantity
                FROM tbl_products
                WHERE id = %s
                FOR UPDATE
            """, (product_id,))

            product = cursor.fetchone()

            if not product:
                raise ValueError(
                    "An order product could not be found."
                )

            previous_quantity = int(product["quantity"])

            new_quantity = (
                previous_quantity + quantity_to_restore
            )

            new_status = (
                "Available"
                if new_quantity > 0
                else "Unavailable"
            )

            # RESTORE PRODUCT STOCK
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

            # RESTORE TODAY'S DAILY CATALOG STOCK
            cursor.execute("""
                UPDATE tbl_daily_catalog
                SET available_quantity = LEAST(
                    available_quantity + %s,
                    %s
                )
                WHERE product_id = %s
                  AND catalog_date = CURDATE()
            """, (
                quantity_to_restore,
                new_quantity,
                product_id
            ))

            # GENERATE CUSTOM STOCK HISTORY CODE
            stock_code = generate_custom_code(
                cursor,
                "tbl_stock_history"
            )

            # RECORD RESTORED STOCK
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
                quantity_to_restore,
                new_quantity,
                f"Order {order_code} cancelled - stock restored"
            ))

        # UPDATE ORDER STATUS
        cursor.execute("""
            UPDATE tbl_sales
            SET status = 'Cancelled'
            WHERE id = %s
              AND user_id = %s
              AND status IN (
                  'Pending',
                  'Payment Rejected'
              )
        """, (
            sale_id,
            session["user_id"]
        ))

        if cursor.rowcount != 1:
            raise ValueError(
                "The order status changed. Please refresh your orders."
            )

        connection.commit()

        flash(
            f"Order {order_code} has been cancelled successfully. "
            "The stock has been restored.",
            "success"
        )

    except ValueError as error:

        if connection is not None:
            connection.rollback()

        flash(str(error), "warning")

    except Exception:
        if connection is not None:
            connection.rollback()

        logger.exception("Customer order cancellation error.")

        flash(
            "Unable to cancel this order right now. Please try again.",
            "danger"
        )

    finally:
        close_database(connection, cursor)

    return redirect(url_for("customer.my_orders"))


# ==========================================
# CUSTOMER ORDER HISTORY
# ==========================================

@customer_blueprint.route("/orders")
def my_orders():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                order_code,
                order_date,
                total_amount,
                status
            FROM tbl_sales
            WHERE user_id = %s
            ORDER BY order_date DESC
        """, (session["user_id"],))

        orders = cursor.fetchall()

        return render_template(
            "customer/orders.html",
            orders=orders
        )

    except Exception:
        logger.exception("Customer orders error.")

        flash(
            "Unable to load your orders.",
            "danger"
        )

        return redirect(url_for("customer.dashboard"))

    finally:
        close_database(connection, cursor)