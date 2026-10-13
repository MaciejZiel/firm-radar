# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Demo mode (`FIRM_RADAR_DEMO_MODE`): read-only, local lookups only, no scheduler, a
  per-client rate limit and a banner. `firm-radar seed-demo` loads a fictional dataset.
- Configurable database pool size (`FIRM_RADAR_DB_POOL_SIZE`, `FIRM_RADAR_DB_MAX_OVERFLOW`).
- `deploy/termux`: run script, environment template, nginx server block and notes for
  running the demo on a small home server without Docker.

## [0.1.0] - 2026-10-13

First release.

### Added

- Validation and detection of NIP, REGON and KRS identifiers.
- Clients for the KRS open API, the VAT taxpayer white list (with a daily request
  budget) and BZP contract award notices (keyset pagination), on an HTTP fetcher with
  bounded retries and a PostgreSQL-backed TTL cache.
- Company profiles merged from the registries, stored as change-tracked snapshots with
  field-level diffs (`added` / `removed` / `modified`).
- JSON API (search, profile, refresh, history, diff) with OpenAPI docs.
- Public procurement: BZP awards indexed by contractor NIP and shown in profiles.
- Background jobs for the KRS change bulletin, stale profile refresh and BZP ingest,
  guarded by an advisory lock, and a CLI for one-off jobs and lookups.
- Server-rendered web UI (Jinja2 and htmx) in Polish and English with search, profile,
  change timeline and data source health pages.
- Docker image, Docker Compose demo and CI (lint, type checks, migrations, tests).
