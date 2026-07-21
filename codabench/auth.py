"""Credentials and the two authentication schemes Codabench uses.

Codabench answers to two different mechanisms, and you need both:

* **Token auth** (``/api/api-token-auth/``) for everything under ``/api/``.
* **Session auth** (a Django form login at ``/accounts/login/``) for
  ``/datasets/download/<key>/`` — the route behind a competition's "Files"
  tab, which is a plain Django view and ignores the API token.

Both read the same credentials, so a caller never has to care which one a
given endpoint needs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urljoin

import requests

from .errors import AuthError

DEFAULT_URL = "https://www.codabench.org/"


def load_dotenv(path: str) -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into the environment.

    Supports optional quotes and ``#`` comments. Existing environment
    variables take precedence, so the real environment always wins over a file.
    """
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Credentials:
    """A Codabench account and the instance it belongs to.

    Accounts are per-instance: ``dev.codabench.org`` logins are separate from
    ``www.codabench.org`` ones.
    """

    username: "str | None" = None
    password: "str | None" = None
    base_url: str = DEFAULT_URL

    @classmethod
    def from_env(cls, base_url: "str | None" = None, username: "str | None" = None,
                 password: "str | None" = None, env_path: "str | None" = None) -> "Credentials":
        """Build from explicit values, falling back to ``.env`` / the environment.

        Reads ``CODABENCH_URL``, ``CODABENCH_USERNAME`` and ``CODABENCH_PASSWORD``.
        """
        if env_path:
            load_dotenv(env_path)
        return cls(
            username=username or os.environ.get("CODABENCH_USERNAME"),
            password=password or os.environ.get("CODABENCH_PASSWORD"),
            base_url=base_url or os.environ.get("CODABENCH_URL", DEFAULT_URL),
        )

    @property
    def complete(self) -> bool:
        """True when both a username and a password are available."""
        return bool(self.username and self.password)

    def require(self) -> None:
        """Raise :class:`AuthError` unless credentials are set."""
        if not self.complete:
            raise AuthError(
                "missing credentials: set CODABENCH_USERNAME and CODABENCH_PASSWORD "
                "in .env or the environment (or pass --username/--password)."
            )


def token_headers(credentials: Credentials, timeout: int = 30) -> dict:
    """Exchange credentials for ``{'Authorization': 'Token ...'}``.

    Returns empty headers when no credentials are configured: public
    competitions are readable anonymously, so that is a valid mode rather
    than an error. Wrong credentials, on the other hand, raise.
    """
    if not credentials.complete:
        return {}
    resp = requests.post(
        urljoin(credentials.base_url, "/api/api-token-auth/"),
        {"username": credentials.username, "password": credentials.password},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise AuthError(
            f"login failed ({resp.status_code}) for {credentials.base_url}. "
            "Check CODABENCH_USERNAME / CODABENCH_PASSWORD — note that accounts "
            "on dev.codabench.org and www.codabench.org are separate."
        )
    return {"Authorization": f"Token {resp.json()['token']}"}


def open_session(credentials: Credentials, timeout: int = 30) -> "requests.Session | None":
    """Log in like a browser and return the cookie-carrying session.

    Returns None when credentials are missing or the login form rejects them;
    callers treat that as "file downloads unavailable" rather than fatal,
    since the rest of the API still works with token auth.
    """
    if not credentials.complete:
        return None
    session = requests.Session()
    login_url = urljoin(credentials.base_url, "/accounts/login/")
    resp = session.get(login_url, timeout=timeout)
    csrf = session.cookies.get("csrftoken")
    if resp.status_code != 200 or not csrf:
        return None
    resp = session.post(
        login_url,
        data={"username": credentials.username, "password": credentials.password,
              "csrfmiddlewaretoken": csrf},
        headers={"Referer": login_url},
        timeout=timeout,
    )
    # A successful Django form login redirects away; landing back on the form is a failure.
    if resp.status_code != 200 or "/accounts/login" in resp.url:
        return None
    return session
