# AssetDesk

API for recording company IT equipment and who is holding it. FastAPI + SQLAlchemy 2 + SQLite, JWT sign-in, two roles (admin, staff).

Once it's running, the API docs are at http://localhost:8000/docs (Swagger) and http://localhost:8000/redoc.

## Versions I worked with

| | |
|---|---|
| OS | Windows 11 (build 26300) |
| Python | 3.12.13 (should work on 3.11+) |
| Database | SQLite 3.50.4 (the one bundled with Python) |
| Container base image | python:3.12-slim |
| Main libraries | FastAPI 0.162, Starlette 1.10, Uvicorn 0.54, SQLAlchemy 2.1, Pydantic 2.14, Alembic 1.20 |

Exact pins are in `requirements.txt` (runtime first, then the test and lint tools).

## 1. Install and run on a clean machine

Windows PowerShell shown; on Linux/macOS use `python3`, `source .venv/bin/activate` and `cp` instead of `copy`.

```powershell
cd assetdesk

# 1. virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. dependencies (includes pytest and ruff)
pip install -r requirements.txt

# 3. configuration - the defaults work locally, so this is optional for a first run
copy .env.sample .env

# 4. create / upgrade the database and the two sign-in accounts
#    (--demo adds a few sample employees and assets)
python -m app.init_db --demo

# 5. run (development)
uvicorn app.main:app --reload
```

Then sign in. In Swagger, use the **Authorize** button with `admin` / `admin-dev-password` (or `staff` / `staff-dev-password`). These are only the local defaults and are set with `ADMIN_PASSWORD` / `STAFF_PASSWORD`.

From the command line:

```powershell
curl.exe -s -X POST http://localhost:8000/auth/token -d "username=admin&password=admin-dev-password"
curl.exe -s http://localhost:8000/assets -H "Authorization: Bearer <access_token>"
```

### The database file

`assetdesk.db` in this folder is a ready-made database (schema plus demo data plus the two default accounts). To start from scratch, delete it and run `python -m app.init_db` again. The schema itself lives in Alembic migrations under `app/migrations/versions`, so the script is the real source of truth, not the file. After changing a model, `python -m app.init_db --new-migration "what changed"` generates the next migration (Alembic is configured from code, so there's no `alembic.ini`).

### Configuration

All settings are read from environment variables or a `.env` file (`app/core/config.py`, using pydantic-settings). Every setting is listed with its default in `.env.sample`. Nothing secret is in the code. With `APP_ENV=production` the service refuses to start if `SECRET_KEY` is the dev default or shorter than 32 characters, or if the default account passwords haven't been changed.

## 2. Running the tests

```powershell
pytest
```

That's it. Each test gets its own temporary SQLite file, so the tests never touch `assetdesk.db`. They take about 25 seconds; most of that is the warranty and notification tests, which wait on purpose.

Other useful commands:

```powershell
pytest --cov=app --cov-report=term-missing   # coverage (currently 97%)

# lint / PEP 8 (line length 110; generated migrations left alone)
ruff check --line-length 110 --select E,F,W,I,N,UP,B,SIM,ASYNC --exclude app/migrations/versions app tests
ruff format --check --line-length 110 --exclude app/migrations/versions app tests
```

The files in `evidence/` are the output of `pytest tests/<file> -v` for each section, plus the coverage and lint runs above.

Tests are split by requirement section (`tests/test_01_employees.py` ... `test_09_operation.py`). Each requirement has at least one case that works and one that is refused. The test names say which, e.g. `test_inactive_employee_refused_br5`.

## Endpoints

| Method | Path | Who | Sync/async |
|---|---|---|---|
| POST | /auth/token | anyone | def |
| GET | /auth/me | signed in | def |
| POST | /employees | admin | def |
| GET | /employees?active=&page=&size= | staff, admin | def |
| GET / PATCH / DELETE | /employees/{id} | GET staff+, others admin | def |
| POST | /assets | admin | def |
| GET | /assets?status=&category=&q=&page=&size= | staff, admin | def |
| GET / PATCH / DELETE | /assets/{id} | GET staff+, others admin | def |
| POST | /assets/{id}/assignments | staff, admin | def (+ async background task) |
| GET | /assets/{id}/assignments | staff, admin | def |
| POST | /assets/{id}/return | staff, admin | def (+ async background task) |
| POST | /warranty-checks | staff, admin | **async def** |
| GET | /health | anyone | def |

Errors always come back in the same shape, with the business rule when one was broken:

```json
{"error": {"code": "EMPLOYEE_INACTIVE", "message": "Employee 3 is not active", "rule": "BR5",
           "request_id": "6f1c0d0a2b9c4b8f9a6e3c2d1b0a9f8e"}}
```

Status codes: 401 no/bad token, 403 wrong role, 404 not found, 409 business rule or uniqueness, 422 invalid input (including rule breaks that are really bad dates, e.g. a return dated before the assignment).

## 3. Which endpoints are async and why

**Everything that talks to the database is a plain `def`.** SQLAlchemy is used in its normal synchronous mode, and a sync call blocks whatever thread it's on. FastAPI runs `def` endpoints in a threadpool, so a slow query only holds up that one worker thread and the event loop keeps serving other requests. If I'd written these as `async def` while still making sync DB calls, every query would freeze the whole server while it ran. Using the async SQLAlchemy driver (aiosqlite/asyncpg) was possible, but with SQLite there's little to gain, and the sync code is simpler to test.

**`POST /auth/token` is `def` on purpose.** bcrypt is deliberately slow (about 200 ms at 12 rounds) and CPU-bound. In an async endpoint it would block the event loop for every login.

**`POST /warranty-checks` is `async def`.** Its time goes on waiting for the warranty source, and those waits can overlap. It starts all the lookups with `asyncio.gather` (each wrapped in `asyncio.wait_for` for a timeout), so 20 assets take about 0.5 s instead of 10 s. The one database read it needs goes through `run_in_threadpool`, so it doesn't block the loop. `return_exceptions=True` means one failed lookup comes back as an error entry instead of failing the whole request.

**Notifications (section 5) are async functions run as `BackgroundTasks`.** The assignment is committed, the response goes back to the caller, and only then does `deliver()` run. It catches and logs any failure, so a broken downstream can't undo or delay an assignment.

**`/health` is `def`** because it pings the database (sync) to report whether the DB is reachable, and returns 503 if not.

## 4. Design notes

- **Layers.** `api/routers` only deal with HTTP; `services/` hold the rules and own the transactions; `models/` are the ORM tables; `schemas/` are the Pydantic request/response models. Services raise `AppError` subclasses (not `HTTPException`), and one handler turns them into the error shape above.
- **BR1 in the database.** Besides the status check in Python, there is a partial unique index: one row per asset where `returned_on IS NULL`. Two requests racing to assign the same asset can both pass the Python check, but only one can commit; the other gets a clean 409 BR1. There's a test that simulates exactly this.
- **BR6 in three places.** The `AssetCreate` model validator, the service (for PATCH, where only one of the dates may be sent, so it has to be checked against the stored one) and a CHECK constraint on the table.
- **No partial writes (4.6).** Each service operation runs in an `atomic()` block: commit at the end, roll back on any exception. Tested by making the commit fail after the INSERT/UPDATE have been flushed.
- **Deleting employees.** BR7 blocks deleting anyone holding an asset. For someone with only past assignments, the foreign key is `ON DELETE SET NULL` and the assignment row keeps a copy of their name and email, so the asset's history isn't lost.
- **Foreign keys** are switched on for every SQLite connection (`PRAGMA foreign_keys=ON` in `db/session.py`); SQLite ignores them otherwise.
- **Status `assigned`** can't be set through POST/PATCH on assets, only by the assignment endpoint, otherwise BR3 could be bypassed. The status also can't be changed while the asset is assigned.
- **Middleware.** A pure ASGI middleware adds `X-Request-ID` and `X-Process-Time-Ms` to every response and writes one JSON log line per request (operation, route, status, outcome, duration, request id). A second middleware inside CORS turns unexpected exceptions into a JSON 500, so crashes also get the headers, the CORS headers and a log line. CORS exposes the two headers so browser code can read them.
- **Passwords.** Stored as bcrypt hashes. Request bodies are never logged, and validation errors don't echo input back, so a password can't leak through a 422 either. Logins for unknown users still do a bcrypt comparison, so response time doesn't reveal which usernames exist.
- **Roles** are re-read from the database on each request rather than trusted from the token, so demoting or deleting a user takes effect immediately.

## 5. Deployment (section 10)

Needs Docker Desktop (Windows/macOS) or Docker Engine (Linux).

First create a file called `docker.env` (keep it out of git) with the settings the container needs. `DATABASE_URL` and `APP_ENV=production` are already set in the image.

```
SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_urlsafe(48))">
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<choose one>
STAFF_USERNAME=staff
STAFF_PASSWORD=<choose one>
CORS_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO
```

The container won't start if `SECRET_KEY` or the passwords are missing or left at the dev defaults. Then:

```powershell
docker build -t assetdesk:1.0 .
docker run -d --name assetdesk -p 8000:8000 --env-file docker.env -v assetdesk-data:/data assetdesk:1.0
docker ps                               # STATUS should become "(healthy)" within ~15 s
curl.exe -i http://localhost:8000/health
```

These commands and their output are recorded in `evidence/section-10-deployment.txt`.

Screenshots in `evidence/`:
- `section-10-deployment-docker-ps.png`: `docker ps` showing the container as healthy
- `section-10-deployment-health.png`: browser on http://localhost:8000/health
- `section-10-deployment-docs.png`: Swagger UI served from the container

The image runs as a non-root user, keeps the SQLite file in a `/data` volume, has a `HEALTHCHECK` against `/health`, runs migrations on start, and gets every secret at `docker run` time. Nothing secret is baked in: the Dockerfile copies only `requirements.txt` and the `app/` package, so a local `.env` or `docker.env` can't end up in the image.

## 6. What I would change for production

- **PostgreSQL instead of SQLite.** SQLite allows one writer at a time and lives on one machine. With Postgres I'd add `psycopg`, set `DATABASE_URL`, and use a connection pool sized to (workers × pool size) < max connections. The partial unique index and CHECK constraints already have Postgres equivalents in the migration.
- **More than one worker**, e.g. `gunicorn -k uvicorn.workers.UvicornWorker -w 4` or `uvicorn --workers 4`, behind Nginx or a cloud load balancer that handles TLS, request size limits and slow clients.
- **Migrations as a separate deploy step**, not run in the container's start command. With several replicas you don't want each one racing to migrate.
- **A real queue for notifications** (Celery/RQ/ARQ, or an outbox table). `BackgroundTasks` runs inside the web process, so if the process restarts after the commit but before the send, that notification is lost and never retried.
- **Secrets from a secrets manager** (Vault, AWS Secrets Manager, Azure Key Vault, Kubernetes secrets) injected as env vars. Proper user management instead of two seeded accounts, rate limiting and lockout on `/auth/token`, and shorter-lived access tokens with refresh tokens.
- **Observability.** Ship the JSON logs to a central store, add metrics (request rate, latency, error rate) and tracing; the request id is already there to join them up.
- **Real HTTP clients for the two external systems**, with retries, backoff and a circuit breaker. The stubs sit behind a small `Protocol`, so they can be swapped without touching the routes.

## What's not finished / known limits

- Section 10 was run on Windows 11 with Docker Desktop (engine 29.9.2, WSL 2). The commands and their output are in `evidence/section-10-deployment.txt` and the screenshots sit next to it.
- The notifier and warranty source are stubs, as the brief says. The notifier keeps its record in memory, so it resets when the service restarts.
- There is no endpoint for managing sign-in users; the two accounts come from configuration.

## Layout

```
app/
  api/            routers, dependencies (auth, db session, roles), shared error docs
  core/           settings, security (bcrypt/JWT), errors, JSON logging, request id context
  db/             engine, session-per-request, declarative base
  integrations/   notifier and warranty-source stubs
  middleware/     request id / timing / access log, unhandled error -> 500
  models/         SQLAlchemy tables
  schemas/        Pydantic request and response models
  services/       business rules and transactions
  migrations/     Alembic migrations
  init_db.py      migrate + create the sign-in accounts (+ --demo data)
tests/            one file per requirement section
evidence/         test output per section, coverage, lint, deployment
```
