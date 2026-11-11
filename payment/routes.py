import os
import uuid
from decimal import Decimal, InvalidOperation

from flask import (
    current_app,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from mysql.connector import Error

from . import payment_blueprint
from payment.status import update_sale_payment_status

from database.db import (
    get_db_connection,
    generate_custom_code
)

from auth.otp import (
    generate_otp,
    save_otp,
    is_valid_otp,
    verify_otp_for_transaction,
    can_resend_otp
)

from auth.email_service import send_otp_email


# PAYMENT SETTINGS
PAYMENT_METHODS = {
    "Cash on Pickup",
    "GCash"
}

ONLINE_PAYMENT_METHODS = {
    "GCash"
}

MAX_PROOF_SIZE = 5 * 1024 * 1024
MAX_PAYMENT_ITEMS = 2
PROOF_FOLDER = "payment_proofs"


# DATABASE CLEANUP
def close_database(connection, cursor):

    if cursor is not None:
        try:
            cursor.close()
        except Error:
            current_app.logger.exception(
                "PAYMENT CURSOR CLOSE ERROR"
            )

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except Error:
            current_app.logger.exception(
                "PAYMENT CONNECTION CLOSE ERROR"
            )


# REQUIRE LOGIN
@payment_blueprint.before_request
def require_login():

    if not session.get("user_id"):
        flash(
            "Please log in to continue.",
            "error"
        )

        return redirect(
            url_for("auth.login")
        )


# CHECK CUSTOMER ACCESS
def require_customer():

    if session.get("role") != "customer":
        flash(
            "You do not have permission to access this page.",
            "error"
        )

        return False

    return True


# VALIDATE PAYMENT AMOUNT
def parse_payment_amount(value):

    try:
        amount = Decimal(str(value).strip())

        if (
            not amount.is_finite()
            or amount <= 0
            or amount.as_tuple().exponent < -2
        ):
            raise ValueError

        return amount.quantize(Decimal("0.01"))

    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            "Please enter valid payment amounts."
        )


# VALIDATE IMAGE FILE
def is_valid_image(file):

    file.seek(0)
    header = file.read(8)
    file.seek(0)

    is_png = header.startswith(
        b"\x89PNG\r\n\x1a\n"
    )

    is_jpeg = header.startswith(
        b"\xff\xd8\xff"
    )

    return is_png or is_jpeg


# SAVE PAYMENT PROOF
def save_payment_proof(file):

    if not file or not file.filename:
        return None

    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size <= 0:
        raise ValueError(
            "The uploaded payment screenshot is empty."
        )

    if file_size > MAX_PROOF_SIZE:
        raise ValueError(
            "Payment screenshot must not exceed 5MB."
        )

    if not is_valid_image(file):
        raise ValueError(
            "Please upload a valid JPG, JPEG, or PNG image."
        )

    header = file.read(8)
    file.seek(0)

    extension = (
        ".png"
        if header.startswith(b"\x89PNG\r\n\x1a\n")
        else ".jpg"
    )

    folder = os.path.join(
        current_app.instance_path,
        PROOF_FOLDER
    )

    os.makedirs(folder, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{extension}"

    file_path = os.path.join(
        folder,
        filename
    )

    file.save(file_path)

    return f"{PROOF_FOLDER}/{filename}"


# VALIDATE PAYMENT PROOF PATH
def get_payment_proof_path(proof_path):

    if not isinstance(proof_path, str) or not proof_path:
        return None

    normalized_path = proof_path.replace("\\", "/")

    parts = normalized_path.split("/")

    if (
        len(parts) != 2
        or parts[0] != PROOF_FOLDER
        or not parts[1]
        or parts[1] in (".", "..")
    ):
        return None

    filename = parts[1]

    if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return None

    expected_folder = os.path.realpath(
        os.path.join(
            current_app.instance_path,
            PROOF_FOLDER
        )
    )

    full_path = os.path.realpath(
        os.path.join(
            expected_folder,
            filename
        )
    )

    try:
        if os.path.commonpath(
            [expected_folder, full_path]
        ) != expected_folder:
            return None

    except ValueError:
        return None

    return full_path


# DELETE PAYMENT PROOF
def delete_payment_proof(proof_path):

    full_path = get_payment_proof_path(proof_path)

    if not full_path:
        return

    try:
        if os.path.isfile(full_path):
            os.remove(full_path)

    except OSError:
        current_app.logger.exception(
            "Unable to delete payment proof."
        )


# DELETE TEMPORARY PAYMENT PROOFS
def delete_pending_proofs(payment_data):

    if not isinstance(payment_data, dict):
        return

    payment_items = payment_data.get(
        "payments",
        []
    )

    if not isinstance(payment_items, list):
        return

    for item in payment_items:

        if isinstance(item, dict):
            delete_payment_proof(
                item.get("proof_path")
            )


# GET PAYMENT BALANCE
def get_payment_balance(cursor, sale_id):

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
            ) AS pending_total

        FROM tbl_payments
        WHERE sale_id = %s
    """, (sale_id,))

    result = cursor.fetchone()

    verified_total = Decimal(
        str(result["verified_total"])
    )

    pending_total = Decimal(
        str(result["pending_total"])
    )

    return verified_total, pending_total


# GET CUSTOMER ORDER
def get_customer_sale(cursor, sale_id):

    cursor.execute("""
        SELECT
            id,
            order_code,
            user_id,
            total_amount,
            status,
            order_date
        FROM tbl_sales
        WHERE id = %s
          AND user_id = %s
    """, (
        sale_id,
        session["user_id"]
    ))

    return cursor.fetchone()


# INVALIDATE PAYMENT OTP
def invalidate_payment_otp(user_id):

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE tbl_email_otps
            SET is_used = 1
            WHERE user_id = %s
              AND purpose = 'payment'
              AND is_used = 0
        """, (user_id,))

        connection.commit()
        return True

    except Exception:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "INVALIDATE PAYMENT OTP ERROR"
        )

        return False

    finally:
        close_database(connection, cursor)


# VALIDATE PENDING PAYMENT SESSION
def validate_pending_payment_items(payment_items):

    if (
        not isinstance(payment_items, list)
        or not payment_items
        or len(payment_items) > MAX_PAYMENT_ITEMS
    ):
        raise ValueError(
            "Invalid payment details."
        )

    payment_total = Decimal("0.00")
    selected_methods = set()

    for item in payment_items:

        if not isinstance(item, dict):
            raise ValueError(
                "Invalid payment details."
            )

        method = item.get("payment_method")

        if (
            method not in PAYMENT_METHODS
            or method in selected_methods
        ):
            raise ValueError(
                "Invalid payment details."
            )

        amount = parse_payment_amount(
            item.get("amount", "0")
        )

        selected_methods.add(method)
        payment_total += amount

        if method in ONLINE_PAYMENT_METHODS:

            reference_number = item.get(
                "reference_number"
            )

            proof_path = item.get(
                "proof_path"
            )

            if (
                not isinstance(reference_number, str)
                or not reference_number.strip()
                or len(reference_number) > 100
                or not get_payment_proof_path(proof_path)
            ):
                raise ValueError(
                    "Online payment details are incomplete."
                )

        else:
            if (
                item.get("reference_number")
                or item.get("proof_path")
            ):
                raise ValueError(
                    "Invalid cash payment details."
                )

    return payment_total


# CUSTOMER PAYMENT CHECKOUT
@payment_blueprint.route(
    "/checkout/<int:sale_id>",
    methods=["GET", "POST"]
)
def checkout(sale_id):

    if not require_customer():
        return redirect(
            url_for("customer.dashboard")
        )

    connection = None
    cursor = None
    uploaded_proofs = []

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        sale = get_customer_sale(
            cursor,
            sale_id
        )

        if not sale:
            flash(
                "Order not found.",
                "error"
            )

            return redirect(
                url_for("customer.dashboard")
            )

        if sale["status"] == "Cancelled":
            flash(
                "This order has already been cancelled. Payment is no longer available.",
                "error"
            )

            return redirect(
                url_for("customer.my_orders")
            )

        verified_total, pending_total = get_payment_balance(
            cursor,
            sale_id
        )

        total_amount = Decimal(
            str(sale["total_amount"])
        )

        remaining_balance = total_amount - verified_total

        if remaining_balance <= 0:
            flash(
                "This order is already fully paid.",
                "success"
            )

            return redirect(
                url_for("payment.payment_history")
            )

        if pending_total > 0:
            flash(
                "Your payment is still being checked. Please wait for the result.",
                "error"
            )

            return redirect(
                url_for("payment.payment_history")
            )

        if request.method == "POST":

            payments = []
            selected_methods = set()
            payment_total = Decimal("0.00")

            try:
                for index in (1, 2):

                    method = request.form.get(
                        f"payment_method_{index}",
                        ""
                    ).strip()

                    amount_text = request.form.get(
                        f"amount_{index}",
                        ""
                    ).strip()

                    if not method:
                        if not amount_text:
                            continue

                        try:
                            unused_amount = Decimal(amount_text)
                        except (InvalidOperation, TypeError, ValueError):
                            raise ValueError(
                                "Please enter valid payment amounts."
                            )

                        if (
                            not unused_amount.is_finite()
                            or unused_amount < Decimal("0")
                            or unused_amount.as_tuple().exponent < -2
                        ):
                            raise ValueError(
                                "Please enter valid payment amounts."
                            )

                        if unused_amount == Decimal("0"):
                            continue

                        raise ValueError(
                            "Please select a second payment method or set its amount to zero."
                        )

                    if method not in PAYMENT_METHODS:
                        raise ValueError(
                            "Please select a valid payment method."
                        )

                    if method in selected_methods:
                        raise ValueError(
                            "Please select two different payment methods."
                        )

                    amount = parse_payment_amount(
                        amount_text
                    )

                    selected_methods.add(method)

                    reference_number = ""
                    proof_path = None

                    if method in ONLINE_PAYMENT_METHODS:

                        reference_number = request.form.get(
                            f"reference_number_{index}",
                            ""
                        ).strip()

                        if not reference_number:
                            raise ValueError(
                                f"Please enter the reference number for {method}."
                            )

                        if len(reference_number) > 100:
                            raise ValueError(
                                "Reference number must not exceed 100 characters."
                            )

                        proof_file = request.files.get(
                            f"proof_image_{index}"
                        )

                        if not proof_file or not proof_file.filename:
                            raise ValueError(
                                f"Please upload the payment screenshot for {method}."
                            )

                        proof_path = save_payment_proof(
                            proof_file
                        )

                        uploaded_proofs.append(proof_path)

                    payments.append({
                        "payment_method": method,
                        "amount": str(amount),
                        "reference_number": reference_number,
                        "proof_path": proof_path
                    })

                    payment_total += amount

            except ValueError as error:

                for path in uploaded_proofs:
                    delete_payment_proof(path)

                flash(str(error), "error")

                return redirect(
                    url_for(
                        "payment.checkout",
                        sale_id=sale_id
                    )
                )

            if not payments:
                flash(
                    "Please select at least one payment method.",
                    "error"
                )

                return redirect(
                    url_for(
                        "payment.checkout",
                        sale_id=sale_id
                    )
                )

            if (
                payment_total <= Decimal("0")
                or payment_total > remaining_balance
            ):

                for path in uploaded_proofs:
                    delete_payment_proof(path)

                flash(
                    "The payment total must be greater than zero and cannot exceed your remaining balance.",
                    "error"
                )

                return redirect(
                    url_for(
                        "payment.checkout",
                        sale_id=sale_id
                    )
                )

            if not can_resend_otp(
                session["user_id"],
                "payment"
            ):

                for path in uploaded_proofs:
                    delete_payment_proof(path)

                flash(
                    "Please wait before requesting another payment code.",
                    "error"
                )

                return redirect(
                    url_for(
                        "payment.checkout",
                        sale_id=sale_id
                    )
                )

            otp = generate_otp()

            if not save_otp(
                session["user_id"],
                otp,
                purpose="payment"
            ):

                for path in uploaded_proofs:
                    delete_payment_proof(path)

                flash(
                    "Unable to create your verification code.",
                    "error"
                )

                return redirect(
                    url_for(
                        "payment.checkout",
                        sale_id=sale_id
                    )
                )

            try:
                cursor.execute("""
                    SELECT email
                    FROM tbl_users
                    WHERE id = %s
                """, (session["user_id"],))

                user = cursor.fetchone()

                email_sent = (
                    user is not None
                    and send_otp_email(
                        user["email"],
                        otp,
                        purpose="payment"
                    )
                )

            except Exception:
                current_app.logger.exception(
                    "PAYMENT OTP EMAIL ERROR"
                )

                email_sent = False

            if not email_sent:

                invalidate_payment_otp(
                    session["user_id"]
                )

                for path in uploaded_proofs:
                    delete_payment_proof(path)

                flash(
                    "Unable to send your verification code.",
                    "error"
                )

                return redirect(
                    url_for(
                        "payment.checkout",
                        sale_id=sale_id
                    )
                )

            old_pending_payment = session.get(
                "pending_payment"
            )

            if old_pending_payment:
                delete_pending_proofs(
                    old_pending_payment
                )

            session["pending_payment"] = {
                "sale_id": sale_id,
                "payments": payments
            }

            flash(
                "We sent a verification code to your registered email.",
                "success"
            )

            return redirect(
                url_for("payment.verify_payment_otp")
            )

        return render_template(
            "payment/checkout.html",
            sale=sale,
            remaining_balance=remaining_balance
        )

    except Exception:
        current_app.logger.exception(
            "PAYMENT CHECKOUT ERROR"
        )

        for path in uploaded_proofs:
            delete_payment_proof(path)

        flash(
            "Unable to process your payment request.",
            "error"
        )

        return redirect(
            url_for("customer.dashboard")
        )

    finally:
        close_database(connection, cursor)


# PAYMENT OTP VERIFICATION
@payment_blueprint.route(
    "/verify-otp",
    methods=["GET", "POST"]
)
def verify_payment_otp():

    if not require_customer():
        return redirect(
            url_for("customer.dashboard")
        )

    pending_payment = session.get(
        "pending_payment"
    )

    if not isinstance(pending_payment, dict):
        flash(
            "No pending payment was found.",
            "error"
        )

        return redirect(
            url_for("customer.dashboard")
        )

    if request.method == "POST":

        entered_otp = request.form.get(
            "otp",
            ""
        ).strip()

        if not is_valid_otp(entered_otp):
            flash(
                "Please enter your 6-digit code.",
                "warning"
            )

            return redirect(
                url_for("payment.verify_payment_otp")
            )

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            connection.start_transaction()

            cursor = connection.cursor(dictionary=True)

            # LOCK CUSTOMER ORDER
            cursor.execute("""
                SELECT
                    id,
                    order_code,
                    total_amount,
                    status
                FROM tbl_sales
                WHERE id = %s
                  AND user_id = %s
                FOR UPDATE
            """, (
                pending_payment.get("sale_id"),
                session["user_id"]
            ))

            sale = cursor.fetchone()

            if not sale:
                connection.rollback()

                delete_pending_proofs(pending_payment)
                session.pop("pending_payment", None)

                flash(
                    "Order not found.",
                    "error"
                )

                return redirect(
                    url_for("customer.dashboard")
                )

            if sale["status"] == "Cancelled":
                connection.rollback()

                delete_pending_proofs(pending_payment)
                session.pop("pending_payment", None)

                flash(
                    "This order has already been cancelled. Your payment was not submitted.",
                    "error"
                )

                return redirect(
                    url_for("customer.my_orders")
                )

            # VERIFY OTP
            otp_valid, otp_message, otp_id = verify_otp_for_transaction(
                cursor,
                session["user_id"],
                entered_otp,
                purpose="payment"
            )

            if not otp_valid:
                connection.commit()

                flash(
                    otp_message,
                    "error"
                )

                return redirect(
                    url_for("payment.verify_payment_otp")
                )

            # CHECK CURRENT PAYMENT BALANCE
            verified_total, pending_total = get_payment_balance(
                cursor,
                sale["id"]
            )

            total_amount = Decimal(
                str(sale["total_amount"])
            )

            remaining_balance = total_amount - verified_total

            if remaining_balance <= 0:
                connection.rollback()

                delete_pending_proofs(pending_payment)
                session.pop("pending_payment", None)

                flash(
                    "This order is already fully paid.",
                    "success"
                )

                return redirect(
                    url_for("payment.payment_history")
                )

            if pending_total > 0:
                connection.rollback()

                delete_pending_proofs(pending_payment)
                session.pop("pending_payment", None)

                flash(
                    "Another payment is still being checked.",
                    "error"
                )

                return redirect(
                    url_for("payment.payment_history")
                )

            # VALIDATE SESSION PAYMENT DETAILS
            payment_items = pending_payment.get(
                "payments",
                []
            )

            payment_total = validate_pending_payment_items(
                payment_items
            )

            if (
                payment_total <= Decimal("0")
                or payment_total > remaining_balance
            ):
                connection.rollback()

                delete_pending_proofs(pending_payment)
                session.pop("pending_payment", None)

                flash(
                    "The remaining balance has changed. Please submit your payment again.",
                    "error"
                )

                return redirect(
                    url_for(
                        "payment.checkout",
                        sale_id=sale["id"]
                    )
                )

            # INSERT PAYMENT RECORDS AS PENDING
            for item in payment_items:

                payment_code = generate_custom_code(
                    cursor,
                    "tbl_payments"
                )

                cursor.execute("""
                    INSERT INTO tbl_payments
                    (
                        payment_code,
                        sale_id,
                        amount,
                        payment_method,
                        payment_status,
                        reference_number,
                        proof_image
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    payment_code,
                    sale["id"],
                    parse_payment_amount(item["amount"]),
                    item["payment_method"],
                    "Pending",
                    item.get("reference_number") or None,
                    item.get("proof_path")
                ))

            # UPDATE ORDER PAYMENT STATUS
            update_sale_payment_status(
                cursor,
                sale["id"]
            )

            # MARK OTP AS USED
            cursor.execute("""
                UPDATE tbl_email_otps
                SET is_used = 1
                WHERE id = %s
                  AND user_id = %s
                  AND purpose = %s
                  AND is_used = 0
            """, (
                otp_id,
                session["user_id"],
                "payment"
            ))

            if cursor.rowcount != 1:
                raise ValueError(
                    "The payment OTP could not be marked as used."
                )

            connection.commit()

            session.pop(
                "pending_payment",
                None
            )

            flash(
                "Your payment was submitted successfully and is waiting for admin verification.",
                "success"
            )

            return redirect(
                url_for("payment.payment_history")
            )

        except ValueError as error:

            if connection is not None:
                connection.rollback()

            current_app.logger.warning(
                "PAYMENT VALIDATION ERROR: %s",
                error
            )

            flash(
                str(error),
                "error"
            )

            return redirect(
                url_for("payment.verify_payment_otp")
            )

        except Exception:

            if connection is not None:
                connection.rollback()

            current_app.logger.exception(
                "PAYMENT VERIFICATION ERROR"
            )

            flash(
                "Unable to save your payment. Please try again.",
                "error"
            )

            return redirect(
                url_for("payment.verify_payment_otp")
            )

        finally:
            close_database(connection, cursor)

    return render_template(
        "payment/verify_otp.html"
    )


# RESEND PAYMENT OTP
@payment_blueprint.route(
    "/resend-otp",
    methods=["POST"]
)
def resend_payment_otp():

    if not require_customer():
        return redirect(
            url_for("customer.dashboard")
        )

    pending_payment = session.get("pending_payment")

    if (
        not isinstance(pending_payment, dict)
        or not pending_payment.get("sale_id")
    ):
        flash(
            "No pending payment was found. Please submit your payment again.",
            "error"
        )
        return redirect(
            url_for("customer.dashboard")
        )

    try:
        validate_pending_payment_items(
            pending_payment.get("payments")
        )
    except ValueError:
        delete_pending_proofs(pending_payment)
        session.pop("pending_payment", None)
        flash(
            "Your pending payment details are no longer valid. Please submit your payment again.",
            "error"
        )
        return redirect(
            url_for(
                "payment.checkout",
                sale_id=pending_payment["sale_id"]
            )
        )

    if not can_resend_otp(
        session["user_id"],
        "payment"
    ):
        flash(
            "Please wait 60 seconds before requesting another payment code.",
            "warning"
        )
        return redirect(
            url_for("payment.verify_payment_otp")
        )

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                s.id,
                s.status,
                u.email
            FROM tbl_sales AS s
            INNER JOIN tbl_users AS u
                ON u.id = s.user_id
            WHERE s.id = %s
              AND s.user_id = %s
            LIMIT 1
        """, (
            pending_payment["sale_id"],
            session["user_id"]
        ))

        payment_owner = cursor.fetchone()

        if not payment_owner or payment_owner["status"] == "Cancelled":
            delete_pending_proofs(pending_payment)
            session.pop("pending_payment", None)
            flash(
                "This pending payment is no longer available. Please start again from your orders.",
                "error"
            )
            return redirect(
                url_for("customer.my_orders")
            )

        otp = generate_otp()

        if not save_otp(
            session["user_id"],
            otp,
            purpose="payment"
        ):
            flash(
                "Unable to create a new payment verification code. Please try again.",
                "error"
            )
            return redirect(
                url_for("payment.verify_payment_otp")
            )

        if not send_otp_email(
            payment_owner["email"],
            otp,
            purpose="payment"
        ):
            invalidate_payment_otp(
                session["user_id"]
            )
            flash(
                "Unable to send a new payment verification code. Please try again.",
                "error"
            )
            return redirect(
                url_for("payment.verify_payment_otp")
            )

        flash(
            "A new payment verification code has been sent to your registered email.",
            "success"
        )
        return redirect(
            url_for("payment.verify_payment_otp")
        )

    except Error:
        current_app.logger.exception(
            "PAYMENT OTP RESEND DATABASE ERROR"
        )
        flash(
            "Unable to resend the payment verification code. Please try again.",
            "error"
        )
        return redirect(
            url_for("payment.verify_payment_otp")
        )

    except Exception:
        current_app.logger.exception(
            "PAYMENT OTP RESEND ERROR"
        )
        flash(
            "Unable to resend the payment verification code. Please try again.",
            "error"
        )
        return redirect(
            url_for("payment.verify_payment_otp")
        )

    finally:
        close_database(connection, cursor)


# PAYMENT HISTORY
@payment_blueprint.route("/history")
def payment_history():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if session.get("role") == "admin":

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
                    s.order_code,
                    s.user_id,
                    s.order_date
                FROM tbl_payments AS p
                INNER JOIN tbl_sales AS s
                    ON p.sale_id = s.id
                ORDER BY p.id DESC
            """)

        elif session.get("role") == "customer":

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
                    s.order_code,
                    s.order_date
                FROM tbl_payments AS p
                INNER JOIN tbl_sales AS s
                    ON p.sale_id = s.id
                WHERE s.user_id = %s
                ORDER BY p.id DESC
            """, (session["user_id"],))

        else:
            flash(
                "You do not have permission to view payment history.",
                "error"
            )

            return redirect(
                url_for("auth.login")
            )

        payments = cursor.fetchall()

        return render_template(
            "payment/history.html",
            payments=payments
        )

    except Exception:
        current_app.logger.exception(
            "PAYMENT HISTORY ERROR"
        )

        flash(
            "Unable to load payment history.",
            "error"
        )

        if session.get("role") == "admin":
            return redirect(
                url_for("admin.dashboard")
            )

        return redirect(
            url_for("customer.dashboard")
        )

    finally:
        close_database(connection, cursor)