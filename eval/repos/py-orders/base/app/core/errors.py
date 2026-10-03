"""Domain errors raised by services.

Services and repositories raise these; ``app.main`` maps them to HTTP responses so the
business layer stays independent of FastAPI.
"""

from typing import Any


class DomainError(Exception):
    code = "domain_error"
    status_code = 400

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class InvalidRequestError(DomainError):
    code = "invalid_request"
    status_code = 422


class AuthenticationError(DomainError):
    code = "unauthenticated"
    status_code = 401


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    status_code = 403


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404


class ConflictError(DomainError):
    code = "conflict"
    status_code = 409


class UpstreamError(DomainError):
    code = "upstream_error"
    status_code = 502
