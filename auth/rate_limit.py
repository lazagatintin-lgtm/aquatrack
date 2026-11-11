import hashlib
import hmac
from datetime import datetime, timedelta

import mysql.connector
from flask import current_app

from database.db import get_db_connection


LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_MINUTES = 15


def _bucket_hash(kind, value):
    secret_key = current_app.config.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError("SECRET_KEY is required for login throttling.")

    message = f"{kind}:{value}".encode("utf-8")
    key = secret_key.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _bucket_hashes(email, remote_address):
    values = []
    if email and remote_address:
        values.append(
            _bucket_hash(
                "login",
                f"{email.lower()}\0{remote_address}"
            )
        )
    elif email:
        values.append(_bucket_hash("email", email.lower()))
    if remote_address:
        values.append(_bucket_hash("ip", remote_address))
    return tuple(values)


def is_login_blocked(email, remote_address):
    hashes = _bucket_hashes(email, remote_address)
    if not hashes:
        return False

    connection = None
    cursor = None
    cutoff = datetime.now() - timedelta(
        minutes=LOGIN_FAILURE_WINDOW_MINUTES
    )

    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        placeholders = ", ".join(["%s"] * len(hashes))
        cursor.execute(
            "SELECT COUNT(*) FROM tbl_login_rate_limits "
            "WHERE bucket_hash IN (" + placeholders + ") "
            "AND window_started_at > %s "
            "AND failed_attempts >= %s",
            (*hashes, cutoff, LOGIN_FAILURE_LIMIT)
        )
        return cursor.fetchone()[0] > 0

    except mysql.connector.Error:
        current_app.logger.exception(
            "LOGIN RATE LIMIT CHECK DATABASE ERROR"
        )
        raise

    finally:
        _close_database(connection, cursor)


def record_failed_login(email, remote_address):
    hashes = _bucket_hashes(email, remote_address)
    if not hashes:
        return

    connection = None
    cursor = None
    now = datetime.now()
    cutoff = now - timedelta(
        minutes=LOGIN_FAILURE_WINDOW_MINUTES
    )

    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor()

        for bucket_hash in hashes:
            cursor.execute("""
                INSERT INTO tbl_login_rate_limits
                    (bucket_hash, window_started_at, failed_attempts)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    failed_attempts = CASE
                        WHEN window_started_at <= %s THEN 1
                        ELSE failed_attempts + 1
                    END,
                    window_started_at = CASE
                        WHEN window_started_at <= %s THEN %s
                        ELSE window_started_at
                    END
            """, (
                bucket_hash,
                now,
                cutoff,
                cutoff,
                now
            ))

        cursor.execute("""
            DELETE FROM tbl_login_rate_limits
            WHERE window_started_at < %s
        """, (now - timedelta(days=1),))
        connection.commit()

    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        current_app.logger.exception(
            "LOGIN RATE LIMIT RECORD DATABASE ERROR"
        )
        raise

    finally:
        _close_database(connection, cursor)


def clear_login_failures(email, remote_address):
    hashes = _bucket_hashes(email, remote_address)
    if not hashes:
        return

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        placeholders = ", ".join(["%s"] * len(hashes))
        cursor.execute(
            "DELETE FROM tbl_login_rate_limits "
            "WHERE bucket_hash IN (" + placeholders + ")",
            hashes
        )
        connection.commit()

    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        current_app.logger.exception(
            "LOGIN RATE LIMIT CLEAR DATABASE ERROR"
        )
        raise

    finally:
        _close_database(connection, cursor)


def _close_database(connection, cursor):
    if cursor is not None:
        try:
            cursor.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "LOGIN RATE LIMIT CURSOR CLOSE ERROR"
            )

    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except mysql.connector.Error:
            current_app.logger.exception(
                "LOGIN RATE LIMIT CONNECTION CLOSE ERROR"
            )
