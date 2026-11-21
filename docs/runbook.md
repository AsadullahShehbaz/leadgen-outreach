# LeadGen deployment runbook

## Check health

```sh
cd deploy
docker compose ps
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read())"
docker compose logs --tail=100 api worker
```

The `/health` response is `503` if database or Redis is unavailable.

## Pause sending

Set `SENDING_ENABLED=false` in `deploy/.env`, then restart API and worker:

```sh
docker compose up -d api worker
```

Suppression and bounce handling remain independent of the sending kill switch.

## Backups

Set a strong `BACKUP_ENCRYPTION_KEY` in `deploy/.env`, then run:

```sh
cd deploy
./backup.sh
```

Backups are AES-256-CBC encrypted and limited by the script to 7 daily copies
and 4 weekly copies.

## Support bundles

```sh
cd deploy
./support-bundle.sh
```

The bundle excludes secret values and email bodies. Review the resulting
`support-bundle-*.tar.gz` file before sending it to support.
