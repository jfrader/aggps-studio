# Deploy

AgGPS Studio is an authenticated, single-instance FastAPI service. Docker is the runtime source of truth.

## Requirements

- Docker Engine with Compose
- 2 GB RAM and 2 CPU cores recommended
- A persistent volume mounted at `/data/jobs`
- HTTPS termination in front of the app for any non-local deployment
- Optional outbound HTTPS to ESRI World Imagery; processing falls back to a paper map when unavailable

Do not run multiple containers or Uvicorn workers against the same jobs directory. The queue and active-worker state are process-local.

## Environment

| Variable | Default | Meaning |
|---|---:|---|
| `AGGPS_STUDIO_PASSWORD` | required | Shared login passphrase, at least 12 characters |
| `AGGPS_SESSION_SECRET` | password value | Separate random signing secret recommended |
| `COOKIE_SECURE` | `false` | Set `true` when the browser reaches the app over HTTPS |
| `HOST` | `127.0.0.1` | Bind address; Compose sets `0.0.0.0` |
| `PORT` | `8765` | HTTP port; platform-provided values are supported |
| `JOBS_DIR` | `_jobs` | Persistent state and terminal artifacts; Compose uses `/data/jobs` |
| `MAX_UPLOAD_MB` | `50` | Maximum uploaded ZIP size |
| `MAX_EXTRACTED_MB` | `300` | Maximum total uncompressed archive size |
| `MAX_ZIP_MEMBER_MB` | `100` | Maximum uncompressed size of one ZIP member |
| `MAX_ZIP_MEMBERS` | `1000` | Maximum archive member count |
| `MAX_CONCURRENT_JOBS` | `1` | Conversion worker count; keep at one unless memory is measured |
| `MAX_PENDING_JOBS` | `20` | Queued and processing job cap |
| `JOB_TTL_HOURS` | `24` | Terminal artifact retention |
| `JOB_CLEANUP_INTERVAL_SECONDS` | `900` | Expired-job cleanup interval |
| `SESSION_HOURS` | `12` | Login-session lifetime |
| `MPLCONFIGDIR` | `/tmp/mpl` | Writable Matplotlib cache |

Generate independent random values for `AGGPS_STUDIO_PASSWORD` and `AGGPS_SESSION_SECRET`. Do not commit `.env`.

## Docker Compose

```bash
cp .env.example .env
# Edit .env before starting the service.
docker compose up --build --detach
docker compose ps
curl --fail http://127.0.0.1:8765/healthz
```

Compose refuses to start without `AGGPS_STUDIO_PASSWORD`. Include the same environment or `.env` file when running later Compose commands.

The container runs as an unprivileged user with a read-only root filesystem. `/tmp` is tmpfs and the named `jobs` volume is the only persistent writable location.
Compose initializes that volume for UID/GID `10001:10001`. Configure the same ownership when attaching a host path or platform-managed disk; startup fails closed if `/data/jobs` is not writable.

## Reverse Proxy

Terminate TLS with Caddy, Traefik, nginx, or the hosting platform and set `COOKIE_SECURE=true`. Preserve the platform request-body limit at 52 MB or slightly above so the application can enforce its 50 MB ZIP limit. Add proxy-level rate limiting for `/auth/login` and `/jobs` on internet-facing deployments.

Only expose the web port. Never serve `/data/jobs` directly.

## Job Data

While a job runs, its uploaded ZIP and extracted tree live under `/data/jobs/<job-id>`. On success, the app keeps only the downloadable ZIP/PDF bundle, previews, and state. On failure it removes partial outputs. Terminal artifacts expire after `JOB_TTL_HOURS`; direct artifact URLs enforce the same expiry.

Jobs that were queued or processing during an abrupt restart are recovered from the persistent input ZIP. Completed artifacts survive normal container replacement until their TTL.

## Hosted Platforms

Fly.io, Railway, and Render can run the Dockerfile when configured as one instance with a persistent disk mounted at `/data/jobs`. Use the platform-provided `PORT`, allocate about 2 GB RAM, and enable HTTPS before setting `COOKIE_SECURE=true`.

Do not deploy to an ephemeral filesystem: a restart would lose pending jobs and downloads.

## Operations

```bash
docker compose logs --follow web
docker compose restart web
docker compose down
```

Use `docker compose down`, not `docker compose down --volumes`, during routine maintenance. Removing the volume deletes all pending jobs and retained artifacts.

Health endpoint: `GET /healthz`. It does not require authentication and returns only service status and version.

## Security Boundaries

- Farm coordinates and field names are private data.
- The shared-password model is for one trusted operator or team.
- The app validates ZIP paths, symlinks, encryption flags, member counts, expanded sizes, shapefile sidecars, geometry roles, and 2D shape types.
- Uploaded and extracted source data is deleted after each terminal job.
- This is not a multi-tenant authorization model; every authenticated operator can access every retained job URL.
