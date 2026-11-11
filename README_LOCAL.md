# AquaTrack Local Run Guide

This guide explains how to run AquaTrack on your local machine for development.

## 1) Requirements

- Python 3.9+
- MySQL 8.0+
- XAMPP (optional but commonly used for MySQL locally)
- Git

## 2) Clone and open the project

```bash
git clone <your-repo-url>
cd aquatrack
```

## 3) Create a virtual environment

On Windows:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

## 4) Install Python dependencies

```bash
python -m pip install -r requirements.txt
```

## 5) Start MySQL in XAMPP

If using XAMPP:

1. Open XAMPP Control Panel
2. Start MySQL
3. Open phpMyAdmin
4. Create a database named:

```sql
CREATE DATABASE aquatrack_db;
```

Then import the schema:

- `database/schema.sql`

## 6) Create a local environment file

In the project root, create a file named `.env` with this content:

```env
SECRET_KEY=replace-with-a-long-random-secret
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=aquatrack_db
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com
APP_ENV=development
SESSION_COOKIE_SECURE=false
```

Notes:
- Use a long random string for `SECRET_KEY`
- If your XAMPP MySQL user is not `root`, change `MYSQL_USER` and `MYSQL_PASSWORD`
- For email OTP features, configure a valid Gmail SMTP app password

## 7) Apply database migrations

```bash
python -m flask --app app migrate-database
```

## 8) Create the initial owner/admin account

```bash
python -m flask --app app create-owner
```

You will be prompted for:
- Owner name
- Owner email
- Owner password

## 9) Run the project

```bash
python -m flask --app app run --host 0.0.0.0 --port 5000
```

Then open:

```text
http://127.0.0.1:5000
```

## 10) Troubleshooting

### Secret key error
If you see:

```text
RuntimeError: SECRET_KEY is missing. Please set it in your .env file.
```

Then make sure your `.env` file exists in the project root and contains `SECRET_KEY`.

### Database connection error
If the app cannot connect to MySQL:

- confirm MySQL is running in XAMPP
- check `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DATABASE`
- make sure the database exists

### Port already in use
If port `5000` is already used, run:

```bash
python -m flask --app app run --host 0.0.0.0 --port 5001
```

## 11) Run tests

```bash
pytest -q
```

## 12) Production note

This guide is for local development only. The app should not be used in production with the Flask development server.

