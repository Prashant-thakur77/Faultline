"""MCP over Streamable HTTP at /mcp for judges and Claude Desktop/Code.

* Bearer keys map to ONE tenant each (FAULTLINE_MCP_KEYS="<key>:<tenant>,…"; secrets live in .env only). Keys are
  compared in constant time; the tenant comes from the key, never from a tool argument.
* 30 calls/min/key (sliding window; per client IP for requests without a key) → HTTP 429 before the request
  reaches the MCP session.
* The same read-only tool set as stdio; every read is GRAPH.RO_QUERY through the tenant's ACL user.

    PYTHONPATH=backend python -m faultline.mcp_server.http --host 127.0.0.1 --port 8401
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import time
from collections import OrderedDict

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from .. import __version__
from ..config import settings
from ..graph.tenant import check_tenant
from .server import INSTRUCTIONS, register_tools


def parse_keys(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, _, tenant = part.rpartition(":")
        if len(key) < 24:
            raise ValueError("MCP bearer keys must be at least 24 characters")
        out[key] = check_tenant(tenant)
    return out


def key_id(key: str) -> str:
    return "key-" + hashlib.sha256(key.encode()).hexdigest()[:8]


class StaticKeyVerifier:
    """TokenVerifier: constant-time comparison against every configured key (no early exit on a match)."""

    def __init__(self, keys: dict[str, str]):
        self.keys = keys

    async def verify_token(self, token: str) -> AccessToken | None:
        hit = None
        for k, tenant in self.keys.items():
            if hmac.compare_digest(k.encode(), (token or "").encode()):
                hit = (k, tenant)
        if hit is None:
            return None
        return AccessToken(token=token, client_id=key_id(hit[0]), scopes=["graph:read"], claims={"tenant": hit[1]})


class RateLimit:
    """ASGI wrapper: N requests/min per bearer key, and N per client IP for requests without a bearer key (so a flood
    of unauthenticated requests is cut off before the MCP app, not just answered 401 at full speed). The window dict
    is bounded: idle keys are pruned, and past MAX_KEYS the least recently seen are dropped."""

    MAX_KEYS = 10_000

    def __init__(self, app, per_min: int):
        self.app, self.per_min = app, per_min
        self.hits: OrderedDict[str, list[float]] = OrderedDict()  # request times per key / IP (process-local, LRU)

    def _key(self, scope) -> str:
        auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode(errors="ignore")
        if auth.lower().startswith("bearer ") and auth[7:].strip():
            return key_id(auth[7:].strip())
        client = scope.get("client") or ("-", 0)
        return f"ip:{client[0]}"

    def allow(self, key: str, now: float) -> bool:
        q = [t for t in self.hits.pop(key, []) if now - t <= 60]
        ok = len(q) < self.per_min
        if ok:
            q.append(now)
        self.hits[key] = q  # most recently seen last
        if len(self.hits) > self.MAX_KEYS:
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                self.hits.pop(k, None)
            while len(self.hits) > self.MAX_KEYS:
                self.hits.popitem(last=False)
        return ok

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not self.allow(self._key(scope), time.monotonic()):
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", b"60")]})
            await send({"type": "http.response.body",
                        "body": b'{"error":"rate limited: %d requests/min per key (or per IP without one)"}' % self.per_min})
            return
        await self.app(scope, receive, send)


def transport_security(public_url: str):
    """DNS-rebinding protection that admits the public host Caddy forwards (Host: <domain>) plus loopback. The SDK's
    default only admits localhost, so behind a reverse proxy every request got 421."""
    from urllib.parse import urlparse

    from mcp.server.transport_security import TransportSecuritySettings

    u = urlparse(public_url)
    netloc = u.netloc
    host = u.hostname or ""
    hosts = sorted({netloc, host, "127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"} - {""})
    origins = sorted({f"{u.scheme}://{netloc}", "http://127.0.0.1:*", "http://localhost:*"})
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def build_http_app(keys: dict[str, str] | None = None, public_url: str = "http://127.0.0.1:8401",
                   per_min: int | None = None):
    from mcp.server.mcpserver import MCPServer

    keys = parse_keys(settings.faultline_mcp_keys) if keys is None else keys
    if not keys:
        raise RuntimeError("no MCP bearer keys configured (FAULTLINE_MCP_KEYS); refusing to serve unauthenticated")
    server = MCPServer(name="faultline", title="Faultline graph tools (read-only)", instructions=INSTRUCTIONS,
                       version=__version__, token_verifier=StaticKeyVerifier(keys),
                       auth=AuthSettings(issuer_url=public_url, resource_server_url=f"{public_url}/mcp",
                                         required_scopes=["graph:read"]))
    register_tools(server, public=True)
    app = server.streamable_http_app(stateless_http=True, json_response=True,
                                     transport_security=transport_security(public_url))
    return RateLimit(app, per_min or settings.faultline_mcp_rate_per_min), server


def main() -> int:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8401)
    ap.add_argument("--public-url", default=None)
    # behind the deploy's Caddy (the only thing that reaches this port there) the client IP is in X-Forwarded-For;
    # trust it only from the given proxies (default loopback), or every unauthenticated client shares one IP bucket
    ap.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    a = ap.parse_args()
    app, _ = build_http_app(public_url=a.public_url or f"http://{a.host}:{a.port}")
    uvicorn.run(app, host=a.host, port=a.port, proxy_headers=True, forwarded_allow_ips=a.forwarded_allow_ips)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
