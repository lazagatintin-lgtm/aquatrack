import importlib
import logging
from pathlib import Path

from mysql.connector import Error


logger = logging.getLogger(__name__)
VERSIONS_PATH = Path(__file__).parent / "versions"
LOCK_NAME = "aquatrack_schema_migrations"


def discover_migrations():
    return sorted(
        path.stem
        for path in VERSIONS_PATH.glob("v[0-9][0-9][0-9][0-9]_*.py")
        if path.name != "__init__.py"
    )


def apply_migrations(connection):
    cursor = None
    lock_acquired = False
    applied = []

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT GET_LOCK(%s, 10)", (LOCK_NAME,))
        lock_acquired = cursor.fetchone()[0] == 1

        if not lock_acquired:
            raise RuntimeError(
                "Could not acquire the database migration lock."
            )

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tbl_schema_migrations (
                version VARCHAR(100) NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (version)
            ) ENGINE=InnoDB
        """)
        connection.commit()

        cursor.execute("""
            SELECT version
            FROM tbl_schema_migrations
        """)
        applied_versions = {
            row[0]
            for row in cursor.fetchall()
        }

        for version in discover_migrations():
            if version in applied_versions:
                continue

            migration = importlib.import_module(
                f"{__name__}.versions.{version}"
            )
            logger.info("Applying database migration %s.", version)
            migration.upgrade(cursor)
            cursor.execute("""
                INSERT INTO tbl_schema_migrations (version)
                VALUES (%s)
            """, (version,))
            connection.commit()
            applied.append(version)

        return applied

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()
        if lock_acquired:
            lock_cursor = connection.cursor()
            try:
                lock_cursor.execute(
                    "SELECT RELEASE_LOCK(%s)",
                    (LOCK_NAME,)
                )
            except Error:
                logger.exception("Could not release migration lock.")
            finally:
                lock_cursor.close()
