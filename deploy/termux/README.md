# Running the demo on the home server (Termux, aarch64)

This directory contains everything needed to serve firm-radar as a small public demo
behind nginx and a Cloudflare tunnel. It was written for Termux on Android (aarch64) with
Python 3.14, PostgreSQL 18 and no Docker.

## What demo mode does

Set with `FIRM_RADAR_DEMO_MODE=true`:

- **Fictional data only.** `firm-radar seed-demo` loads one company that does not exist
  (the same fictional fixtures the tests use) with two snapshots, six detected changes
  and a BZP award, so the profile, the timeline and the procurement block all have
  content. The seed refuses to run on a database that already has companies.
- **No registry calls.** Searches for a KRS, NIP or REGON number are answered from the
  local database only; an unknown number returns an empty result with a short note. The
  white list quota (100 queries a day) is never touched.
- **No background jobs.** The scheduler is not started even if it is enabled in the
  environment.
- **Read-only.** Any request other than GET, HEAD or OPTIONS gets `403`. The refresh
  button is hidden and a banner says the data is fictional.
- **Rate limit.** At most `FIRM_RADAR_DEMO_RATE_LIMIT_PER_MINUTE` requests per client
  address per minute (default 60, `0` disables it); over the limit the answer is `429`
  with `Retry-After`. `/healthz` and `/static/` are not counted. The counters live in
  the process, so a restart resets them.

## Files

| File | Purpose |
|---|---|
| `run-demo.sh` | `setup`, `start`, `stop`, `status`, `run` (foreground, for a supervisor) |
| `firm-radar.env.example` | Environment template. No secrets. Copy to `firm-radar.env` |
| `nginx-firm-radar.conf` | nginx server block (listens on 127.0.0.1:8080) |
| `requirements.txt` | Pinned runtime dependencies exported from `uv.lock` |

`requirements.txt` leaves out `uvloop`, `httptools`, `watchfiles` and `websockets` (the
`uvicorn[standard]` extras). The demo runs uvicorn with the plain asyncio loop and h11, so
there are fewer native extensions to build on the device. The application is run from the
source tree (`PYTHONPATH=src`), so the project itself is never built or installed.

## One-time setup

1. Packages (names are Termux package names; the list is what the native wheels need when
   no prebuilt one exists for Android):

   ```bash
   pkg install python postgresql nginx clang rust make binutils libffi openssl git
   ```

2. PostgreSQL role and database. On Termux the PostgreSQL superuser is your own user, so
   no password is involved when the server uses `trust` for the loopback interface (the
   `initdb` default). Skip this step if the shared instance already has them.

   ```bash
   createuser firm_radar
   createdb -O firm_radar firm_radar
   ```

   If the instance uses password authentication, put the password into
   `firm-radar.env` (the file is git-ignored) and keep it out of the repository.

3. Clone, configure, install, migrate and seed:

   ```bash
   git clone https://github.com/MaciejZiel/firm-radar.git && cd firm-radar
   cp deploy/termux/firm-radar.env.example deploy/termux/firm-radar.env
   deploy/termux/run-demo.sh setup
   ```

   `setup` creates `.venv-demo`, installs `requirements.txt`, runs `alembic upgrade head`
   and `firm-radar seed-demo`. Compiling `pydantic-core` (Rust) and `asyncpg` takes a few
   minutes on first install.

4. nginx: copy `nginx-firm-radar.conf` next to your other server blocks, change
   `server_name` to the tunnel hostname and reload nginx. Point the Cloudflare tunnel
   hostname at `http://127.0.0.1:8080`.

## Running

```bash
deploy/termux/run-demo.sh start     # background, log in deploy/termux/run/firm-radar.log
deploy/termux/run-demo.sh status    # pid and resident memory
deploy/termux/run-demo.sh stop
curl -s http://127.0.0.1:8093/healthz
```

The app listens on `127.0.0.1:8093` (`HOST` and `PORT` in the env file). It trusts
`X-Forwarded-For` only from `127.0.0.1`; the nginx block sets that header from
`CF-Connecting-IP`, which is what makes the per-client rate limit work behind the tunnel.
Use `run-demo.sh run` as the command of a service supervisor if you have one (for example
`termux-services`).

## Memory footprint

Measured on a Linux x86-64 development machine with Python 3.14.4, one uvicorn worker (asyncio
loop, h11), a pool of 2 database connections and PostgreSQL 18 in a container. The server
has a different CPU and libc (bionic), so treat the numbers as a close estimate, and
re-measure there with `run-demo.sh status` (it prints `VmRSS` and the peak `VmHWM`).

| Situation | App process RSS |
|---|---|
| Idle, right after start | 120 MB |
| After opening every page and the API docs once | 126 MB |
| After 1500 page requests at 16 concurrent connections (rate limit off) | 158 MB (peak 189 MB) |

PostgreSQL adds one backend process per pooled connection: 17 to 18 MB RSS each in this
test, most of it shared pages. With `FIRM_RADAR_DB_POOL_SIZE=2` and
`FIRM_RADAR_DB_MAX_OVERFLOW=2` that is at most four backends. The database itself is
tiny (about 8 MB with the demo data); it uses the shared PostgreSQL instance of the
server, so no extra postmaster is started. Plan for roughly 150 to 200 MB for the app
plus the backends.

Ways to lower it if needed: `--limit-concurrency` in `run-demo.sh` (32 now) bounds the
number of simultaneous requests, and the rate limit bounds a single client.

## Not covered

- A first request to `/docs` builds the OpenAPI schema once (the whole page tour in the table above cost about 6 MB); disable it in
  nginx if you do not want to expose it.
- The demo does not show live registry data. Run the Docker Compose setup from the main
  README for that.
