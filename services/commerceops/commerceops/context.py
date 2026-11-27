"""Trusted workspace for the current call. Callers set it from a signed identity or MCP env."""

from __future__ import annotations

from contextvars import ContextVar, Token

from commerceops.errors import CommerceOpsError

_WORKSPACE: ContextVar[str | None] = ContextVar("commerceops_workspace", default=None)

DEMO_WORKSPACE = "ws-demo"
LEGACY_WORKSPACE = "ws-legacy"


def bind_workspace(workspace_id: str) -> Token[str | None]:
    cleaned = workspace_id.strip()
    if not cleaned:
        raise CommerceOpsError("workspace is required", code="workspace_required", status_code=401)
    return _WORKSPACE.set(cleaned)


def reset_workspace(token: Token[str | None]) -> None:
    _WORKSPACE.reset(token)


def current_workspace() -> str:
    value = _WORKSPACE.get()
    if not value:
        raise CommerceOpsError("workspace is required", code="workspace_required", status_code=401)
    return value
