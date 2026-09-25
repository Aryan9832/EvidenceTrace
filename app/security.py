"""Operator authorization and bounded, per-process public request throttling."""
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from secrets import compare_digest

from fastapi import HTTPException, Request
from app.config import settings


class BodySizeLimit:
    def __init__(self, app, limit=4_000_000):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse
        payload = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            payload.extend(message.get("body", b""))
            if len(payload) > self.limit:
                return await JSONResponse({"detail":"Request body exceeds 4 MB"}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type":"http.request", "body":bytes(payload), "more_body":False}
            return await receive()
        return await self.app(scope, replay, send)


def require_operator(request: Request) -> None:
    if settings.local_mode and request.client and request.client.host in {"127.0.0.1", "::1"}:
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(403, "Local operator mode requires a loopback hostname")
        # Browsers must be same-origin; reject cross-site writes on local mode.
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            raise HTTPException(403, "Cross-origin operator request rejected")
        return
    key = settings.operator_key
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not key or not compare_digest(supplied.encode(), key.encode()):
        raise HTTPException(401, "Operator access required. Configure an operator key or use the loopback-only local preview.")


class RequestLimiter:
    """Single-process backstop. Use a gateway/shared limiter for multiple replicas."""
    def __init__(self, limit=30, window=60.0):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)
        self.lock = Lock()

    def allow(self, client: str) -> bool:
        now = monotonic()
        with self.lock:
            if client not in self.hits and len(self.hits) >= 2048:
                self.hits = defaultdict(deque, {k: v for k, v in self.hits.items() if v and now - v[-1] < self.window})
                if len(self.hits) >= 2048:
                    return False
            hits = self.hits[client]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True
