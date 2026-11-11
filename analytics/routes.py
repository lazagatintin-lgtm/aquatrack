from datetime import date, datetime, timedelta
from decimal import Decimal

import mysql.connector

from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    session,
    current_app,
    request
)

from . import analytics_blueprint
from database.db import get_db_connection


MAX_ANALYTICS_MONTHS = 60


# ==========================================
# ADMIN ACCESS PROTECTION
# ==========================================

@analytics_blueprint.before_request
def require_admin():

    if not session.get("user_id"):
        flash(
            "You must log in before accessing the dashboard.",
            "danger"
        )
        return redirect(url_for("auth.login"))

    if session.get("role") != "admin":
        flash(
            "Please log in as an administrator.",
            "danger"
        )
        return redirect(url_for("auth.login"))


# ==========================================
# DATABASE CLEANUP
# ==========================================

def close_database(connection, cursor):

    if cursor is not None:
        try:
            cursor.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "ANALYTICS CURSOR CLOSE ERROR"
            )

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "ANALYTICS CONNECTION CLOSE ERROR"
            )


def parse_date_filter(value, field_name):
    if not value:
        return None

    try:
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(
            f"Please enter a valid {field_name} date."
        )

    if parsed_date.isoformat() != value:
        raise ValueError(
            f"Please enter a valid {field_name} date."
        )

    if parsed_date < date(1000, 1, 1):
        raise ValueError(
            f"The {field_name} date must be on or after January 1, 1000."
        )

    return parsed_date


def get_month_range(start_date, end_date):
    month_difference = (
        (end_date.year - start_date.year) * 12
        + end_date.month
        - start_date.month
    )

    if month_difference >= MAX_ANALYTICS_MONTHS:
        raise ValueError(
            "Choose a date range within five years."
        )

    current_month = date(start_date.year, start_date.month, 1)
    last_month = date(end_date.year, end_date.month, 1)
    months = []

    while current_month <= last_month:
        months.append(current_month.strftime("%Y-%m"))
        if current_month.month == 12:
            current_month = date(current_month.year + 1, 1, 1)
        else:
            current_month = date(
                current_month.year,
                current_month.month + 1,
                1
            )

    return months


# ==========================================
# ANALYTICS DASHBOARD
# ==========================================

@analytics_blueprint.route("/")
def dashboard():

    today = date.today()
    default_end = today
    default_start_month_index = (
        today.year * 12 + today.month - 1 - 11
    )
    default_start = date(
        default_start_month_index // 12,
        default_start_month_index % 12 + 1,
        1
    )

    has_start_filter = "from_date" in request.args
    has_end_filter = "to_date" in request.args

    try:
        if has_start_filter != has_end_filter:
            raise ValueError("Select both a start date and an end date.")

        if has_start_filter:
            start_date = parse_date_filter(
                request.args.get("from_date", ""),
                "start"
            )
            end_date = parse_date_filter(
                request.args.get("to_date", ""),
                "end"
            )

            if start_date is None or end_date is None:
                raise ValueError(
                    "Select both a start date and an end date."
                )
        else:
            start_date = default_start
            end_date = default_end

        if start_date > end_date:
            raise ValueError(
                "The start date must be on or before the end date."
            )

        if end_date == date.max:
            raise ValueError(
                "The end date is outside the supported range."
            )

        months = get_month_range(start_date, end_date)

    except ValueError as error:
        flash(str(error), "danger")
        return redirect(url_for("analytics.dashboard"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        end_exclusive = end_date + timedelta(days=1)

        cursor.execute("""
            SELECT
                COUNT(*) AS total_products,
                COALESCE(SUM(quantity), 0) AS total_stock,
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
                ), 0) AS low_stock_products,
                COALESCE(SUM(
                    CASE
                        WHEN quantity <= 0 THEN 1
                        ELSE 0
                    END
                ), 0) AS out_of_stock_products,
                COALESCE(SUM(
                    CASE
                        WHEN max_stock IS NOT NULL
                         AND quantity > max_stock THEN 1
                        ELSE 0
                    END
                ), 0) AS over_stock_products,
                COALESCE(SUM(
                    CASE
                        WHEN max_stock IS NOT NULL
                         AND quantity > max_stock
                        THEN quantity - max_stock
                        ELSE 0
                    END
                ), 0) AS excess_stock_units,
                COALESCE(SUM(price * quantity), 0) AS inventory_value
            FROM tbl_products
        """)
        inventory_snapshot = cursor.fetchone()

        # Income is grouped by when the payment was verified, not by order date.
        cursor.execute("""
            SELECT
                DATE_FORMAT(
                    COALESCE(p.verified_at, p.payment_date),
                    '%Y-%m'
                ) AS month,
                COUNT(p.id) AS verified_payments,
                COALESCE(SUM(p.amount), 0) AS total_income
            FROM tbl_payments AS p
            INNER JOIN tbl_sales AS s
                ON s.id = p.sale_id
            WHERE p.payment_status = 'Verified'
              AND s.status != 'Cancelled'
              AND COALESCE(p.verified_at, p.payment_date) >= %s
              AND COALESCE(p.verified_at, p.payment_date) < %s
            GROUP BY DATE_FORMAT(
                COALESCE(p.verified_at, p.payment_date),
                '%Y-%m'
            )
            ORDER BY month ASC
        """, (start_date, end_exclusive))
        sales_by_month = {
            row["month"]: row
            for row in cursor.fetchall()
            if row["month"]
        }

        cursor.execute("""
            SELECT
                DATE_FORMAT(loss_date, '%Y-%m') AS month,
                COALESCE(SUM(quantity), 0) AS total_lost
            FROM tbl_inventory_losses
            WHERE loss_date >= %s
              AND loss_date < %s
            GROUP BY DATE_FORMAT(loss_date, '%Y-%m')
            ORDER BY month ASC
        """, (start_date, end_exclusive))
        losses_by_month = {
            row["month"]: row
            for row in cursor.fetchall()
            if row["month"]
        }

        cursor.execute("""
            SELECT
                DATE_FORMAT(created_at, '%Y-%m') AS month,
                COALESCE(
                    SUM(
                        CASE
                            WHEN change_type = 'Stock In'
                            THEN changed_quantity
                            ELSE 0
                        END
                    ), 0
                ) AS total_stock_in,
                COALESCE(
                    SUM(
                        CASE
                            WHEN change_type = 'Stock Out'
                            THEN changed_quantity
                            ELSE 0
                        END
                    ), 0
                ) AS total_stock_out
            FROM tbl_stock_history
            WHERE created_at >= %s
              AND created_at < %s
            GROUP BY DATE_FORMAT(created_at, '%Y-%m')
            ORDER BY month ASC
        """, (start_date, end_exclusive))
        stock_by_month = {
            row["month"]: row
            for row in cursor.fetchall()
            if row["month"]
        }

        monthly_sales = []
        monthly_losses = []
        monthly_stock = []

        for month in months:
            sale = sales_by_month.get(month, {})
            loss = losses_by_month.get(month, {})
            stock = stock_by_month.get(month, {})
            month_label = datetime.strptime(
                month,
                "%Y-%m"
            ).strftime("%b %Y")

            monthly_sales.append({
                "month": month,
                "month_label": month_label,
                "verified_payments": int(
                    sale.get("verified_payments") or 0
                ),
                "total_income": Decimal(
                    str(sale.get("total_income") or 0)
                )
            })
            monthly_losses.append({
                "month": month,
                "month_label": month_label,
                "total_lost": int(loss.get("total_lost") or 0)
            })
            monthly_stock.append({
                "month": month,
                "month_label": month_label,
                "total_stock_in": int(
                    stock.get("total_stock_in") or 0
                ),
                "total_stock_out": int(
                    stock.get("total_stock_out") or 0
                )
            })

        max_income = max(
            (row["total_income"] for row in monthly_sales),
            default=Decimal("0")
        )
        max_loss = max(
            (row["total_lost"] for row in monthly_losses),
            default=0
        )
        max_stock = max(
            (
                max(row["total_stock_in"], row["total_stock_out"])
                for row in monthly_stock
            ),
            default=0
        )

        for row in monthly_sales:
            row["bar_width"] = (
                float(row["total_income"] / max_income * 100)
                if max_income else 0
            )

        for row in monthly_losses:
            row["bar_width"] = (
                row["total_lost"] / max_loss * 100
                if max_loss else 0
            )

        for row in monthly_stock:
            row["stock_in_width"] = (
                row["total_stock_in"] / max_stock * 100
                if max_stock else 0
            )
            row["stock_out_width"] = (
                row["total_stock_out"] / max_stock * 100
                if max_stock else 0
            )

        total_income = sum(
            (row["total_income"] for row in monthly_sales),
            Decimal("0.00")
        )
        total_verified_payments = sum(
            row["verified_payments"]
            for row in monthly_sales
        )
        total_lost = sum(
            row["total_lost"]
            for row in monthly_losses
        )
        total_stock_in = sum(
            row["total_stock_in"]
            for row in monthly_stock
        )
        total_stock_out = sum(
            row["total_stock_out"]
            for row in monthly_stock
        )

        return render_template(
            "analytics/dashboard.html",
            monthly_sales=monthly_sales,
            monthly_losses=monthly_losses,
            monthly_stock=monthly_stock,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            has_income_records=bool(sales_by_month),
            has_loss_records=bool(losses_by_month),
            has_stock_records=bool(stock_by_month),
            total_income=total_income,
            total_verified_payments=total_verified_payments,
            total_lost=total_lost,
            total_stock_in=total_stock_in,
            total_stock_out=total_stock_out,
            inventory_snapshot=inventory_snapshot
        )

    except mysql.connector.Error:
        current_app.logger.exception(
            "ANALYTICS DATABASE ERROR"
        )

        flash(
            "Unable to load analytics data. Please try again.",
            "error"
        )

        return redirect(url_for("admin.dashboard"))

    except Exception:
        current_app.logger.exception(
            "UNEXPECTED ANALYTICS ERROR"
        )

        flash(
            "An unexpected error occurred while loading analytics.",
            "error"
        )

        return redirect(url_for("admin.dashboard"))

    finally:
        close_database(connection, cursor)
