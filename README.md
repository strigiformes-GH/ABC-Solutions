# ABC Solutions Web App

A Flask app for managing stock, sales, customers and accounts.

## Run locally

Use Python 3.13.
The local database uses SQLite.

1. Copy `.env.example` to `.env`.
2. Generate a key and copy the output into `SECRET_KEY`:

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

3. Fill in the five `ADMIN_*` settings. Use a password of at least 12 characters.
4. In PowerShell, from the `WebApp` project folder, run:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   .\.venv\Scripts\python.exe -m flask --app app init-db
   .\.venv\Scripts\python.exe -m flask --app app auth create-admin
   .\.venv\Scripts\python.exe app.py
   ```

Open <http://127.0.0.1:5000>.
Set up MFA.
Remove the admin settings after creating the account.

## Tests

   ```powershell
   .\.venv\Scripts\python.exe -m pytest
   ```

## Deploy

1. Choose hosting that runs Docker and provides HTTPS. Create a PostgreSQL database with a secure connection.
2. Use `.env.production.example` to configure the host. Store real credentials in its secret settings:

   APP_ENV - production
   SECRET_KEY - A new random key, but keep it across restarts
   DATABASE_URL - PostgreSQL connection address
   SESSION_COOKIE_SECURE - true
   MFA_REQUIRED - true
   AUTO_INIT_DB - false
   TRUSTED_HOSTS - Hostname, such as app.example.com, without the https:// part

3. Enable HTTPS and redirect HTTP visitors to HTTPS. Block public access to the internal app port. Set `FORWARDED_ALLOW_IPS` to the trusted proxy addresses provided by the host.
4. Build the image and upload it to the hosting service:

   ```text
   docker build -t abc-solutions:release-1 .
   ```

5. For a **new, empty db**, run through the host's console or one-off jobs, using the release image and its settings:

   ```text
   alembic upgrade head
   flask --app app seed-roles
   flask --app app auth create-admin
   ```

   Supply the admin settings for account creation, then remove them.

6. Start the image with its default command. Gunicorn serves the app. Configure the host to check `/healthz` using an allowed hostname.
7. Check login, MFA, permissions, sales and receipts in staging before going live.

Start with one app instance.

Never commit secrets, database files or backups to version control.

## Database changes

A migration is a saved change to the database structure.
Alembic tracks which migrations have been applied.
Review generated migrations, try them in staging and back up production before applying them.

**Existing databases:** do not run the initial migration over existing tables. Back up and compare the database with migration `0001`. Only if they match, use `alembic stamp 0001`. Stamping records a version without checking or changing the tables.

Moving SQLite data to PostgreSQL requires a separate transfer and checks that records and totals match.

## Release checks

GitHub Actions runs `.github/workflows/release-checks.yml` on pushes, pull request changes or manual starts.

It checks PostgreSQL migrations, role creation, automated tests, security findings, vulnerable packages and the Docker build. The automated tests use their own SQLite database.

A failed check fails the workflow.

The PostgreSQL password and the password in its `DATABASE_URL` must match.

## Backups and recovery

- Set up encrypted daily backups.
- Practise restoring into a separate database.
- Keep the previous release image. Reuse it only if it supports the current database structure.
- Restore backups with the matching app version.
- Monitor errors, database health, backup failures and failed scheduled jobs.
- Schedule `flask --app app auth purge-reset-tokens` daily to remove old password reset records.

## Recorded checks

Recorded on 19th Nov 2026
(Python 3.13)

- 36 tests passed, 3 manual checks skipped.
- Bandit found no medium/high severity issues and one low severity issue.
- The dependency audit found no known vulnerabilities.
