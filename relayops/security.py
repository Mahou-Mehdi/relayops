"""Local demonstration boundaries. Public persona headers are NOT authentication."""

from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

ROLES = {"operator", "reviewer", "observer"}


def role(request: Request, required: str | None = None) -> str:
    value = request.headers.get("X-RelayOps-Role", "observer")
    if value not in ROLES or (required and value != required):
        raise HTTPException(403, "This operation is not permitted for the selected local persona.")
    return value


class LocalBoundaryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)

        async def reject(detail, status):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)

        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
            return await reject("RelayOps v0.1 only serves localhost.", 403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-RelayOps-Request") != "1":
                return await reject("Missing local request header.", 403)
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed = urlsplit(origin)
                    actual = urlsplit(str(request.url))
                    expected_port = actual.port or (443 if actual.scheme == "https" else 80)
                    origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                    valid = parsed.scheme == actual.scheme and parsed.hostname == actual.hostname and origin_port == expected_port and not parsed.username and not parsed.password
                except ValueError:
                    valid = False
                if not valid:
                    return await reject("Cross-origin writes are disabled.", 403)
            content_length = request.headers.get("content-length")
            try:
                if content_length and not 0 <= int(content_length) <= 32_768:
                    return await reject("Request body is too large.", 413)
            except ValueError:
                return await reject("Invalid content length.", 400)
            # Count actual bytes too: Content-Length is optional for streamed requests.
            chunks = []
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > 32_768:
                    return await reject("Request body is too large.", 413)
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            original_receive = receive
            delivered = False

            async def buffered_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await original_receive()

            receive = buffered_receive

        async def secured_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"), (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")]
            await send(message)

        return await self.app(scope, receive, secured_send)
