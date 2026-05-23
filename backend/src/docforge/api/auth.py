from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from docforge.config import Settings
from docforge.errors import UnauthorizedError

LOOPBACK = frozenset({"127.0.0.1", "::1"})


@dataclass(frozen=True)
class Principal:
    name: str


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def require_writer(request: Request) -> Principal:
    """Guards every route that changes state or spends money.

    With ``API_TOKENS`` configured, a known bearer token is required and names the principal (the
    reviewer recorded on review decisions). Without tokens, only loopback callers may write: the
    local Next.js proxy works out of the box, while anything reachable over a network does not.
    """
    tokens = _settings(request).api_tokens
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if tokens:
        if scheme.lower() == "bearer" and presented:
            for token, name in tokens.items():
                if hmac.compare_digest(token.encode(), presented.encode()):
                    return Principal(name)
        raise UnauthorizedError("a valid bearer token is required")
    if request.client is not None and request.client.host in LOOPBACK:
        return Principal("local")
    raise UnauthorizedError("writes from other hosts require API_TOKENS to be configured")


WriterDep = Annotated[Principal, Depends(require_writer)]
