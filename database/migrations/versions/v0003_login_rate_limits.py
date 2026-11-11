def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tbl_login_rate_limits (
            bucket_hash CHAR(64) NOT NULL,
            window_started_at DATETIME NOT NULL,
            failed_attempts INT NOT NULL DEFAULT 0,
            PRIMARY KEY (bucket_hash),
            KEY idx_login_rate_window (window_started_at),
            CONSTRAINT chk_login_rate_attempts
                CHECK (failed_attempts >= 0)
        ) ENGINE=InnoDB
    """)
