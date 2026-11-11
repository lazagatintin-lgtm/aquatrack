from database.migrations.helpers import add_column_if_missing


def upgrade(cursor):
    add_column_if_missing(
        cursor,
        "tbl_users",
        "profile_image_path",
        "VARCHAR(255) NULL"
    )