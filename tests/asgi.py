"""Tiny in-process ASGI client, so API tests need no extra HTTP test dependency."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

from starlette.types import ASGIApp, Message


@dataclass
class Response:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def text(self) -> str:
        return self.body.decode()

    def json(self) -> Any:
        return json.loads(self.body)


class AsgiClient:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> Response:
        parts = urlsplit(url)
        query = parts.query
        if params:
            query = "&".join(p for p in (query, urlencode(params)) if p)
        body = urlencode(data).encode() if data is not None else b""
        raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        if cookies:
            cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())
            raw_headers.append((b"cookie", cookie.encode()))
        if data is not None:
            raw_headers.append((b"content-type", b"application/x-www-form-urlencoded"))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": parts.path,
            "raw_path": parts.path.encode(),
            "query_string": query.encode(),
            "headers": [(b"host", b"testserver"), *raw_headers],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
        sent = False
        response = Response(status_code=0)

        async def receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response.status_code = message["status"]
                for key, value in message.get("headers", []):
                    name = key.decode().lower()
                    previous = response.headers.get(name)
                    response.headers[name] = (
                        f"{previous}, {value.decode()}" if previous else value.decode()
                    )
            elif message["type"] == "http.response.body":
                response.body += message.get("body", b"")

        await self.app(scope, receive, send)
        return response

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self.request("POST", url, **kwargs)
