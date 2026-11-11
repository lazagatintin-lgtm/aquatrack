import os
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")

from app import app


class FakeReportCursor:

    def __init__(self):
        self.queries = []
        self.fetchone_results = [
            {"total_verified": Decimal("1337.50")},
            {"total_records": 60}
        ]

    def execute(self, query, parameters=()):
        self.queries.append((query, parameters))

    def fetchone(self):
        return self.fetchone_results.pop(0)

    def fetchall(self):
        return [{
            "id": 1,
            "order_code": "ORDER-1",
            "user_id": 2,
            "user_code": "CUSTOMER-1",
            "total_amount": Decimal("1400.00"),
            "status": "Pending",
            "order_date": datetime(2026, 11, 1, 12, 0),
            "verified_total": Decimal("1337.50")
        }]

    def close(self):
        pass


class FakeReportConnection:

    def __init__(self, cursor):
        self.report_cursor = cursor
        self.closed = False

    def cursor(self, dictionary=False):
        return self.report_cursor

    def is_connected(self):
        return not self.closed

    def close(self):
        self.closed = True


class FakeAnalyticsCursor:

    def __init__(self):
        self.queries = []

    def execute(self, query, parameters=()):
        self.queries.append((query, parameters))

    def fetchone(self):
        return {
            "total_products": 4,
            "total_stock": 41,
            "available_products": 1,
            "low_stock_products": 1,
            "out_of_stock_products": 1,
            "over_stock_products": 1,
            "excess_stock_units": 6,
            "inventory_value": Decimal("555.50")
        }

    def fetchall(self):
        return []

    def close(self):
        pass


class FakeAnalyticsConnection:

    def __init__(self, cursor):
        self.analytics_cursor = cursor
        self.closed = False

    def cursor(self, dictionary=False):
        return self.analytics_cursor

    def is_connected(self):
        return not self.closed

    def close(self):
        self.closed = True


class SalesReportTests(unittest.TestCase):

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        with self.client.session_transaction() as user_session:
            user_session["user_id"] = 9
            user_session["role"] = "admin"

    def test_report_filters_and_paginates_in_sql(self):
        cursor = FakeReportCursor()
        connection = FakeReportConnection(cursor)

        with patch(
            "reports.routes.get_db_connection",
            return_value=connection
        ):
            response = self.client.get(
                "/reports/sales?from_date=2026-11-01"
                "&to_date=2026-11-30&page=2"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Page 2 of 3", response.data)
        self.assertIn(b"1337.50", response.data)
        self.assertEqual(len(cursor.queries), 3)
        self.assertIn("s.order_date >= %s", cursor.queries[0][0])
        self.assertIn(
            "s.order_date < DATE_ADD(%s, INTERVAL 1 DAY)",
            cursor.queries[0][0]
        )
        self.assertEqual(
            cursor.queries[2][1],
            (
                datetime(2026, 11, 1).date(),
                datetime(2026, 11, 30).date(),
                25,
                25
            )
        )
        self.assertTrue(connection.closed)

    def test_invalid_date_range_is_rejected_without_database_access(self):
        with patch("reports.routes.get_db_connection") as get_connection:
            response = self.client.get(
                "/reports/sales?from_date=2026-12-01"
                "&to_date=2026-11-01"
            )

        self.assertEqual(response.status_code, 302)
        get_connection.assert_not_called()

    def test_analytics_shows_current_stock_snapshot_and_overstock(self):
        cursor = FakeAnalyticsCursor()
        connection = FakeAnalyticsConnection(cursor)

        with patch(
            "analytics.routes.get_db_connection",
            return_value=connection
        ):
            response = self.client.get("/analytics/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Current Inventory Snapshot", response.data)
        self.assertIn(b"Units Above Maximum", response.data)
        self.assertIn(b"<strong>6</strong>", response.data)
        self.assertIn("max_stock", cursor.queries[0][0])
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
