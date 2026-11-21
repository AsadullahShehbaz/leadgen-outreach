#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || die "Docker is required"
command -v openssl >/dev/null 2>&1 || die "openssl is required for encrypted backups"

get_env_value() {
    sed -n "s/^${1}=//p" .env | head -n 1
}

[ -f .env ] || die ".env not found"
BACKUP_KEY=$(get_env_value BACKUP_ENCRYPTION_KEY)
[ -n "$BACKUP_KEY" ] || die "BACKUP_ENCRYPTION_KEY is required"
export BACKUP_ENCRYPTION_KEY=$BACKUP_KEY

mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
plain="backups/leadgen-${stamp}.sql"
encrypted="${plain}.enc"

docker compose exec -T db pg_dump -U leadgen -d leadgen > "$plain" ||
    { rm -f "$plain"; die "Database backup failed"; }

openssl enc -aes-256-cbc -salt -pbkdf2 \
    -pass "env:BACKUP_ENCRYPTION_KEY" \
    -in "$plain" -out "$encrypted"
rm -f "$plain"

find backups -type f -name 'leadgen-*.sql.enc' -mtime +7 -delete
printf 'Encrypted backup created: %s\n' "$encrypted"
