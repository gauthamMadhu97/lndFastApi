FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependencies first: this layer is reused as long as requirements.txt doesn't change.
# Only the runtime part goes in the image; everything from "# --- tests" down is test/lint tooling.
# The pip cache is a BuildKit cache mount: it speeds up rebuilds but is not stored in the image.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    sed '/^# --- tests/,$d' requirements.txt > /tmp/runtime.txt \
    && pip install --timeout 120 --retries 10 -r /tmp/runtime.txt \
    && rm /tmp/runtime.txt

# Unprivileged user; /data holds the SQLite file and is meant to be a volume
RUN useradd --create-home --uid 10001 appuser \
    && mkdir /data && chown appuser:appuser /data

# Only the application package goes in (it includes the migrations), nothing else from the folder
COPY --chown=appuser:appuser app ./app

USER appuser

# Defaults that suit the container; everything else (SECRET_KEY, passwords...) is
# supplied at "docker run" time with -e or --env-file
ENV DATABASE_URL=sqlite:////data/assetdesk.db \
    APP_ENV=production

VOLUME ["/data"]
EXPOSE 8000

# slim has no curl, so use Python for the check
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# Migrate + seed, then hand PID 1 over to uvicorn so it receives stop signals.
# One worker because SQLite allows a single writer; see README for production.
# --no-access-log because the app writes its own structured access log.
CMD ["sh", "-c", "python -m app.init_db && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --no-server-header --no-access-log"]
