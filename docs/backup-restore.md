# LeadGen backup and restore

## Create a backup

Set `BACKUP_ENCRYPTION_KEY` in `deploy/.env`, then run:

```sh
cd deploy
./backup.sh
```

The plain SQL dump is deleted after encryption. The output file is stored in
`deploy/backups/`.

## Restore a backup

Restore is manual and destructive:

```sh
cd deploy
./restore.sh backups/leadgen-20261122T000000Z.sql.enc RESTORE
```

The backup must resolve inside `deploy/backups/`. The script stops API and worker,
decrypts locally, restores Postgres, and restarts API and worker.

Test restores before relying on a deployment backup process.
