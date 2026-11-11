# Part B answers

## 1. What FastAPI does with type hints

When the app starts, FastAPI reads the signature of every path operation function and works out where each parameter comes from. A name that appears in the path (`asset_id: int` in `/assets/{asset_id}`) is a path parameter. A Pydantic model (`body: AssignmentCreate`) is the JSON body. Something wrapped in `Depends(...)` is a dependency to resolve first. In `list_assets` I used `query: Annotated[AssetListQuery, Query()]`, so the whole query string is read into one model. The hints also drive the response: the return annotation and `response_model=AssetRead` decide what gets serialised and which fields are left out. And the same information is turned into the OpenAPI schema, which is why `/docs` knows that `status` is one of four values without me writing that anywhere else.

The validation itself is done by Pydantic (v2, whose core is written in Rust as `pydantic-core`). FastAPI builds a validator from the hints and runs the incoming data through it, converting types along the way (`"2025-01-01"` becomes a `date`, `"3"` becomes `3`). If that fails, it raises `RequestValidationError`, which I turn into our 422 error shape. So `GET /assets?status=broken` never reaches my code, because `AssetStatus` doesn't have that value, and `size=500` is refused because of `Field(le=100)`.

## 2. Starlette, Uvicorn and where my code sits

Uvicorn is the server. It opens the socket, accepts connections, parses raw HTTP bytes, runs the asyncio event loop (uvloop on Linux), and calls the application through the ASGI interface with a `scope` dict plus `receive`/`send` functions. Starlette is the ASGI toolkit underneath FastAPI. It provides routing, `Request`/`Response`, the middleware stack, `BackgroundTasks`, exception handling, CORS middleware and the test client. FastAPI sits on top of Starlette and adds the type-hint-driven parts: validation, dependency injection, serialisation and OpenAPI.

My code sits inside that stack. Uvicorn calls the outermost middleware, which in my case is `RequestContextMiddleware` (my own ASGI class), then CORS, then my `UnhandledErrorMiddleware`, then Starlette's routing, then FastAPI resolving dependencies (`get_db`, `get_current_user`) and calling my route function, which calls a service. An ASGI server is needed because WSGI is synchronous: one request ties up one thread from start to finish, and there's no event loop. My warranty endpoint `await`s 20 lookups at once and my notifications run after the response is sent. Neither is possible under WSGI. ASGI also covers WebSockets and long-lived connections, which WSGI can't.

## 3. async vs sync endpoints

For an `async def` endpoint, FastAPI awaits it directly on the event loop. For a plain `def` endpoint, it runs the function in a threadpool (through `anyio.to_thread`) and awaits the result, so the loop stays free while the thread does the work. Most of my endpoints are `def` because they use synchronous SQLAlchemy. `check_warranty` is `async def` because its work is waiting on I/O that can overlap. The same rule applies to dependencies: `get_db` and `get_current_user` are sync, so they also run in the threadpool even when the endpoint is async.

If a blocking call is made inside an `async def` endpoint, it blocks the event loop thread, and every other request on that worker stops until it finishes. A simple way to see it: put `time.sleep(0.5)` inside the warranty stub instead of `await asyncio.sleep(0.5)`. The 20-asset check then takes 10 seconds instead of 0.5, and `/health` hangs for that whole time. That's also why the one database lookup in `check_warranty` is wrapped in `run_in_threadpool`, and why `login` is a `def`: bcrypt takes about 200 ms of CPU on purpose, and doing that on the loop would stall every other request.

## 4. Dependency injection and the database session

Dependency injection lets a route say what it needs (a session, the current user, the settings, the notifier) and leaves FastAPI to provide it. Dependencies can depend on other dependencies: `require_admin` depends on `get_current_user`, which depends on `oauth2_scheme`, `get_db` and `get_settings`. FastAPI resolves that chain once per request and caches each result within the request, so the route and the auth check share the same session. It keeps cross-cutting concerns out of the route bodies. Auth is attached once at router level with `dependencies=[Depends(get_current_user)]`, not repeated in every function.

The session comes through `get_db` because it is a resource with a lifecycle: open at the start of the request, close at the end even if the handler raised. `get_db` is a generator with `try/yield/finally`, so cleanup always happens and that logic lives in one place. If each route created its own session, every route would need its own `try/finally`, and one forgotten `close()` would leak connections from the pool. The bigger win for me was testing. `conftest.py` sets `app.dependency_overrides[get_db]` to a session on a temporary SQLite file, and the routes don't know the difference. The health test overrides it again with an engine pointing at a missing directory to check the 503 path. Without DI I'd have had to monkeypatch module globals.

## 5. Separate request and response models

They describe different things. A request model is what the client is *allowed to send*, and a response model is what we are *willing to show*. They overlap but they aren't the same set of fields, and the rules on them differ.

Examples from my code:

- **Users.** The `User` table has `password_hash`. `UserRead` (returned by `/auth/me`) has only `id`, `username` and `role`. If the ORM object or a shared model were returned, the hash would go out in the response. There's a test that checks "password" doesn't appear in that response.
- **Assets.** `AssetCreate` has no `id`, and its `status` validator refuses `assigned`, because only the assignment endpoint may set that (BR3). It also checks the BR6 date rule and that the purchase date isn't in the future. `AssetRead` must include `id` and must be able to show `assigned`. With one shared model, either clients could send `"status": "assigned"` and get round BR1-BR3, or the API couldn't return assigned assets. `AssetDetail` adds `current_holder`, which isn't a column at all.
- **PATCH.** `AssetUpdate` makes every field optional so a partial update works. A response model like that would tell clients that any field might be missing.

My request models also use `extra="forbid"`, so a typo like `"emial"` gets a 422 instead of being silently ignored. Response models use `from_attributes=True` so they can be built from ORM objects. Those are opposite settings, and having separate base classes (`RequestModel`, `ResponseModel`) makes that clear.

## 6. Running for real traffic

I'd run it with several worker processes, either `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 --bind 0.0.0.0:8000 --timeout 30` or plain `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers`. Each process has its own event loop and its own threadpool, so the workers are what give real parallelism across CPU cores (Python threads don't, because of the GIL). For the starting number I'd use the usual (2 × CPU cores) + 1 and then load test, for example with Locust or k6 against a realistic mix of list, assign and warranty requests. I'd watch p95 latency, CPU and memory, and adjust. This service mostly waits on the database, so it could take more workers than cores. Logins are CPU-heavy because of bcrypt, so a burst of sign-ins would push towards fewer. On Kubernetes I'd usually run one or two workers per pod and scale the number of pods instead.

The database has to change. SQLite allows one writer at a time, so several workers would queue on writes and eventually hit "database is locked". It also lives on a single disk, so it can't be shared between machines. I'd move to PostgreSQL: set `DATABASE_URL` to a `postgresql+psycopg://` URL and run the same Alembic migrations (the partial unique index and CHECK constraints already have Postgres versions). Then I'd size the SQLAlchemy pool so that workers × (pool_size + max_overflow) stays below the server's `max_connections`, or put PgBouncer in front. `pool_pre_ping=True` is already set for non-SQLite URLs, so dropped connections are detected.

## 7. Development vs production command

In development I run `uvicorn app.main:app --reload`. That's one process, bound to 127.0.0.1, with a file watcher (watchfiles) that restarts the server whenever a `.py` file changes. In production it's something like `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --no-access-log` (or Gunicorn managing Uvicorn workers). It listens on all interfaces, runs several workers, trusts `X-Forwarded-*` from the proxy, and has no reloader. Config also differs: `APP_ENV=production`, a real `SECRET_KEY` and real passwords, which my settings class enforces at startup.

`--reload` must not be used in production for a few reasons. It runs a supervisor process that polls the file system, which costs CPU for nothing on a server where the code shouldn't change. It can't be combined with `--workers`, so you'd be stuck with one process. A restart kills requests that are still running and drops background tasks, so a notification queued after an assignment could be lost. And if anything writes a `.py` file into the app directory (a deploy tool, a mounted volume, an attacker), the server restarts and runs it without anyone deciding to deploy.

## 8. Dockerfile choices and runtime configuration

The choices in my Dockerfile:

- **Base image.** `python:3.12-slim` is the Debian base without compilers and docs. All my dependencies ship wheels, so I don't need the full image, and Alpine's musl causes trouble with some wheels.
- **Layer order.** `requirements.txt` is copied and installed before the code, so changing a route reuses the cached dependency layer and rebuilds in seconds.
- **Python settings.** `PYTHONDONTWRITEBYTECODE` and `PYTHONUNBUFFERED` stop `.pyc` clutter and make logs appear straight away in `docker logs`. `PIP_NO_CACHE_DIR` keeps the image smaller.
- **Non-root.** The service runs as user `appuser` (uid 10001), so a compromise inside the app isn't root in the container.
- **Data.** `/data` is declared as a volume for the SQLite file, so data survives the container being replaced.
- **Healthcheck.** `HEALTHCHECK` calls `/health` with Python's `urllib` because slim has no curl. `docker ps` shows `(healthy)` and orchestrators can act on it.
- **Startup.** The `CMD` runs `init_db` (migrations and seed) and then `exec`s Uvicorn, so Uvicorn is PID 1 and receives SIGTERM for a clean shutdown. There's no `--reload`, and Uvicorn's own access log is off because the app writes its own.
- **Explicit copies only.** The Dockerfile copies `requirements.txt` and the `app/` package and nothing else (the migrations live inside `app/`). A local `.env`, `docker.env`, the venv, the tests or a local database can't end up in the image by accident.

Configuration is supplied when the container starts (`--env-file docker.env`, or `-e`) and not built in. The same image can then be promoted unchanged from test to staging to production, with only the settings differing. That's the "build once, configure per environment" idea from twelve-factor apps. Secrets baked into an image stay in its layers for good. Anyone who can pull the image can read them with `docker history` or by unpacking the layers, and they end up in registries and caches. Rotating a key would also mean rebuilding. The image only sets two harmless defaults (`DATABASE_URL` pointing at the volume, `APP_ENV=production`). Because of the production check in `Settings`, the container refuses to start if nobody supplied a real `SECRET_KEY` and passwords, rather than quietly running with dev values.

## 9. What sits in front of Uvicorn

Normally a reverse proxy or load balancer: Nginx, Traefik, HAProxy, or a cloud load balancer (AWS ALB, Azure Application Gateway), often with a CDN or WAF in front of that. Its jobs:

- **TLS.** It terminates HTTPS, holds the certificates and renews them.
- **Load balancing.** It spreads requests across several Uvicorn instances or containers and takes unhealthy ones out of rotation using the health check.
- **Slow clients.** It buffers slow uploads and downloads, so a client on a bad connection doesn't hold a worker open.
- **Protection.** It applies request size limits, connection limits and rate limiting (useful on `/auth/token`), plus IP allow-lists and a WAF.
- **Static content.** It handles compression and caching, and serves any static files.
- **Proxy headers.** It sets `X-Forwarded-For` / `X-Forwarded-Proto` so the app knows the real client and scheme. That's why the container runs with `--proxy-headers`.
- **Shared access logs and HTTP/2 or HTTP/3** towards clients.

Uvicorn could serve TLS with `--ssl-keyfile`, but it doesn't renew certificates, balance load across machines, rate limit or protect against slow clients very well. It's meant to be the fast application server behind the proxy, not the edge.

## 10. Changing the database structure on a live deployment

Through migrations. The schema is defined by the models, and each change gets an Alembic revision in `app/migrations/versions` (`python -m app.init_db --new-migration "..."`, which runs Alembic's autogenerate, then I read and fix what it generated). That revision is reviewed and committed like code. On deploy, the upgrade to `head` applies only the revisions the database doesn't have yet; Alembic tracks this in its `alembic_version` table. In my container that runs from `init_db` at startup. With several replicas I'd make it a separate one-off job that runs before the new version is rolled out, so replicas don't race each other. Before running it, I'd take a backup and try the migration on a copy of production data.

What can go wrong if it's done carelessly:

- **Data loss.** Autogenerate sees a renamed column as drop-plus-add, so the data in it is gone.
- **Old code breaking.** During a rolling deploy, old and new code run at the same time. If the migration drops or renames a column the old code still reads, the old instances start failing. The safe way is expand and contract: add the new column (nullable), deploy code that writes both, backfill, switch reads, and only drop the old column in a later release.
- **Failed NOT NULL changes.** Adding a NOT NULL column without a default fails on a table that already has rows.
- **Locks.** On a big table, adding an index or rewriting a column can lock it for minutes. In Postgres I'd use `CREATE INDEX CONCURRENTLY`.
- **Half-applied migrations.** A failure halfway can leave the schema in an in-between state. Postgres runs DDL in a transaction, MySQL doesn't, and SQLite needs Alembic's batch mode (which I turned on) because it can't alter most constraints in place.
- **Unique constraints on dirty data.** Adding something like my one-open-assignment index fails if existing rows already break it, so the data has to be cleaned first.
- **No way back.** A downgrade that can't recreate dropped data isn't really a way back, so the backup matters.

## 11. Secrets in production

The code only reads secrets from the environment, through `Settings` in `app/core/config.py`. The repository only contains `.env.sample`, which has placeholders and no real values. The real `.env` and `docker.env` are never added. For this submission I kept the ignore rules local (`.git/info/exclude`) so the repository holds only what the brief asks for; in a team repository they'd go in a committed `.gitignore` so everyone gets them. The Docker image can't pick them up either, because the Dockerfile only copies `app/` and `requirements.txt`. In production the values come from the platform. That means a secrets manager (Azure Key Vault, AWS Secrets Manager, HashiCorp Vault), Kubernetes Secrets mounted as env vars, Docker/Swarm secrets, or the CI/CD system's protected variables at deploy time. Access to them is limited and audited, and rotating a secret is a redeploy, not a code change. The production check in `Settings` acts as a backstop: if the real secret didn't arrive, the service won't start with the dev default.

To check nothing has been committed:

- **Before committing.** Run a scanner over the whole history, not just the current files, e.g. `gitleaks detect --source . --log-opts="--all"` or `trufflehog git file://.`, and also as a pre-commit hook (`detect-secrets` or gitleaks) so it's caught first.
- **In CI.** Run the same scan on every push and block the merge if it finds something. GitHub's secret scanning and push protection do this server-side as well.
- **Quick manual checks.** `git ls-files | findstr /i ".env"` (should only list `.env.sample`), and `git log -p | findstr /i "SECRET_KEY password"`. I also have a test, `test_no_secret_hard_coded_in_app`, that fails if a `secret_key = "..."` literal or the test password appears in `app/`.
- **If one is found.** Deleting it in a new commit isn't enough, because it's still in history and anyone who cloned has it. The secret has to be rotated first, and then the history rewritten (`git filter-repo` or BFG).
