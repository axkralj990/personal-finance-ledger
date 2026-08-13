# Synology Deployment

This runbook deploys the production application container on Synology. It uses SQLite and an
external host directory mounted at `/data`; there is no external database, worker, or bundled
reverse proxy. The commands use the repository wrapper so the environment file, Compose project,
and Compose files cannot be selected implicitly.

## Security Boundary

The application has no authentication or authorization. Keep it on a trusted LAN or behind a VPN. Do not forward its port from the public internet. A Synology reverse proxy can provide TLS and a friendly hostname, but it does not add application authentication by itself.

## Prepare the Filesystem

Choose separate locations for project files, production data, test data, and host configuration.
The examples use:

```text
/volume1/docker/personal-finance/app
/volume1/docker/personal-finance/data/production
/volume1/docker/personal-finance/data/test
/volume1/docker/personal-finance/config
```

Create the data directory over SSH or with an equivalent DSM file-management workflow:

```sh
sudo mkdir -p /volume1/docker/personal-finance/data/production
sudo mkdir -p /volume1/docker/personal-finance/data/test
sudo mkdir -p /volume1/docker/personal-finance/config
sudo chown -R 10001:10001 /volume1/docker/personal-finance/data
sudo chmod 750 /volume1/docker/personal-finance/data/production
sudo chmod 750 /volume1/docker/personal-finance/data/test
```

The image runs as UID/GID `10001:10001`. Both data directories must remain writable by that
identity. Place the repository or an exported release in
`/volume1/docker/personal-finance/app`, then create the external production environment file:

```sh
cd /volume1/docker/personal-finance/app
cp environments/main.env.example \
  /volume1/docker/personal-finance/config/main.env
chmod 600 /volume1/docker/personal-finance/config/main.env
```

Set at least these values in `/volume1/docker/personal-finance/config/main.env`:

```dotenv
FINANCE_DATA_PATH=/volume1/docker/personal-finance/data/production
FINANCE_HOST_PORT=8000
TIMEZONE=Europe/Ljubljana
MAX_UPLOAD_BYTES=20971520
MAX_FILE_ROWS=20000
QUOTE_PREVIEW_MAX_AGE_HOURS=24
ALLOWED_HOSTS=NAS-LAN-IP,finance.example.internal
ALLOWED_ORIGINS=http://NAS-LAN-IP:8000,https://finance.example.internal
```

`FINANCE_DATA_PATH` is required, absolute, external to the Git root or exported release directory,
and must already exist. `FINANCE_HOST_PORT` must be numeric and between 1 and 65535. If both
production and test environment files exist, their host ports and data directories must differ.
Compose mounts it at the fixed container `DATA_DIR=/data`. `FRONTEND_DIST_PATH` is fixed at
`/app/frontend/dist`.
Manual portfolio valuations, ECB FX previews, and Yahoo Finance quotes work without an API
key. Keep local settings only in the external environment file; do not place them in `compose.yaml`,
source control, screenshots, or logs.

OpenAI import mapping is optional and disabled by default. If enabled, place
`OPENAI_MAPPING_ENABLED=true` and `OPENAI_API_KEY` only in the permission-restricted environment file,
and select the provider's lowest retention/data-use setting. Never expose the key to the
browser or support logs. Mapping sends headers and locally redacted representative values;
manual mapping remains available when the provider is unavailable. `ALLOWED_HOSTS` must list
each exact hostname accepted by the app, without a scheme. `ALLOWED_ORIGINS` must list each
corresponding browser origin, including scheme and non-default port. Separate multiple values
with commas.

## Start Production

Set the external configuration directory and use the wrapper:

```sh
cd /volume1/docker/personal-finance/app
export FINANCE_ENV_DIR=/volume1/docker/personal-finance/config
./scripts/finance.sh start
./scripts/finance.sh status
```

This creates the explicit Compose project `finance-main`. No source directory is mounted
into the container. Only the production data directory is mounted. If Container Manager is used
to inspect or manage the resulting container, keep the project name unchanged. Do not create a
second GUI project from `compose.yaml` without explicitly reproducing the same environment file,
project name, and both Compose files.

Values in the selected environment file take precedence over exported application settings in
the SSH session, including `FINANCE_HOST_PORT`. The wrapper preserves Docker connection settings.
An exported release does not need `.git`; the wrapper uses its own directory as the protected root.

## Network and Reverse Proxy

Browse directly to `http://NAS-LAN-IP:8000`, replacing `8000` with `FINANCE_HOST_PORT`. If the port conflicts, change only `FINANCE_HOST_PORT` and recreate the service.

For a DSM reverse proxy, create an HTTPS source hostname and send it to `http://127.0.0.1:<FINANCE_HOST_PORT>`. Use a valid certificate and restrict access to LAN/VPN clients. Do not interpret HTTPS or the reverse proxy as authentication.

## Health and Logs

The container initializes the schema, seeds the `Unknown` account, and then reports healthy when `/health` returns successfully:

```sh
FINANCE_ENV_DIR=/volume1/docker/personal-finance/config \
  ./scripts/finance.sh status
curl --fail http://127.0.0.1:8000/health
FINANCE_ENV_DIR=/volume1/docker/personal-finance/config \
  ./scripts/finance.sh logs
```

Container logs use the `json-file` driver with three 10 MB files. Avoid pasting import output or transaction details into support channels.

## Updates

Back up first, then retain the current image as a local rollback target and build the update:

```sh
cd /volume1/docker/personal-finance/app
export FINANCE_ENV_DIR=/volume1/docker/personal-finance/config
./scripts/finance.sh backup
docker image tag personal-finance:latest personal-finance:rollback-YYYYMMDD
./scripts/finance.sh start
./scripts/finance.sh status
```

Run the health check and inspect logs after every update. Database migrations run automatically at startup.

## Rollback

To run the retained image without rebuilding it, temporarily set `FINANCE_IMAGE_TAG` in the
external production environment file and run the fully explicit command below:

```sh
cd /volume1/docker/personal-finance/app
docker compose \
  --env-file /volume1/docker/personal-finance/config/main.env \
  --project-name finance-main \
  --project-directory /volume1/docker/personal-finance/app \
  -f /volume1/docker/personal-finance/app/compose.yaml \
  up -d --no-build app
FINANCE_ENV_DIR=/volume1/docker/personal-finance/config \
  ./scripts/finance.sh status
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
