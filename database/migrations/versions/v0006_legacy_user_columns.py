from database.migrations.helpers import normalize_legacy_user_schema


def upgrade(cursor):
    normalize_legacy_user_schema(cursor)