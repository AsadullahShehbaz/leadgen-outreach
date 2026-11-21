#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

command -v sed >/dev/null 2>&1 || die "sed is required for redaction"
command -v docker >/dev/null 2>&1 || die "Docker is required"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
bundle="support-bundle-${stamp}"
mkdir -p "$bundle"

docker compose ps > "$bundle/container-status.txt" 2>&1 || true
docker compose version > "$bundle/compose-version.txt" 2>&1 || true

if [ -f .env ]; then
    sed -E \
        -e '/^(SECRET_KEY|FERNET_KEY|DB_PASSWORD|BACKUP_ENCRYPTION_KEY|LICENSE_TOKEN|LLM_API_KEY|VERIFIER_API_KEY|APOLLO_API_KEY|APIFY_TOKEN|SMTP_PASSWORD|IMAP_PASSWORD)=/ s/=.*$/=<redacted>/' \
        -e '/LICENSE_PUBLIC_KEY_PEM=/ s/=.*$/=<present-or-empty>/' \
        .env > "$bundle/env-redacted.txt"
else
    printf 'missing\n' > "$bundle/env-redacted.txt"
fi

docker compose logs --tail=500 api worker db redis caddy 2>&1 |
    sed -E \
        -e 's/(Bearer )[A-Za-z0-9._-]+/\1<redacted>/Ig' \
        -e 's/((password|secret|token|api[_-]?key|license)[=: ])[^\s,&]+/\1<redacted>/Ig' \
        -e '/(Subject:|Body:|Email body)/Id' \
        > "$bundle/logs-redacted.txt" || true

printf 'No backup passwords or email bodies are included.\n' > "$bundle/notice.txt"
tar -czf "${bundle}.tar.gz" "$bundle"
rm -rf "$bundle"

printf 'Support bundle: %s\n' "${bundle}.tar.gz"
