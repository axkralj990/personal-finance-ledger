# Backup and Restore

The SQLite database and retained files live below the host path configured by `FINANCE_DATA_PATH`. Database backups belong in `/data/backups`. A full-volume backup of the data directory includes `/data/uploads` and `/data/models`; a SQLite-only backup includes neither directory.

## Online Database Backup

Run the included script from any directory:

```sh
git switch main
./scripts/finance.sh backup
```

It runs this application command in a one-off container:

```sh
python -m backend.app.cli backup --output /data/backups/finance-<UTC_TIMESTAMP>.sqlite3
```

The CLI uses SQLite's online backup API rather than copying a live database file. A lock directory under `/data` prevents two scheduled script runs from writing concurrently.

For Synology Task Scheduler, create a scheduled **User-defined script** under an account allowed to run Docker:

```sh
FINANCE_ENV_DIR=/volume1/docker/personal-finance/config \
  /volume1/docker/personal-finance/app/scripts/finance.sh backup \
  >> /volume1/docker/personal-finance/backup.log 2>&1
```

Monitor the task and apply an explicit retention policy appropriate to available storage. The script never deletes old backups.

## Full Backup

The SQLite database backup does not include `/data/uploads` or `/data/models`. Periodically snapshot or back up the entire `/volume1/docker/personal-finance/data` directory with Hyper Backup or Snapshot Replication. That full-volume backup includes the model artifacts under `/data/models`. Coordinate retention so a database backup and retained files from the same period remain available.

## Restore

Stop the production app before replacing database files. The commands below preserve the
current database and any WAL/SHM files in a timestamped rollback directory; uploads, backups,
and models are not changed. Set `FINANCE_DATA_PATH` to the same absolute value used in the
external production environment file.

```sh
cd /volume1/docker/personal-finance/app
export FINANCE_ENV_DIR=/volume1/docker/personal-finance/config
./scripts/finance.sh stop

export FINANCE_DATA_PATH=/volume1/docker/personal-finance/data/production
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo mkdir -p "$FINANCE_DATA_PATH/restore-$stamp"
for file in finance.sqlite3 finance.sqlite3-wal finance.sqlite3-shm; do
  if [ -e "$FINANCE_DATA_PATH/$file" ]; then
    sudo mv "$FINANCE_DATA_PATH/$file" "$FINANCE_DATA_PATH/restore-$stamp/"
  fi
done

sudo cp "$FINANCE_DATA_PATH/backups/finance-UTC_TIMESTAMP.sqlite3" \
  "$FINANCE_DATA_PATH/finance.sqlite3.restore"
sudo chown 10001:10001 "$FINANCE_DATA_PATH/finance.sqlite3.restore"
sudo chmod 600 "$FINANCE_DATA_PATH/finance.sqlite3.restore"
sudo mv "$FINANCE_DATA_PATH/finance.sqlite3.restore" \
  "$FINANCE_DATA_PATH/finance.sqlite3"

./scripts/finance.sh start
./scripts/finance.sh status
curl --fail http://127.0.0.1:8000/health
```

Replace `UTC_TIMESTAMP` and port `8000` with the selected backup and configured host port. Check logs and application aggregates before removing the timestamped rollback directory. To restore retained uploads or model artifacts, recover those directories from the matching full backup while the app remains stopped, then restore ownership to `10001:10001`.
