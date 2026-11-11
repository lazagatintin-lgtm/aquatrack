# AquaTrack JRJ PETSHOP

AquaTrack is a Flask/MySQL inventory and order-management system for JRJ
PETSHOP. Customers can browse available fish products, place orders, and view
their orders and payments. The owner and staff can manage products, stock,
inventory losses, sales, payments, and reports.

## Requirements

- Python 3.9 or later
- MySQL 8.0 or later
- The packages listed in `requirements.txt`

The interface uses responsive HTML5, CSS3, and JavaScript. Flask-WTF protects
form submissions with CSRF tokens, Jinja escapes rendered values, SQL
statements use parameterized values, and account passwords are stored as
Werkzeug password hashes.

## Local setup

1. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv venv
   venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Create a MySQL database and user. The default database name is
   `aquatrack_db`. Import `database\schema.sql` into the database using MySQL
   Workbench or the MySQL command-line client.

3. Create a `.env` file in the project root and configure:

   ```text
   SECRET_KEY=replace-with-a-long-random-secret
   MYSQL_HOST=localhost
   MYSQL_PORT=3306
   MYSQL_USER=root
   MYSQL_PASSWORD=your-database-password
   MYSQL_DATABASE=aquatrack_db
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   MAIL_USE_TLS=true
   MAIL_USE_SSL=false
   MAIL_USERNAME=your-smtp-account
   MAIL_PASSWORD=your-smtp-app-password
   MAIL_DEFAULT_SENDER=your-smtp-account
   ```

   Keep `.env` private and do not commit real credentials. Use the email
   provider's supported SMTP credentials, not an ordinary account password.

4. Apply migrations and create the initial owner:

   ```powershell
   python -m flask --app app migrate-database
   python -m flask --app app create-owner
   ```

   The owner command prompts for the owner's name, email, and password. From
   the owner dashboard, approve staff by name and email before they register.

5. Start the development server:

   ```powershell
   python -m flask --app app run --debug
   ```

   Open `http://127.0.0.1:5000`. Do not use the Flask debug server for public
   production hosting.

See [database/README.md](database/README.md) for schema, migration, SMTP,
backup, and MySQL integration-test details.

## Tests

Run the unit test suite:

```powershell
python -m unittest discover -v
```

MySQL integration checks are opt-in and require a dedicated test database
whose name starts with `aquatrack_test_`. Follow the safety instructions in
[database/README.md](database/README.md); never point integration tests at a
live database.

## Accounts and features

- Customers can register and log in using the Customer account tabs.
- The owner signs in through Owner Login; the initial owner is provisioned from the CLI.
- All accounts use email OTP verification at login.
- Each authenticated user can manage their own name, email, and password from
  **My Profile**.
- The owner manages inventory and business operations.
- The code uses `User` and `Product` domain classes for account/password
  behavior and product validation.

## Final-project submission checklist

The codebase implements the application features and technology requirements
in the course guidelines. The following submission evidence is specific to
the student/client process and must be completed with accurate, real details:

- Confirm that the project title is unique and recorded in the class title
  list. The project owner reports that AquaTrack JRJ PETSHOP is already on the
  title sheet.
- See [CLIENT-ENGAGEMENT.md](CLIENT-ENGAGEMENT.md) for the client and the
  discussion/review details provided so far. Add any remaining interview
  notes and review evidence if available.
- Submit the source repository link and present the live walkthrough during
  the scheduled defense. The repository link is currently pending.

Do not use invented client details or fabricated sign-off.
