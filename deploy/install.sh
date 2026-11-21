#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || die "Docker is required"
docker info >/dev/null 2>&1 || die "Docker is not running or is not accessible"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required to generate secrets"

if [ -n "${1:-}" ]; then
    PUBLIC_URL_INPUT=$1
else
    PUBLIC_URL_INPUT=
fi

if [ ! -f .env ]; then
    cp .env.example .env
fi

set_env_value() {
    key=$1
    value=$2
    if grep -q "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

get_env_value() {
    sed -n "s/^${1}=//p" .env | head -n 1
}

if [ -n "$PUBLIC_URL_INPUT" ]; then
    set_env_value PUBLIC_URL "$PUBLIC_URL_INPUT"
fi

PUBLIC_URL_VALUE=$(get_env_value PUBLIC_URL)
case "$PUBLIC_URL_VALUE" in
    https://*|http://localhost*|http://127.0.0.1*) ;;
    *) die "PUBLIC_URL must be https://..., http://localhost, or http://127.0.0.1" ;;
esac

DB_PASSWORD=$(get_env_value DB_PASSWORD)
if [ -z "$DB_PASSWORD" ]; then
    DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    set_env_value DB_PASSWORD "$DB_PASSWORD"
fi

SECRET_KEY_VALUE=$(get_env_value SECRET_KEY)
if [ -z "$SECRET_KEY_VALUE" ]; then
    SECRET_KEY_VALUE=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    set_env_value SECRET_KEY "$SECRET_KEY_VALUE"
fi

FERNET_KEY_VALUE=$(get_env_value FERNET_KEY)
if [ -z "$FERNET_KEY_VALUE" ]; then
    FERNET_KEY_VALUE=$(python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
    set_env_value FERNET_KEY "$FERNET_KEY_VALUE"
fi

set_env_value DATABASE_URL "postgresql://leadgen:${DB_PASSWORD}@db:5432/leadgen"

mkdir -p backups

for port in 80 443; do
    if command -v ss >/dev/null 2>&1 && ss -ltn | awk '{print $4}' | grep -Eq "(\\[::\\]|0\\.0\\.0\\.0|127\\.0\\.0\\.1):${port}$"; then
        die "Port ${port} is already in use"
    fi
done

docker compose pull
docker compose up -d

HEALTH_OK=false
i=0
while [ "$i" -lt 60 ]; do
    if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" >/dev/null 2>&1; then
        HEALTH_OK=true
        break
    fi
    i=$((i + 1))
    sleep 2
done

if [ "$HEALTH_OK" != true ]; then
    docker compose logs --tail=100 api worker
    die "Application did not become healthy"
fi

printf 'LeadGen installed successfully.\n'
printf 'Open %s/setup to complete setup.\n' "$PUBLIC_URL_VALUE"
