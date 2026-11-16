"""Section 9: API docs, configuration, health check."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import DEV_SECRET_KEY, Settings
from app.db.session import build_engine, get_db

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TAGS = {"Auth", "Employees", "Assets", "Assignments", "Warranty", "Health"}


class TestDocs:
    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_docs_published_without_sign_in(self, client, path):
        assert client.get(path).status_code == 200

    def test_grouped_by_area_with_descriptions(self, client):
        spec = client.get("/openapi.json").json()
        tags = {t["name"]: t["description"] for t in spec["tags"]}
        assert set(tags) == EXPECTED_TAGS
        assert all(len(d) > 10 for d in tags.values())

    def test_every_operation_documented(self, client):
        spec = client.get("/openapi.json").json()
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                where = f"{method.upper()} {path}"
                assert op.get("summary"), where
                assert len(op["tags"]) == 1 and op["tags"][0] in EXPECTED_TAGS, where
                success = [c for c in op["responses"] if c.startswith("2")]
                assert success, where
                if success[0] != "204":
                    assert "schema" in op["responses"][success[0]]["content"]["application/json"], where

    def test_error_responses_documented(self, client):
        op = client.get("/openapi.json").json()["paths"]["/assets/{asset_id}/assignments"]["post"]
        assert {"401", "404", "409", "422"} <= set(op["responses"])
        assert op["responses"]["409"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "ErrorResponse"
        )

    def test_bearer_auth_in_docs(self, client):
        schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
        assert schemes["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/auth/token"


class TestConfiguration:
    def test_defaults_work_locally(self, monkeypatch):
        for var in ("DATABASE_URL", "APP_ENV", "SECRET_KEY", "CORS_ORIGINS"):
            monkeypatch.delenv(var, raising=False)
        s = Settings(_env_file=None)
        assert s.app_env == "development"
        assert s.database_url == "sqlite:///./assetdesk.db"
        assert s.access_token_expire_minutes == 30

    def test_settings_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db/assetdesk")
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
        monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com, https://b.example.com")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        s = Settings(_env_file=None)
        assert s.database_url == "postgresql+psycopg://u:p@db/assetdesk"
        assert s.access_token_expire_minutes == 15
        assert s.cors_origins == ["https://a.example.com", "https://b.example.com"]
        assert s.log_level == "WARNING"

    def test_settings_read_from_env_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("APP_NAME", raising=False)
        env = tmp_path / ".env"
        env.write_text("APP_NAME=FromFile\n")
        assert Settings(_env_file=env).app_name == "FromFile"

    @pytest.mark.parametrize(
        "var,value",
        [
            ("ACCESS_TOKEN_EXPIRE_MINUTES", "0"),
            ("ACCESS_TOKEN_EXPIRE_MINUTES", "soon"),
            ("APP_ENV", "staging"),
            ("LOG_LEVEL", "LOUD"),
        ],
    )
    def test_bad_setting_refused_at_startup(self, monkeypatch, var, value):
        monkeypatch.setenv(var, value)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_production_refuses_dev_secret(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(_env_file=None, app_env="production")
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(_env_file=None, app_env="production", secret_key="short")

    def test_production_refuses_default_passwords(self):
        with pytest.raises(ValidationError, match="ADMIN_PASSWORD"):
            Settings(_env_file=None, app_env="production", secret_key="k" * 40)

    def test_production_accepts_real_settings(self):
        s = Settings(
            _env_file=None,
            app_env="production",
            secret_key="k" * 40,
            admin_password="a-real-admin-password",
            staff_password="a-real-staff-password",
        )
        assert s.secret_key != DEV_SECRET_KEY

    def test_token_lifetime_comes_from_settings(self, client, settings):
        resp = client.post("/auth/token", data={"username": "admin", "password": "admin-test-pw"})
        assert resp.json()["expires_in"] == settings.access_token_expire_minutes * 60

    def test_env_sample_lists_every_setting(self):
        sample = (ROOT / ".env.sample").read_text()
        documented = set(re.findall(r"^#?\s*([A-Z_]+)=", sample, flags=re.MULTILINE))
        expected = {name.upper() for name in Settings.model_fields}
        assert expected <= documented, f"missing from .env.sample: {expected - documented}"

    def test_no_secret_hard_coded_in_app(self):
        source = "\n".join(p.read_text() for p in (ROOT / "app").rglob("*.py"))
        assert "admin-test-pw" not in source
        assert re.search(r"secret_key\s*=\s*['\"]", source) is None


class TestHealth:
    def test_health_without_sign_in(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "version": "1.0.0", "database": "ok"}

    def test_health_reports_database_down(self, app, client, tmp_path):
        broken = build_engine(f"sqlite:///{tmp_path / 'missing-dir' / 'nope.db'}")

        def unreachable_db():
            db = Session(bind=broken)
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = unreachable_db
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "degraded"
        assert resp.json()["database"] == "unavailable"

    def test_health_only_allows_get(self, client):
        assert client.post("/health").status_code == 405
