"""HMAC identity passed from OpenDot to CommerceOps. The client cannot mint this."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import os
import time

from commerceops.errors import CommerceOpsError

SCOPE = "commerceops"
APPROVE_SCOPE = "commerceops.approve"
HEADER = "x-commerceops-identity"


@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str
    workspace_id: str
    can_approve: bool
    scope: str
    exp: int
    draft_id: str = ""


def signing_secret() -> bytes:
    raw = os.environ.get("COMMERCEOPS_SIGNING_SECRET", "").strip()
    if len(raw) < 16:
        raise CommerceOpsError(
            "CommerceOps signing secret is not configured",
            code="auth_not_configured",
            status_code=503,
        )
    return raw.encode("utf-8")


def _canonical(fields: dict) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(fields: dict, secret: bytes | None = None) -> str:
    payload = _canonical(fields)
    key = secret if secret is not None else signing_secret()
    digest = hmac.new(key, payload, sha256).hexdigest()
    return payload.decode("utf-8") + "." + digest


def _verify(token: str, *, expected_scope: str, secret: bytes | None = None, now: int | None = None) -> Identity:
    if not token or "." not in token:
        raise CommerceOpsError("missing authorization", code="unauthorized", status_code=401)
    payload, _, digest = token.rpartition(".")
    key = secret if secret is not None else signing_secret()
    expected = hmac.new(key, payload.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        raise CommerceOpsError("invalid authorization", code="unauthorized", status_code=401)
    try:
        fields = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CommerceOpsError("invalid authorization", code="unauthorized", status_code=401) from exc
    if fields.get("scope") != expected_scope or fields.get("v") != 1:
        raise CommerceOpsError("invalid authorization scope", code="unauthorized", status_code=401)
    exp = int(fields.get("exp") or 0)
    if exp < (now if now is not None else int(time.time())):
        raise CommerceOpsError("authorization expired", code="unauthorized", status_code=401)
    username = str(fields.get("username") or "").strip()
    user_id = str(fields.get("user_id") or "").strip()
    workspace_id = str(fields.get("workspace_id") or "").strip()
    if not username or not user_id or not workspace_id:
        raise CommerceOpsError("invalid authorization", code="unauthorized", status_code=401)
    return Identity(
        user_id=user_id,
        username=username,
        workspace_id=workspace_id,
        can_approve=bool(fields.get("can_approve")),
        scope=expected_scope,
        exp=exp,
        draft_id=str(fields.get("draft_id") or ""),
    )


def issue_identity(
    *,
    user_id: str,
    username: str,
    workspace_id: str,
    can_approve: bool,
    ttl_seconds: int = 60,
    secret: bytes | None = None,
    now: int | None = None,
) -> str:
    issued_at = now if now is not None else int(time.time())
    return _sign(
        {
            "v": 1,
            "scope": SCOPE,
            "user_id": user_id,
            "username": username,
            "workspace_id": workspace_id,
            "can_approve": can_approve,
            "exp": issued_at + ttl_seconds,
        },
        secret,
    )


def read_identity(token: str, *, secret: bytes | None = None, now: int | None = None) -> Identity:
    return _verify(token, expected_scope=SCOPE, secret=secret, now=now)


def issue_approval_grant(
    *,
    user_id: str,
    username: str,
    workspace_id: str,
    draft_id: str,
    ttl_seconds: int = 120,
    secret: bytes | None = None,
    now: int | None = None,
) -> str:
    issued_at = now if now is not None else int(time.time())
    return _sign(
        {
            "v": 1,
            "scope": APPROVE_SCOPE,
            "user_id": user_id,
            "username": username,
            "workspace_id": workspace_id,
            "can_approve": True,
            "draft_id": draft_id,
            "exp": issued_at + ttl_seconds,
        },
        secret,
    )


def read_approval_grant(
    token: str,
    *,
    draft_id: str,
    workspace_id: str,
    secret: bytes | None = None,
    now: int | None = None,
) -> Identity:
    identity = _verify(token, expected_scope=APPROVE_SCOPE, secret=secret, now=now)
    if not identity.can_approve or identity.draft_id != draft_id or identity.workspace_id != workspace_id:
        raise CommerceOpsError("approval is not authorized", code="approval_forbidden", status_code=403)
    return identity
