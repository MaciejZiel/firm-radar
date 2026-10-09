"""Typed clients for the official registries used by firm-radar."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from firm_radar.config import Settings
from firm_radar.sources.base import HttpFetcher, SourceStore
from firm_radar.sources.bzp import BzpClient
from firm_radar.sources.krs import KrsClient
from firm_radar.sources.whitelist import WhiteListClient


@dataclass(frozen=True, slots=True)
class Sources:
    krs: KrsClient
    whitelist: WhiteListClient
    bzp: BzpClient
    store: SourceStore

    @classmethod
    def build(
        cls, session: aiohttp.ClientSession, settings: Settings, store: SourceStore
    ) -> Sources:
        fetcher = HttpFetcher(session, settings, store)
        return cls(
            krs=KrsClient(fetcher, settings),
            whitelist=WhiteListClient(fetcher, settings),
            bzp=BzpClient(fetcher, settings),
            store=store,
        )
