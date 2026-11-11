from database.migrations.helpers import get_primary_key_column


def upgrade(cursor):
    user_primary_key = get_primary_key_column(cursor, "tbl_users")

    cursor.execute("""
        ALTER TABLE tbl_users
        MODIFY COLUMN role
            ENUM('admin', 'staff', 'customer')
            NOT NULL DEFAULT 'customer'
    """)

    cursor.execute(f"""
        UPDATE tbl_users
        SET role = 'staff'
        WHERE role = 'admin'
          AND `{user_primary_key}` <> (
              SELECT owner_id
              FROM (
                  SELECT MIN(`{user_primary_key}`) AS owner_id
                  FROM tbl_users
                  WHERE role = 'admin'
              ) AS first_owner
          )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS tbl_staff_registration_approvals (
            id INT NOT NULL AUTO_INCREMENT,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) NOT NULL,
            approved_by INT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (id),
            UNIQUE KEY uq_staff_approval_email (email),
            CONSTRAINT fk_staff_approval_owner
                FOREIGN KEY (approved_by)
                REFERENCES tbl_users (`{user_primary_key}`)
                ON DELETE CASCADE
                ON UPDATE CASCADE
        ) ENGINE=InnoDB
    """)
