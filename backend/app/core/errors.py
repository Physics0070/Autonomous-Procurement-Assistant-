"""Domain-level exceptions, translated into HTTP responses in main.py."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class ConfigurationError(AppError):
    """Raised when a required external dependency is not configured.

    Used to fail *gracefully and explicitly* (e.g. missing GEMINI_API_KEY)
    rather than crashing or silently producing fake results.
    """

    status_code = 503
    code = "not_configured"
