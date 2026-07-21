"""Exceptions raised by the client.

The library raises; the CLI catches :class:`CodabenchError` at the top level and
turns it into a one-line ``error: ...`` message. Nothing here calls ``sys.exit``,
so the package stays usable from a notebook or another program.
"""

from __future__ import annotations


class CodabenchError(Exception):
    """Base class for every error this package raises."""


class AuthError(CodabenchError):
    """Credentials are missing, rejected, or insufficient for the request."""


class ApiError(CodabenchError):
    """The API returned an unexpected status code.

    ``status`` and ``body`` are kept so callers can branch on them (e.g. treat
    403/404 as "not authorized for this account" rather than a hard failure).
    """

    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body
