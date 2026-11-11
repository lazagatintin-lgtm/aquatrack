import logging

from datetime import datetime
from decimal import Decimal

from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    session,
    current_app,
    request
)

from . import reports_blueprint
from database.db import get_db_connection


logger = logging.getLogger(__name__)
SALES_PER_PAGE = 25


def parse_report_date(value, field_name):
    if not value:
        return None

    try:
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"Please enter a valid {field_name} date.")

    if parsed_date.isoformat() != value:
        raise ValueError(f"Please enter a valid {field_name} date.")

    if parsed_date.year < 1000:
        raise ValueError(
            f"The {field_name} date must be on or after January 1, 1000."
        )

    return parsed_date


def get_sales_date_filters():
    start_date = parse_report_date(
        request.args.get("from_date", ""),
        "start"
    )
    end_date = parse_report_date(
        request.args.get("to_date", ""),
        "end"
    )

    if start_date and end_date and start_date > end_date:
        raise ValueError("The start date must be on or before the end date.")

    conditions = []
    parameters = []

    if start_date:
        conditions.append("s.order_date >= %s")
        parameters.append(start_date)

    if end_date:
        conditions.append("s.order_date < DATE_ADD(%s, INTERVAL 1 DAY)")
        parameters.append(end_date)

    return start_date, end_date, conditions, parameters


# ==========================================
# ADMIN ACCESS PROTECTION
# ==========================================

@reports_blueprint.before_request
def require_admin():

    if not session.get("user_id"):
        flash(
            "You must log in before accessing the dashboard.",
            "danger"
        )

        return redirect(
            url_for("auth.login")
        )

    if session.get("role") != "admin":
        flash(
            "Please log in as an administrator.",
            "danger"
        )

        return redirect(
            url_for("auth.login")
        )


# ==========================================
# DATABASE CLEANUP
# ==========================================

def close_database(connection, cursor):

    if cursor is not None:
        try:
            cursor.close()

        except Exception:
            logger.exception(
                "REPORT CURSOR CLOSE ERROR"
            )

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()

        except Exception:
            logger.exception(
                "REPORT CONNECTION CLOSE ERROR"
            )


# ==========================================
# SALES REPORT
# ==========================================

@reports_blueprint.route("/sales")
def sales_report():

    connection = None
    cursor = None

    try:
        start_date, end_date, date_conditions, date_parameters = (
            get_sales_date_filters()
        )

        try:
            page = int(request.args.get("page", "1"))
        except (TypeError, ValueError):
            raise ValueError("Please enter a valid report page.")

        if page < 1:
            raise ValueError("Please enter a valid report page.")

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        where_clause = (
            "WHERE " + " AND ".join(date_conditions)
            if date_conditions
            else ""
        )

        cursor.execute(f"""
            SELECT COALESCE(SUM(payment_totals.verified_total), 0)
                AS total_verified
            FROM tbl_sales AS s
            LEFT JOIN (
                SELECT sale_id, SUM(amount) AS verified_total
                FROM tbl_payments
                WHERE payment_status = 'Verified'
                GROUP BY sale_id
            ) AS payment_totals
                ON payment_totals.sale_id = s.id
            {where_clause}
        """, tuple(date_parameters))
        total_sales = Decimal(
            str(cursor.fetchone()["total_verified"] or 0)
        )

        cursor.execute(f"""
            SELECT COUNT(*) AS total_records
            FROM tbl_sales AS s
            {where_clause}
        """, tuple(date_parameters))
        total_records = int(cursor.fetchone()["total_records"])
        total_pages = max(
            1,
            (total_records + SALES_PER_PAGE - 1) // SALES_PER_PAGE
        )
        page = min(page, total_pages)
        offset = (page - 1) * SALES_PER_PAGE

        cursor.execute(f"""
            SELECT
                s.id,
                s.order_code,
                s.user_id,
                u.user_code,
                s.total_amount,
                s.status,
                s.order_date,
                COALESCE(payment_totals.verified_total, 0)
                    AS verified_total
            FROM tbl_sales AS s
            LEFT JOIN tbl_users AS u
                ON s.user_id = u.id
            LEFT JOIN (
                SELECT sale_id, SUM(amount) AS verified_total
                FROM tbl_payments
                WHERE payment_status = 'Verified'
                GROUP BY sale_id
            ) AS payment_totals
                ON payment_totals.sale_id = s.id
            {where_clause}
            ORDER BY s.order_date DESC, s.id DESC
            LIMIT %s OFFSET %s
        """, tuple(date_parameters + [SALES_PER_PAGE, offset]))
        sales = cursor.fetchall()

        return render_template(
            "reports/sales.html",
            sales=sales,
            total_sales=total_sales,
            total_records=total_records,
            page=page,
            total_pages=total_pages,
            from_date=start_date.isoformat() if start_date else "",
            to_date=end_date.isoformat() if end_date else ""
        )

    except ValueError as error:
        flash(str(error), "warning")
        return redirect(url_for("reports.sales_report"))

    except Exception:
        current_app.logger.exception(
            "SALES REPORT ERROR"
        )

        flash(
            "Unable to load sales report.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(
            connection,
            cursor
        )


# ==========================================
# INVENTORY REPORT
# ==========================================

@reports_blueprint.route("/inventory")
def inventory_report():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                product_code,
                product_name,
                category,
                description,
                price,
                quantity,
                min_stock,
                max_stock,
                status,
                created_at

            FROM tbl_products

            ORDER BY product_name ASC
        """)

        products = cursor.fetchall()

        total_products = len(products)
        total_stock = sum(
            int(product["quantity"] or 0)
            for product in products
        )
        available_products = sum(
            1
            for product in products
            if (
                int(product["quantity"] or 0)
                > int(product["min_stock"] or 0)
                and (
                    product["max_stock"] is None
                    or int(product["quantity"] or 0)
                    <= int(product["max_stock"])
                )
            )
        )
        low_stock_products = sum(
            1
            for product in products
            if 0 < int(product["quantity"] or 0) <= int(product["min_stock"] or 0)
        )
        out_of_stock_products = sum(
            1
            for product in products
            if int(product["quantity"] or 0) <= 0
        )
        over_stock_products = sum(
            1
            for product in products
            if (
                product["max_stock"] is not None
                and int(product["quantity"] or 0)
                > int(product["max_stock"])
            )
        )
        inventory_value = sum(
            (
                Decimal(str(product["price"] or 0))
                * int(product["quantity"] or 0)
                for product in products
            ),
            Decimal("0.00")
        )

        return render_template(
            "reports/inventory_report.html",
            products=products,
            total_products=total_products,
            total_stock=total_stock,
            available_products=available_products,
            low_stock_products=low_stock_products,
            out_of_stock_products=out_of_stock_products,
            over_stock_products=over_stock_products,
            inventory_value=inventory_value
        )

    except Exception:
        current_app.logger.exception(
            "INVENTORY REPORT ERROR"
        )

        flash(
            "Unable to load inventory report.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(
            connection,
            cursor
        )


# ==========================================
# INVENTORY LOSS REPORT
# ==========================================

@reports_blueprint.route("/losses")
def losses_report():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                l.id,
                l.loss_code,
                l.product_id,
                p.product_code,
                p.product_name,
                l.quantity,
                l.reason,
                l.loss_date,
                l.recorded_at

            FROM tbl_inventory_losses AS l

            LEFT JOIN tbl_products AS p
                ON l.product_id = p.id

            ORDER BY
                l.loss_date DESC,
                l.id DESC
        """)

        losses = cursor.fetchall()

        return render_template(
            "reports/losses.html",
            losses=losses
        )

    except Exception:
        current_app.logger.exception(
            "INVENTORY LOSS REPORT ERROR"
        )

        flash(
            "Unable to load inventory loss report.",
            "error"
        )

        return redirect(
            url_for("admin.dashboard")
        )

    finally:
        close_database(
            connection,
            cursor
        )