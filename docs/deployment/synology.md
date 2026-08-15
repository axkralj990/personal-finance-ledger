# Synology Deployment

This runbook installs the production application from a Git checkout on a Synology NAS. Docker
Compose builds one container containing the React frontend and FastAPI backend. SQLite, uploads,
backups, and model artifacts stay in a separate host directory mounted at `/data`.

## Security Boundary

The application has no authentication or authorization. Keep it on a trusted LAN or behind a VPN
such as Tailscale. Do not forward its port from the public internet. A Synology reverse proxy can
provide TLS and a friendly hostname, but it does not add application authentication by itself.

Membership in the host `docker` group grants root-equivalent control through the Docker daemon.
Grant it only to a trusted administrator or dedicated deployment account.

## Prerequisites

Install Container Manager and Git, enable SSH temporarily, and sign in with an account that can use
`sudo`. The NAS must use `linux/amd64` or `linux/arm64`; older ARMv7 models are not supported by the
base images.

Check whether the account can reach Docker without `sudo`:

```sh
docker ps
```

If that reports permission denied for `/var/run/docker.sock`, inspect the existing group first:

```sh
sudo synogroup --get docker
```

Create it only if DSM reports that it does not exist:

```sh
sudo synogroup --add docker
```

Then add the deployment account and assign the socket to the group:

```sh
sudo synogroup --memberadd docker "$USER"
sudo chgrp docker /var/run/docker.sock
sudo chmod g+rw /var/run/docker.sock
```

Do not rerun `--add` when the group already exists, and do not make the socket world-writable. Log
out of SSH completely and reconnect so the new membership reaches the shell. Confirm with:

```sh
id
docker ps
```

Plain `id` shows the groups active in the current shell. `id USERNAME` can show configured group
membership before the current shell has refreshed it.

DSM or Container Manager may recreate the socket during an update or restart. Verify `docker ps`
again after a NAS reboot. If the group ownership resets on a particular DSM release, use a root
boot-up task in DSM Task Scheduler to reapply `chgrp docker` and `chmod g+rw` after Container
Manager starts. Never work around a reset with `chmod 666`.

## Choose Host Paths

The checkout, configuration, and production data are independent. They may use any absolute paths
that suit the NAS. This guide uses:

```text
/volume1/docker/personal-finance-ledger       Git checkout
/volume1/docker/personal-finance-config       Host configuration
/volume1/docker/personal-finance-db           Production data
```

The checkout directory itself is the application directory. No additional directory named `app`
is required. The production database will be:

```text
/volume1/docker/personal-finance-db/finance.sqlite3
```

Inside the container, the same file is `/data/finance.sqlite3`. If `FINANCE_DATA_PATH` names
`/volume1/docker/personal-finance-db`, do not place the database in an extra `production`
subdirectory.

Create the external directories:

```sh
sudo mkdir -p /volume1/docker/personal-finance-ledger
sudo mkdir -p /volume1/docker/personal-finance-config
sudo mkdir -p /volume1/docker/personal-finance-db
sudo chown "$USER" /volume1/docker/personal-finance-ledger
sudo chown "$USER" /volume1/docker/personal-finance-config
sudo chown "$USER" /volume1/docker/personal-finance-db
sudo chmod 700 /volume1/docker/personal-finance-config
```

The data directory is assigned to the container account after any existing data has been copied.

## Check Out the Application

Clone the repository directly into the selected checkout path:

```sh
git clone --branch main https://github.com/axkralj990/LifeDashboard.git \
  /volume1/docker/personal-finance-ledger
cd /volume1/docker/personal-finance-ledger
```

The wrapper selects production or test configuration from the checked-out branch and deliberately
accepts only `main` or `test`. A source deployment therefore needs its `.git` directory and must
remain on `main` for production:

```sh
git branch --show-current
```

## Configure Production

The wrapper looks for `main.env` under `$HOME/.config/personal-finance-ledger` by default. A shared
Synology configuration path is usually clearer for administration and scheduled tasks:

```sh
cp environments/main.env.example /volume1/docker/personal-finance-config/main.env
chmod 600 /volume1/docker/personal-finance-config/main.env
```

Use an absolute data path and an unused, stable host port. Port `18473` is only an example:

```dotenv
FINANCE_DATA_PATH=/volume1/docker/personal-finance-db
FINANCE_HOST_PORT=18473
FINANCE_IMAGE_TAG=latest

TIMEZONE=Europe/Ljubljana
MAX_UPLOAD_BYTES=20971520
MAX_FILE_ROWS=20000
YAHOO_FINANCE_BASE_URL=https://query1.finance.yahoo.com
MARKET_DATA_TIMEOUT_SECONDS=10
QUOTE_PREVIEW_MAX_AGE_HOURS=24

ALLOWED_HOSTS=localhost,127.0.0.1,NAS-LAN-IP,NAS-TAILSCALE-IP,nas-name.example.ts.net
ALLOWED_ORIGINS=http://NAS-LAN-IP:18473,http://NAS-TAILSCALE-IP:18473,https://nas-name.example.ts.net

OPENAI_MAPPING_ENABLED=false
OPENAI_API_KEY=
OPENAI_MAPPING_MODEL=gpt-4.1-mini
OPENAI_MAPPING_CONNECT_TIMEOUT_SECONDS=5
OPENAI_MAPPING_READ_TIMEOUT_SECONDS=20
OPENAI_MAPPING_OVERALL_TIMEOUT_SECONDS=30
OPENAI_MAPPING_MAX_RETRIES=1
OPENAI_MAPPING_MAX_CONCURRENT=1
OPENAI_MAPPING_REQUESTS_PER_HOUR=10
```

Replace the example addresses with the destinations used in the browser. These settings protect
the optional OpenAI mapping requests; they are not application-wide host filtering or CORS:

- `ALLOWED_HOSTS` contains hostnames or IP addresses without schemes or ports.
- `ALLOWED_ORIGINS` contains complete browser origins, including the scheme and non-default port.
- A Tailscale IP or MagicDNS name is needed only when the browser opens the application through it.
- Ordinary frontend and API access is not restricted by these values.
- These settings are not a source-IP firewall or login system.
- Do not use a wildcard.

OpenAI import mapping is optional and disabled by default. If enabled, keep `OPENAI_API_KEY` only
in this permission-restricted file. Never place local settings or credentials in `compose.yaml`,
Git, screenshots, or logs.

`FINANCE_ENV_DIR` cannot be placed inside `main.env`: it tells the wrapper where to find that file.
Use it as a command prefix for a non-default configuration directory:

```sh
FINANCE_ENV_DIR=/volume1/docker/personal-finance-config \
  ./scripts/finance.sh status
```

If `main.env` is instead stored at the default
`$HOME/.config/personal-finance-ledger/main.env`, no prefix is required. Avoid running the wrapper
with `sudo` and a home-relative configuration because `$HOME` then becomes `/root`.

## Select a Host Port

Every container may listen on port `8000` internally because containers have isolated networks.
Only `FINANCE_HOST_PORT` must be unique on the NAS. Inspect current Docker mappings and all host
listeners before choosing it:

```sh
docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo ss -lntp
```

If DSM does not provide `ss`, use:

```sh
sudo netstat -lntp
```

Changing `FINANCE_HOST_PORT` from `8000` to `18473`, for example, creates the mapping
`18473 -> 8000`; it does not change the application port inside the container.

## Migrate Existing Data

Skip this section for a new empty ledger. For an existing installation, stop the source application
before copying SQLite so its WAL state is consistent. Copy the complete production data directory,
not only `finance.sqlite3`. It can contain:

```text
finance.sqlite3
finance.sqlite3-wal
finance.sqlite3-shm
uploads/
models/
backups/
```

With the default workstation configuration, the source directory is:

```text
$HOME/.local/share/personal-finance-ledger/production
```

Copy its contents directly into the configured Synology data directory. For example, run from the
source machine after stopping the application:

```sh
rsync -av "$HOME/.local/share/personal-finance-ledger/production/" \
  NAS_USER@NAS_HOST:/volume1/docker/personal-finance-db/
```

If the source cannot be stopped, create an online backup with `./scripts/finance.sh backup`, transfer
the resulting `backups/finance-<UTC_TIMESTAMP>.sqlite3` file into the NAS data directory's
`backups/` directory, and follow the [backup and restore guide](backup-restore.md). Copy `uploads/`
and `models/` separately from a stopped source or filesystem snapshot so those files remain
coordinated with the database. Keep the source copy until the migrated application and its
aggregates have been verified.

Whether the directory is empty or migrated, give the final data tree to the non-root account used
by the image:

```sh
sudo chown -R 10001:10001 /volume1/docker/personal-finance-db
sudo chmod 750 /volume1/docker/personal-finance-db
```

## Start Production

Run the wrapper as the Docker-enabled deployment account, not through `sudo`:

```sh
cd /volume1/docker/personal-finance-ledger
FINANCE_ENV_DIR=/volume1/docker/personal-finance-config \
  ./scripts/finance.sh start
FINANCE_ENV_DIR=/volume1/docker/personal-finance-config \
  ./scripts/finance.sh status
```

The first build downloads Node, Python, and uv images and can take several minutes on a NAS. Later
builds reuse Docker layers. `start` runs `docker compose up --detach --build`; a separate restart is
not needed.

This creates the Compose project `finance-main` and container `finance-main-app-1`. Only the host
data directory is mounted into the container; source code and the environment file are not mounted.
Do not create a second Container Manager project from the same Compose file with different settings.

Wait for startup, then check health using the selected host port:

```sh
curl --fail http://127.0.0.1:18473/health
```

Browse to `http://NAS-LAN-IP:18473` or the configured Tailscale/reverse-proxy origin.

## Startup After a NAS Restart

The Compose service uses `restart: unless-stopped`. Docker automatically starts the existing
container when Container Manager starts after a NAS reboot. Compose does not need to run at boot.

`./scripts/finance.sh stop` runs `docker compose down` and removes the container, so a container
stopped that way cannot restart until `start` is run again. A container manually stopped in DSM
also remains stopped under the `unless-stopped` policy.

## Health and Logs

The container applies database migrations, seeds the `Unknown` account when needed, and reports
healthy after `/health` succeeds:

```sh
FINANCE_ENV_DIR=/volume1/docker/personal-finance-config \
  ./scripts/finance.sh status
docker logs --tail 100 finance-main-app-1
```

For followed logs, use:

```sh
FINANCE_ENV_DIR=/volume1/docker/personal-finance-config \
  ./scripts/finance.sh logs
```

Container logs use the `json-file` driver with three 10 MB files. Avoid pasting transaction data or
import contents into support channels.

## Source Updates

Deploy only an up-to-date, clean `main` after its CI checks pass. Back up before pulling because
startup can run database migrations:

```sh
cd /volume1/docker/personal-finance-ledger
export FINANCE_ENV_DIR=/volume1/docker/personal-finance-config

test -z "$(git status --porcelain)" || { printf '%s\n' 'Refusing to update a dirty checkout' >&2; exit 1; }
./scripts/finance.sh backup
docker image tag personal-finance:latest personal-finance:rollback-YYYYMMDD
git pull --ff-only origin main
./scripts/finance.sh start
./scripts/finance.sh status
curl --fail http://127.0.0.1:18473/health
```

The guard stops the update when `git status --porcelain` produces any output. Docker rebuilds
changed layers and Compose recreates the container when the image changes. It does not replace the
external environment or data.

This sequence can run from DSM Task Scheduler under the deployment account, but automatic polling
of `main` can deploy a commit before its CI run finishes. Manual deployment after green CI is safer
unless the scheduled script also verifies the release or CI status. Always use absolute paths and
an explicit `FINANCE_ENV_DIR` in scheduled tasks because their `$HOME` may differ from an SSH login.

## Rollback

An image-only rollback is safe only when the release did not migrate the database and explicitly
remains compatible with the older application. Otherwise stop the service and restore the matching
pre-update database backup before starting the older image.

For an image-only rollback, set `FINANCE_IMAGE_TAG` to the rollback tag in `main.env`, then use an
explicit no-build Compose command:

```sh
cd /volume1/docker/personal-finance-ledger
docker compose \
  --env-file /volume1/docker/personal-finance-config/main.env \
  --project-name finance-main \
  --project-directory /volume1/docker/personal-finance-ledger \
  -f /volume1/docker/personal-finance-ledger/compose.yaml \
  up -d --no-build app
```

Do not wait for an older image to fail before restoring after a schema migration: it might start and
write data incorrectly. Use the [backup and restore guide](backup-restore.md) before starting it.

## Troubleshooting

### Docker socket permission denied

If Docker reports permission denied for `/var/run/docker.sock`, verify the current shell rather than
the account database alone:

```sh
id
ls -l /var/run/docker.sock
```

The active groups must include `docker`, and the socket should normally be `root:docker` with group
read/write permission. Log out and reconnect after changing membership. A Container Manager update
may require checking the socket group again.

### Environment file resolves under `/root`

The wrapper was run with `sudo`. Run it as the Docker-enabled deployment account, use the default
file under that account's home, or pass the external configuration directory explicitly.

### SQLite cannot open the database

`sqlite3.OperationalError: unable to open database file` means the mounted data directory is absent,
nested differently than `FINANCE_DATA_PATH`, or not writable by UID/GID `10001:10001`. Inspect the
actual mount and host permissions:

```sh
docker inspect finance-main-app-1 \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
ls -ld /volume1/docker/personal-finance-db
ls -la /volume1/docker/personal-finance-db
sudo synoacltool -get /volume1/docker/personal-finance-db
```

The configured host directory must mount directly to `/data`, and `finance.sqlite3` must be directly
inside it. The image user must own or be able to write the complete data tree.

### Container keeps restarting

`Restarting (1)` means the application process exited during startup. Do not rebuild repeatedly;
read the first application error:

```sh
docker logs --tail 100 finance-main-app-1
```

### Port already allocated

Choose another unused `FINANCE_HOST_PORT`, update every direct HTTP origin in `ALLOWED_ORIGINS`, and
run `start` again. `ALLOWED_HOSTS` contains the hostname or IP without the port.

## Reverse Proxy

For a DSM reverse proxy, create an HTTPS source hostname and send it to
`http://127.0.0.1:<FINANCE_HOST_PORT>`. If OpenAI mapping is enabled, add the source hostname to
`ALLOWED_HOSTS` and its complete HTTPS origin to `ALLOWED_ORIGINS`. Use a valid certificate and
restrict access to LAN or VPN clients. HTTPS is recommended for browser APIs and transport privacy,
but it is not application authentication.

## Architecture Notes

The Dockerfile uses official multi-architecture Node 24 and Python 3.12 Debian images. Native
Container Manager builds select the NAS architecture automatically. The service deliberately runs
one Uvicorn worker. SQLite uses WAL mode and persists database state, retained uploads, backups, and
model artifacts under `/data`. Multiple workers or replicas against this data directory are not
supported.
