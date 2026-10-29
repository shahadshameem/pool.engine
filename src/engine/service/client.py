"""In-memory ASGI test client for executing HTTP calls directly against standard ASGI 3 apps."""

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional


Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class AsgiResponse:
    """Encapsulates an HTTP response returned by an ASGI application."""

    def __init__(self, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.text)


class AsgiTestClient:
    """Synchronous in-memory HTTP client testing ASGI applications without sockets."""

    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        json_data: Optional[Any] = None,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> AsgiResponse:
        """Executes a simulated HTTP request against the ASGI app."""
        return asyncio.run(
            self._async_request(
                method=method,
                path=path,
                json_data=json_data,
                data=data,
                headers=headers,
            )
        )

    async def _async_request(
        self,
        method: str,
        path: str,
        json_data: Optional[Any] = None,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> AsgiResponse:
        req_headers: dict[str, str] = {k.lower(): v for k, v in (headers or {}).items()}
        req_body: bytes = b""

        if json_data is not None:
            req_body = json.dumps(json_data).encode("utf-8")
            req_headers.setdefault("content-type", "application/json")
            req_headers.setdefault("content-length", str(len(req_body)))
        elif data is not None:
            req_body = data
            req_headers.setdefault("content-length", str(len(req_body)))

        raw_headers = [
            (k.encode("latin1"), v.encode("latin1")) for k, v in req_headers.items()
        ]

        query_string = b""
        req_path = path
        if "?" in path:
            req_path, qs = path.split("?", 1)
            query_string = qs.encode("latin1")

        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method.upper(),
            "path": req_path,
            "raw_path": req_path.encode("latin1"),
            "query_string": query_string,
            "headers": raw_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }

        body_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": req_body,
                    "more_body": False,
                }
            return {"type": "http.request", "body": b"", "more_body": False}

        resp_status = 500
        resp_headers: dict[str, str] = {}
        resp_chunks: list[bytes] = []

        async def send(message: dict[str, Any]) -> None:
            nonlocal resp_status, resp_headers
            msg_type = message.get("type")
            if msg_type == "http.response.start":
                resp_status = message.get("status", 500)
                for raw_k, raw_v in message.get("headers", []):
                    resp_headers[raw_k.decode("latin1").lower()] = raw_v.decode("latin1")
            elif msg_type == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    resp_chunks.append(chunk)

        await self.app(scope, receive, send)
        return AsgiResponse(
            status_code=resp_status,
            headers=resp_headers,
            body=b"".join(resp_chunks),
        )

    def get(self, path: str, headers: Optional[dict[str, str]] = None) -> AsgiResponse:
        return self.request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        json: Optional[Any] = None,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> AsgiResponse:
        return self.request("POST", path, json_data=json, data=data, headers=headers)

    def patch(
        self,
        path: str,
        json: Optional[Any] = None,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> AsgiResponse:
        return self.request("PATCH", path, json_data=json, data=data, headers=headers)

    def delete(self, path: str, headers: Optional[dict[str, str]] = None) -> AsgiResponse:
        return self.request("DELETE", path, headers=headers)

    def options(self, path: str, headers: Optional[dict[str, str]] = None) -> AsgiResponse:
        return self.request("OPTIONS", path, headers=headers)
