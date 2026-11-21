#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

encrypted=${1:-}
confirmation=${2:-}

[ -n "$encrypted" ] || die "Usage: ./restore.sh <backup-file.enc> RESTORE"
[ "$confirmation" = "RESTORE" ] || die "Pass RESTORE as the second argument"
command -v openssl >/dev/null 2>&1 || die "openssl is required"
[ -f .env ] || die ".env not found"

BACKUP_DIR=$(CDPATH= cd -- backups && pwd)
requested=$(CDPATH= cd -- "$(dirname -- "$encrypted")" && pwd)/$(basename -- "$encrypted")
case "$requested" in
    "$BACKUP_DIR"/*) ;;
    *) die "Backup file must be inside the deployment backups directory" ;;
esac
[ -f "$requested" ] || die "Backup file not found"

get_env_value() {
    sed -n "s/^${1}=//p" .env | head -n 1
}

BACKUP_KEY=$(get_env_value BACKUP_ENCRYPTION_KEY)
[ -n "$BACKUP_KEY" ] || die "BACKUP_ENCRYPTION_KEY is required"
export BACKUP_ENCRYPTION_KEY=$BACKUP_KEY

plain=$(mktemp)
trap 'rm -f "$plain"' EXIT HUP INT TERM

openssl enc -d -aes-256-cbc -pbkdf2 \
    -pass "env:BACKUP_ENCRYPTION_KEY" \
    -in "$requested" -out "$plain" ||
    die "Backup decryption failed"

docker compose stop api worker
docker compose exec -T db psql -U leadgen -d leadgen -v ON_ERROR_STOP=1 < "$plain" ||
    die "Restore failed"

docker compose start api worker
printf 'Restore completed. Run ./update.sh <current-version> if migrations are needed.\n'
