from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DEPLOY = ROOT / "deploy"

# The API container mounts only the backend folder, so the deployment files
# are not available there. Run these tests on the host instead.
pytestmark = pytest.mark.skipif(
    not (DEPLOY / "docker-compose.yml").is_file(),
    reason="deployment files are not available in this environment",
)


def test_compose_services_and_volumes():
    text = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    for service in ("caddy:", "api:", "worker:", "db:", "redis:"):
        assert service in text
    for volume in ("caddy_data:", "pgdata:", "redisdata:", "caddy_config:"):
        assert volume in text
    assert '"80:80"' in text
    assert '"443:443"' in text
    assert "5432:5432" not in text
    assert "6379:6379" not in text


def test_caddy_routes_api_and_static_files():
    text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    assert "handle /api/*" in text
    assert "uri strip_prefix /api" in text
    assert "reverse_proxy api:8000" in text
    assert "file_server" in text


def test_environment_example_has_no_secret_values():
    text = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    for key in (
        "PUBLIC_URL=", "VERSION=", "REGISTRY_IMAGE=", "DB_PASSWORD=",
        "DATABASE_URL=", "REDIS_URL=", "SECRET_KEY=", "FERNET_KEY=",
        "LICENSE_PUBLIC_KEY_PEM=", "LLM_API_KEY=", "BACKUP_ENCRYPTION_KEY=",
    ):
        assert key in text
    for line in text.splitlines():
        if line.startswith(("DB_PASSWORD=", "SECRET_KEY=", "FERNET_KEY=",
                           "LLM_API_KEY=", "BACKUP_ENCRYPTION_KEY=")):
            assert line.endswith("=")


def test_dockerfile_is_nonroot_and_never_copies_env():
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    assert "USER appuser" in text
    assert "COPY .env" not in text
    assert "COPY app /app/app" in text
    assert "alembic upgrade head" not in text


def test_install_and_update_have_bounded_health_and_rollback():
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    update = (DEPLOY / "update.sh").read_text(encoding="utf-8")
    assert "docker compose pull" in install
    assert "docker compose up -d" in install
    assert '"$i" -lt 60' in install
    assert "rollback()" in update
    assert "OLD_VERSION" in update
    assert "set_env_value VERSION \"$OLD_VERSION\"" in update
    assert "pgdata" not in update
    assert "redisdata" not in update
    assert "docker volume rm" not in update


def test_backup_restore_and_support_bundle_are_safe():
    backup = (DEPLOY / "backup.sh").read_text(encoding="utf-8")
    restore = (DEPLOY / "restore.sh").read_text(encoding="utf-8")
    support = (DEPLOY / "support-bundle.sh").read_text(encoding="utf-8")

    assert "-mtime +7 -delete" in backup
    assert "aes-256-cbc" in backup
    assert "[ \"$confirmation\" = \"RESTORE\" ]" in restore
    assert 'case "$requested" in' in restore
    assert "BACKUP_DIR" in restore
    assert "stop api worker" in restore

    assert "FERNET_KEY" in support
    assert "LLM_API_KEY" in support
    assert "<redacted>" in support
    assert "Email body" in support
