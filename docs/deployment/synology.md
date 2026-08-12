# Synology Deployment

This runbook deploys one application container through Synology Container Manager. It uses SQLite and a host directory mounted at `/data`; there is no external database, worker, or bundled reverse proxy.

## Security Boundary

The application has no authentication or authorization. Keep it on a trusted LAN or behind a VPN. Do not forward its port from the public internet. A Synology reverse proxy can provide TLS and a friendly hostname, but it does not add application authentication by itself.

## Prepare the Filesystem

Choose separate locations for the project files and persistent data. The examples use:

```text
/volume1/docker/personal-finance/app
/volume1/docker/personal-finance/data
```

Create the data directory over SSH or with an equivalent DSM file-management workflow:

```sh
sudo mkdir -p /volume1/docker/personal-finance/data
sudo chown -R 10001:10001 /volume1/docker/personal-finance/data
sudo chmod 750 /volume1/docker/personal-finance/data
```

The image runs as UID/GID `10001:10001`. The directory must remain writable by that identity. Place the repository or an exported release in `/volume1/docker/personal-finance/app`, then create its environment file:

```sh
cd /volume1/docker/personal-finance/app
cp .env.example .env
```

Set at least these values in `.env`:

```dotenv
FINANCE_DATA_PATH=/volume1/docker/personal-finance/data
FINANCE_HOST_PORT=8000
TIMEZONE=Europe/Ljubljana
MAX_UPLOAD_BYTES=20971520
MAX_FILE_ROWS=20000
QUOTE_PREVIEW_MAX_AGE_HOURS=24
```

`FINANCE_DATA_PATH` is a host path. Compose mounts it at the fixed container `DATA_DIR=/data`. `FRONTEND_DIST_PATH` is fixed at `/app/frontend/dist`.
Manual portfolio valuations, ECB FX previews, and Yahoo Finance quotes work without an API
key. Keep local settings only in `.env`; do not place them in `compose.yaml`,
source control, screenshots, or logs.

## Create the Container Manager Project

1. Open **Container Manager > Project > Create**.
2. Select `/volume1/docker/personal-finance/app` as the project path.
3. Use the existing `compose.yaml` in that directory.
4. Build and start the project.

The equivalent SSH commands are:

```sh
cd /volume1/docker/personal-finance/app
docker compose config
docker compose build --pull
docker compose up -d
```

No source directory is mounted into the container. Only the persistent data directory is mounted.

## Network and Reverse Proxy

Browse directly to `http://NAS-LAN-IP:8000`, replacing `8000` with `FINANCE_HOST_PORT`. If the port conflicts, change only `FINANCE_HOST_PORT` and recreate the service.

For a DSM reverse proxy, create an HTTPS source hostname and send it to `http://127.0.0.1:<FINANCE_HOST_PORT>`. Use a valid certificate and restrict access to LAN/VPN clients. Do not interpret HTTPS or the reverse proxy as authentication.

## Health and Logs

The container initializes the schema, seeds source accounts, and then reports healthy when `/health` returns successfully:

```sh
docker compose ps
curl --fail http://127.0.0.1:8000/health
docker compose logs --tail=100 app
```

Container logs use the `json-file` driver with three 10 MB files. Avoid pasting import output or transaction details into support channels.

## Updates

Back up first, then retain the current image as a local rollback target and build the update:

```sh
cd /volume1/docker/personal-finance/app
./scripts/backup.sh
docker image tag personal-finance:latest personal-finance:rollback-YYYYMMDD
docker compose build --pull
docker compose up -d
docker compose ps
```

Run the health check and inspect logs after every update. Database migrations run automatically at startup.

## Rollback

To run the retained image without rebuilding it:

```sh
cd /volume1/docker/personal-finance/app
FINANCE_IMAGE_TAG=rollback-YYYYMMDD docker compose up -d --no-build app
docker compose ps
```

An older application image might not support a newer database schema. If application rollback alone fails, stop the app and restore the matching pre-update backup using [backup and restore](backup-restore.md).

## Architecture Notes

The Dockerfile uses official multi-architecture Node 24 and Python 3.12 Debian images and contains no architecture-specific binaries or source paths. Build or publish the same Dockerfile for `linux/amd64` and `linux/arm64`; native Container Manager builds select the NAS architecture automatically.

The service deliberately runs one Uvicorn worker. SQLite uses WAL mode and persists the database, WAL/SHM state, retained uploads, backups, and future model artifacts under `/data`. Running multiple application workers or replicas against this deployment is unsupported.

For registry publishing from a multi-platform builder:

```sh
docker buildx build --platform linux/amd64,linux/arm64 -t REGISTRY/personal-finance:VERSION --push .
```

Multi-platform output requires a Buildx builder that supports it. A local native build is sufficient when deploying directly on one NAS.
