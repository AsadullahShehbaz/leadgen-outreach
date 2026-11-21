#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

NEW_VERSION=${1:-}
[ -n "$NEW_VERSION" ] || die "Usage: ./update.sh <version>"

get_env_value() {
    sed -n "s/^${1}=//p" .env | head -n 1
}

set_env_value() {
    key=$1
    value=$2
    if grep -q "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

[ -f .env ] || die ".env not found"
OLD_VERSION=$(get_env_value VERSION)
[ -n "$OLD_VERSION" ] || OLD_VERSION=latest

set_env_value VERSION "$NEW_VERSION"

rollback() {
    set_env_value VERSION "$OLD_VERSION"
    docker compose up -d api worker || true
}

printf 'Updating from %s to %s\n' "$OLD_VERSION" "$NEW_VERSION"

if ! docker compose pull api worker; then
    rollback
    die "Image pull failed; previous version restored"
fi

if ! docker compose up -d api worker; then
    rollback
    die "Container startup failed; previous version restored"
fi

HEALTH_OK=false
i=0
while [ "$i" -lt 30 ]; do
    if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" >/dev/null 2>&1; then
        HEALTH_OK=true
        break
    fi
    i=$((i + 1))
    sleep 2
done

if [ "$HEALTH_OK" != true ]; then
    rollback
    die "Health check failed; previous version restored"
fi

printf 'Update to %s completed successfully.\n' "$NEW_VERSION"
