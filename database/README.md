# AquaTrack - JRJ PETSHOP
## Database Documentation

### Database Information

- **Database Name:** aquatrack_db
- **Project:** AquaTrack Stock Monitoring System for Preventing Inventory Losses
- **Database Management System:** MySQL
- **Backend:** Python Flask

### 1. Database Overview

The AquaTrack database stores and manages the information needed by the system. It handles user accounts, fish product information, inventory quantities, daily product availability, stock movements, inventory losses, sales, payments, and email OTP verification.

### 2. Database Tables

| Table | Description |
|---|---|
| tbl_users | Stores customer and owner (admin-role) accounts; legacy staff rows may remain but are not authorized by the application |
| tbl_staff_registration_approvals | Legacy staff approvals table; no longer used by the application |
| tbl_products | Stores fish product information, prices, and stock quantities |
| tbl_daily_catalog | Stores daily fish catalog and available quantities |
| tbl_stock_history | Records inventory stock movements |
| tbl_sales | Stores customer orders and sales information |
| tbl_sale_items | Stores individual products included in each order |
| tbl_payments | Stores payment records and verification details |
| tbl_inventory_losses | Records lost or damaged fish inventory |
| tbl_email_otps | Stores hashed email OTP verification records |
| tbl_login_rate_limits | Stores keyed login-failure counters |

### 3. Database Relationships

The database uses foreign keys to connect related records.

- Products are connected to daily catalog records.
- Products are connected to stock history records.
- Products are connected to inventory loss records.
- Users are connected to sales orders.
- Users are connected to email OTP records.
- Sales are connected to sale items.
- Products are connected to sale items.
- Sales are connected to payment records.
- Users are connected to payment verification records.

### 4. Inventory Management

The inventory module manages fish product information, stock quantities, daily availability, stock movements, and inventory losses.

It also supports low-stock and out-of-stock reminders, optional per-product
maximum stock levels for overstock alerts, and inventory reporting. A product
is low stock when its positive quantity is at or below its minimum; zero is
out of stock. A product is over stock only when a maximum is configured and
its quantity exceeds that maximum. Over-stock alerts do not block stock entry.

The maximum is optional; leave it unset where no upper limit has been defined.
Configure it from **Products → Edit**. The analytics dashboard includes a
current inventory snapshot with available, low, out-of-stock, and over-stock
counts, excess units, and current inventory value. The snapshot is independent
of the selected date range; movement and loss charts remain date-filtered.

Products must have a positive price because customer checkout rejects
zero-total orders. Versioned migrations also add database-backed login
throttling.

### 5. Sales and Payment Management

The sales module stores customer orders and their corresponding items.

The payment module records payment methods, amounts, payment statuses, and verification details.

### 6. User Account Management

The application supports two active account roles:

- Admin: Owner role with access to products, inventory, sales, payments, and reports.
- Customer: Views available fish products and places orders.

All authenticated roles can update their own name, email, and password from
**My Profile**. The account role cannot be changed through profile management.

Customers use customer login and registration tabs. The owner uses the separate
Owner Login and is provisioned from a terminal with `flask --app app create-owner`.
The historical staff migration remains in the migration history; existing staff
rows are not deleted, but staff accounts are no longer accepted for login or
management access. After creating the database, provision the first owner from a
terminal with `flask --app app create-owner`; the command prompts for the owner
name, email, and a hidden password and refuses to create a second initial
owner.

Email OTP verification is used as part of the account authentication process.

### Product Photos

Administrators can upload an optional photo when adding a product, or replace
and remove the photo from the product edit page. JPG, PNG, and WebP files up to
5 MiB are accepted. Images are stored under `static/uploads/products/`; only
the relative image path is stored in `tbl_products.image_path`.

After running the database migrations, sign in as an administrator, open
**Products → Add New Product**, choose a photo, and save the product. Existing
products can be updated from their **Edit** page.

### Database Migrations

Back up the database before applying schema changes. Start MySQL and run from
the project folder:

```powershell
venv\Scripts\python.exe -m flask --app app migrate-database
```

Migrations are ordered and recorded in `tbl_schema_migrations`. They safely
check for documented legacy columns/indexes, backfill missing unique codes,
add product photos and max-stock fields, normalize the old `Cash` method, add
the max-stock constraint, require positive product prices, and install login
throttling storage. Re-running the command skips completed migrations. Failed
login attempts are tracked using keyed hashes for the IP and the IP/email pair;
the raw address and email are not written to the limiter table. Five failures
within 15 minutes temporarily block further attempts for that IP and pair.
The staff-registration migration adds owner approvals and a separate staff
role while preserving the earliest existing admin account as the owner.

The positive-price migration intentionally stops if any product has a price
of zero or less. Review and assign valid prices, then re-run the command.
Correct other migration errors before retrying; migrations are designed to
resume idempotently after partially completed DDL.

### SMTP and Configuration Checks

Run these checks without exposing credentials:

```powershell
venv\Scripts\python.exe -m flask --app app check-config
venv\Scripts\python.exe -m flask --app app check-mail
```

`check-mail` connects and authenticates with SMTP, sends an SMTP `NOOP`, and
does not send an email. Configure `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`,
`MAIL_PASSWORD`, and `MAIL_DEFAULT_SENDER` in the local environment first.
For production, set `APP_ENV=production`, use a unique secret key of at least
32 characters, serve over HTTPS, and enable secure session cookies.

### Integration Tests

Unit tests run with `venv\Scripts\python.exe -m unittest discover`. Read-only
MySQL integration checks are opt-in. Create a separate database named with
the `aquatrack_test_` prefix and apply `database\schema.sql` to it. In a
temporary PowerShell window, set `MYSQL_DATABASE` to that test database and
run `venv\Scripts\python.exe -m flask --app app migrate-database`. Then open a
separate PowerShell window with the normal application configuration, set
`AQUATRACK_TEST_DATABASE` to the test database name, and run
`venv\Scripts\python.exe -m unittest test_mysql_integration -v`. The test
refuses to connect when the target is not a dedicated prefixed database or
matches the normal application database. Never point `MYSQL_DATABASE` at a
live database while setting up integration fixtures.

### 7. Database Connection

The Flask application connects to the MySQL database through:

`database/db.py`

Database connection settings are managed through the project's configuration.

### 8. Database Maintenance

- Maintain regular database and uploaded-file backups, and test restoration.
- Validate user inputs before saving records.
- Preserve relationships between related tables.
- Monitor stock quantities and inventory movements.
- Verify payment records before recording confirmed income.
- Review **Inventory Reconciliation** for differences between product stock
  and the latest recorded movement.

#### Backup

Store backups outside the project folder and restrict access because they may
contain customer and payment records. In PowerShell, from the project folder:

```powershell
$backup = Join-Path "D:\AquaTrackBackups" (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Path $backup -Force | Out-Null
# Set these non-secret values for your installation before running mysqldump.
$env:MYSQL_HOST = "localhost"
$env:MYSQL_USER = "root"
$env:MYSQL_DATABASE = "aquatrack_db"
mysqldump --host=$env:MYSQL_HOST --port=3306 --user=$env:MYSQL_USER --password --single-transaction --routines --triggers $env:MYSQL_DATABASE --result-file="$backup\database.sql"
if ($LASTEXITCODE -ne 0) { throw "Database backup failed." }
if (Test-Path ".\static\uploads") {
    Copy-Item ".\static\uploads" -Destination $backup -Recurse
}
if (Test-Path ".\instance\payment_proofs") {
    Copy-Item ".\instance\payment_proofs" -Destination $backup -Recurse
}
```

`mysqldump` prompts for the database password; do not put it in the command
line or backup script. Restore first to a separate test database and copy the
uploaded folders back to their matching paths. Verify product photos and
payment-proof retrieval before relying on the restored system.

### 9. Production Configuration

- Serve the application only over HTTPS in production and set
  `APP_ENV=production`; secure session cookies default on in that mode.
- Set a unique, unpredictable `SECRET_KEY` outside source control.
- Run `flask --app app check-config` and `flask --app app check-mail` before
  deployment. Never paste `.env` values into tickets, logs, or source control.
- The application limits each request to 11 MiB to accommodate up to two
  payment-proof images (each limited to 5 MiB) plus form data.