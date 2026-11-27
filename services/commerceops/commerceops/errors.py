"""Service errors. Routes and MCP tools map these; engines raise ValueError."""

from __future__ import annotations


class CommerceOpsError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "commerceops_error",
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class StoreNotFound(CommerceOpsError):
    def __init__(self, store_code: str) -> None:
        super().__init__(
            f"store not found: {store_code}",
            code="store_not_found",
            status_code=404,
            details={"store_code": store_code},
        )


class DraftNotFound(CommerceOpsError):
    def __init__(self, draft_id: str) -> None:
        super().__init__(
            f"draft not found: {draft_id}",
            code="draft_not_found",
            status_code=404,
            details={"draft_id": draft_id},
        )


class UnapprovedExecutionError(CommerceOpsError):
    def __init__(self, draft_id: str) -> None:
        super().__init__(
            "refusing to execute a draft without an approval record",
            code="unapproved_execution",
            status_code=409,
            details={"draft_id": draft_id},
        )


class ImportValidationError(CommerceOpsError):
    def __init__(self, errors: list[dict]) -> None:
        super().__init__(
            "import validation failed",
            code="import_invalid",
            status_code=422,
            details={"errors": errors},
        )
        self.errors = errors


class NoActionRequired(CommerceOpsError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message, code=code, status_code=409)
