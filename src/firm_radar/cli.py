"""Command line entry point for one-off jobs (e.g. from a cron service).

firm-radar jobs            # one full cycle: KRS bulletin, stale refresh, BZP ingest, purge
firm-radar ingest-bzp --days 7
firm-radar ingest-bzp --day 2026-10-01 --force
firm-radar lookup 0000019193
firm-radar seed-demo      # fictional dataset for the read-only demo
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date

import aiohttp

from firm_radar.config import get_settings
from firm_radar.db import Database
from firm_radar.demo import seed
from firm_radar.identifiers import detect
from firm_radar.services.jobs import JobRunner
from firm_radar.services.procurement import ProcurementService
from firm_radar.services.profiles import ProfileService
from firm_radar.sources import Sources
from firm_radar.sources.store import PgSourceStore


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with aiohttp.ClientSession() as http:
            sources = Sources.build(http, settings, PgSourceStore(database.sessionmaker))
            profiles = ProfileService(database.sessionmaker, sources)
            procurement = ProcurementService(database.sessionmaker, sources.bzp)
            if args.command == "jobs":
                runner = JobRunner(settings, database.sessionmaker, sources, profiles, procurement)
                report = await runner.run_locked()
                print(report)
            elif args.command == "ingest-bzp":
                if args.day:
                    results = [await procurement.ingest_day(args.day, force=args.force)]
                else:
                    results = await procurement.ingest_recent(args.days)
                for r in results:
                    state = "skipped (already ingested)" if r.skipped else "ingested"
                    print(f"{r.day}: {r.notices} notices, {r.awards} awards - {state}")
            elif args.command == "seed-demo":
                loaded = await seed(database.sessionmaker, profiles, procurement)
                print("demo data loaded" if loaded else "database not empty, nothing changed")
            elif args.command == "lookup":
                result = await profiles.resolve(detect(args.identifier))
                print(json.dumps(result.snapshot.data, ensure_ascii=False, indent=2))
    finally:
        await database.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="firm-radar")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("jobs", help="run one cycle of background jobs")
    ingest = sub.add_parser("ingest-bzp", help="ingest BZP contract award notices")
    ingest.add_argument("--days", type=int, default=get_settings().bzp_ingest_days)
    ingest.add_argument("--day", type=date.fromisoformat)
    ingest.add_argument("--force", action="store_true", help="re-ingest an already ingested day")
    sub.add_parser("seed-demo", help="load the fictional demo dataset into an empty database")
    lookup = sub.add_parser("lookup", help="resolve an identifier and print the snapshot")
    lookup.add_argument("identifier")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
