import logging

from decimal import Decimal, InvalidOperation
from mysql.connector import Error


logger = logging.getLogger(__name__)


def update_sale_payment_status(cursor, sale_id):
    """
    Update a sale's status based on its payment records.

    Requirements:
    - Dictionary cursor.
    - Active database transaction.
    - Sale row is locked before payment status is updated.

    Supports split payments and preserves cancelled orders.
    The caller is responsible for committing or rolling back
    the database transaction.
    """

    try:
        # VALIDATE SALE ID
        if not sale_id:
            logger.warning(
                "Payment status was not updated because the sale ID is missing."
            )
            return False

        # GET AND LOCK THE SALE
        cursor.execute("""
            SELECT total_amount, status
            FROM tbl_sales
            WHERE id = %s
            FOR UPDATE
        """, (sale_id,))

        sale = cursor.fetchone()

        if not sale:
            logger.warning(
                "Payment status was not updated. Sale ID %s was not found.",
                sale_id
            )
            return False

        # PRESERVE CANCELLED ORDERS
        if sale["status"] == "Cancelled":
            return False

        # VALIDATE SALE TOTAL
        total_amount = Decimal(str(sale["total_amount"]))

        if (
            not total_amount.is_finite()
            or total_amount <= Decimal("0")
        ):
            logger.warning(
                "Invalid total amount for sale ID %s.",
                sale_id
            )
            return False

        # GET PAYMENT TOTALS
        cursor.execute("""
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN payment_status = 'Verified'
                            THEN amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS verified_total,

                COALESCE(
                    SUM(
                        CASE
                            WHEN payment_status = 'Pending'
                            THEN amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS pending_total,

                COALESCE(
                    SUM(
                        CASE
                            WHEN payment_status = 'Rejected'
                            THEN amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS rejected_total

            FROM tbl_payments
            WHERE sale_id = %s
        """, (sale_id,))

        totals = cursor.fetchone()

        if not totals:
            logger.warning(
                "Payment totals could not be retrieved for sale ID %s.",
                sale_id
            )
            return False

        # CONVERT PAYMENT TOTALS
        verified_total = Decimal(str(totals["verified_total"]))
        pending_total = Decimal(str(totals["pending_total"]))
        rejected_total = Decimal(str(totals["rejected_total"]))

        # VALIDATE PAYMENT TOTALS
        payment_totals = (
            verified_total,
            pending_total,
            rejected_total
        )

        if any(
            not amount.is_finite() or amount < Decimal("0")
            for amount in payment_totals
        ):
            logger.warning(
                "Invalid payment totals for sale ID %s.",
                sale_id
            )
            return False

        # DETERMINE THE NEW SALE STATUS
        if verified_total >= total_amount:
            new_status = "Paid"

        elif verified_total > Decimal("0"):
            new_status = "Partially Paid"

        elif pending_total > Decimal("0"):
            new_status = "Payment Pending"

        elif rejected_total > Decimal("0"):
            new_status = "Payment Rejected"

        else:
            new_status = "Pending"

        # UPDATE SALE STATUS
        cursor.execute("""
            UPDATE tbl_sales
            SET status = %s
            WHERE id = %s
              AND status != 'Cancelled'
        """, (
            new_status,
            sale_id
        ))

        logger.info(
            "Sale ID %s payment status updated to %s.",
            sale_id,
            new_status
        )

        return True

    except (Error, InvalidOperation, TypeError, ValueError, KeyError):
        logger.exception(
            "Failed to update payment status for sale ID %s.",
            sale_id
        )
        raise