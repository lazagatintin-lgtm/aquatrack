def column_exists(cursor, table_name, column_name):
    cursor.execute("""
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        LIMIT 1
    """, (table_name, column_name))
    return cursor.fetchone() is not None


def add_column_if_missing(
    cursor,
    table_name,
    column_name,
    column_definition
):
    if not column_exists(cursor, table_name, column_name):
        cursor.execute(
            f"ALTER TABLE `{table_name}` "
            f"ADD COLUMN `{column_name}` {column_definition}"
        )


def unique_index_exists(cursor, table_name, column_name):
    cursor.execute("""
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
          AND NON_UNIQUE = 0
        GROUP BY INDEX_NAME
        HAVING COUNT(*) = 1
        LIMIT 1
    """, (table_name, column_name))
    return cursor.fetchone() is not None


def get_primary_key_column(cursor, table_name):
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = 'PRIMARY'
        ORDER BY ORDINAL_POSITION
        LIMIT 2
    """, (table_name,))
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            f"Table {table_name} must have a single-column primary key "
            "to backfill legacy codes."
        )
    return rows[0][0]


def ensure_legacy_code(
    cursor,
    table_name,
    column_name,
    index_name,
    legacy_prefix
):
    add_column_if_missing(
        cursor,
        table_name,
        column_name,
        "VARCHAR(20) NULL"
    )
    primary_key = get_primary_key_column(cursor, table_name)
    cursor.execute(
        f"UPDATE `{table_name}` "
        f"SET `{column_name}` = CONCAT(%s, `{primary_key}`) "
        f"WHERE `{column_name}` IS NULL OR `{column_name}` = ''",
        (legacy_prefix,)
    )
    cursor.execute(
        f"ALTER TABLE `{table_name}` "
        f"MODIFY COLUMN `{column_name}` VARCHAR(20) NOT NULL"
    )
    if not unique_index_exists(cursor, table_name, column_name):
        cursor.execute(
            f"ALTER TABLE `{table_name}` "
            f"ADD UNIQUE KEY `{index_name}` (`{column_name}`)"
        )


def constraint_exists(cursor, table_name, constraint_name):
    cursor.execute("""
        SELECT 1
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = %s
          AND CONSTRAINT_TYPE = 'CHECK'
        LIMIT 1
    """, (table_name, constraint_name))
    return cursor.fetchone() is not None


def check_clause(cursor, table_name, constraint_name):
    cursor.execute("""
        SELECT cc.CHECK_CLAUSE
        FROM information_schema.CHECK_CONSTRAINTS AS cc
        WHERE cc.CONSTRAINT_SCHEMA = DATABASE()
          AND cc.CONSTRAINT_NAME = %s
        LIMIT 1
    """, (constraint_name,))
    row = cursor.fetchone()
    return row[0] if row else None
