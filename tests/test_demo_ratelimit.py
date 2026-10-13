"""Demo rate limiter: client keying and bounded memory. No database needed."""

from __future__ import annotations

import ipaddress

import pytest
from starlette.types import Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from firm_radar.demo import DemoGuard, client_key


async def _ok(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _get(app: object, client: str, headers: list[tuple[bytes, bytes]] | None = None) -> int:
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": headers or [],
        "client": (client, 5000),
        "scheme": "http",
    }
    status = 0

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    await app(scope, receive, send)  # type: ignore[operator]
    return status


def test_client_key_ipv4_unchanged() -> None:
    assert client_key("203.0.113.7") == "203.0.113.7"
    assert client_key("unknown") == "unknown"


def test_client_key_ipv6_collapses_to_64() -> None:
    a = client_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd")
    b = client_key("2001:db8:1:2::1")
    assert a == b == "2001:db8:1:2::/64"
    assert client_key("2001:db8:1:3::1") != a


def test_client_key_ipv4_mapped_ipv6_is_ipv4() -> None:
    assert client_key("::ffff:203.0.113.7") == "203.0.113.7"


async def test_ipv6_rotation_inside_a_64_shares_one_budget() -> None:
    guard = DemoGuard(_ok, limit_per_minute=3)
    base = int(ipaddress.IPv6Address("2001:db8:5:5::"))
    codes = [await _get(guard, str(ipaddress.IPv6Address(base + i + 1))) for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


async def test_ipv4_clients_have_separate_budgets() -> None:
    guard = DemoGuard(_ok, limit_per_minute=1)
    assert await _get(guard, "203.0.113.1") == 200
    assert await _get(guard, "203.0.113.1") == 429
    assert await _get(guard, "203.0.113.2") == 200


async def test_many_distinct_addresses_are_never_blocked_and_memory_is_bounded() -> None:
    guard = DemoGuard(_ok, limit_per_minute=3)
    for i in range(20_000):
        ip = f"10.{i >> 16 & 255}.{i >> 8 & 255}.{i & 255}"
        assert await _get(guard, ip) == 200
        assert len(guard._hits) <= DemoGuard.MAX_CLIENTS
    assert len(guard._hits) == DemoGuard.MAX_CLIENTS


async def test_least_recently_seen_client_is_evicted_first() -> None:
    guard = DemoGuard(_ok, limit_per_minute=1)
    guard.MAX_CLIENTS = 2
    assert await _get(guard, "198.51.100.1") == 200
    assert await _get(guard, "198.51.100.2") == 200
    assert await _get(guard, "198.51.100.1") == 429  # refreshes .1
    assert await _get(guard, "198.51.100.3") == 200  # evicts .2
    assert await _get(guard, "198.51.100.1") == 429
    assert await _get(guard, "198.51.100.2") == 200  # forgotten, starts fresh


def _proxied() -> ProxyHeadersMiddleware:
    # Same wiring as `uvicorn --proxy-headers --forwarded-allow-ips 127.0.0.1`.
    return ProxyHeadersMiddleware(DemoGuard(_ok, limit_per_minute=1), trusted_hosts="127.0.0.1")


def _xff(value: str) -> list[tuple[bytes, bytes]]:
    return [(b"x-forwarded-for", value.encode())]


async def test_keys_on_forwarded_address_from_the_local_proxy() -> None:
    app = _proxied()
    assert await _get(app, "127.0.0.1", _xff("203.0.113.1")) == 200
    assert await _get(app, "127.0.0.1", _xff("203.0.113.1")) == 429
    assert await _get(app, "127.0.0.1", _xff("203.0.113.2")) == 200
    assert await _get(app, "127.0.0.1", _xff("2001:db8:9:9::1")) == 200
    assert await _get(app, "127.0.0.1", _xff("2001:db8:9:9::2")) == 429


async def test_missing_forwarded_header_falls_back_to_one_shared_bucket() -> None:
    # nginx drops X-Forwarded-For when CF-Connecting-IP is absent: all such requests share
    # the proxy's own address, so the limit still holds and nothing can be spoofed.
    app = _proxied()
    assert await _get(app, "127.0.0.1") == 200
    assert await _get(app, "127.0.0.1") == 429


async def test_forwarded_header_from_an_untrusted_peer_is_ignored() -> None:
    app = _proxied()
    assert await _get(app, "198.51.100.9", _xff("203.0.113.1")) == 200
    assert await _get(app, "198.51.100.9", _xff("203.0.113.2")) == 429


@pytest.mark.parametrize("raw", ["", "not-an-ip"])
def test_client_key_tolerates_garbage(raw: str) -> None:
    assert client_key(raw) == raw
