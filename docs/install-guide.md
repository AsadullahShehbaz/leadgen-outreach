# LeadGen dedicated deployment install guide

## Requirements

- A Linux VPS with Docker and Docker Compose v2.
- Ports 80 and 443 open.
- A public hostname that resolves to the VPS.
- A private application image in a registry.

## Install

1. Copy the `deploy` directory to the VPS.
2. Set the application image in `deploy/.env.example` or export it when starting.
3. Run:

   ```sh
   cd deploy
   ./install.sh https://leadgen.example.com
   ```

4. Open `https://leadgen.example.com/setup`.

The script generates `SECRET_KEY`, `FERNET_KEY`, and `DB_PASSWORD`. It never
prints these values. Replace `BACKUP_ENCRYPTION_KEY` before creating backups.

## Services

Docker Compose runs Caddy, the FastAPI API, the ARQ worker, Postgres, and Redis.
Postgres and Redis are only available inside the Compose network.

## Updates

```sh
cd deploy
./update.sh 2026-11-22
```

The update script pulls and starts the requested application version. If the
health check fails, it restores the previous version. It never deletes database
or Redis volumes.

## Rollback

Run the update script with the last known good version:

```sh
./update.sh <previous-version>
```
