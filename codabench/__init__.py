"""A small, readable Python client for the `Codabench <https://www.codabench.org/>`_ API.

Typical use::

    from codabench import CodabenchClient

    client = CodabenchClient()                     # reads .env / environment
    competition = client.competition(17363)        # URL or id both work
    for f in collect_files(competition):
        client.download_dataset(f.key, "input/", f.filename)

Every command in the ``codabench`` CLI is a thin wrapper over these methods —
see ``examples/`` for the same flows written as standalone scripts.
"""

from __future__ import annotations

from .auth import Credentials, DEFAULT_URL, load_dotenv
from .client import ARTIFACTS, CodabenchClient, TERMINAL_STATES, default_env_path
from .competitions import (
    CompetitionFile,
    collect_files,
    description_markdown,
    find_phase,
    pages,
    parse_competition_id,
    phases,
    primary_metric,
    save_description,
)
from .errors import ApiError, AuthError, CodabenchError

__version__ = "0.1.1"

__all__ = [
    "ARTIFACTS",
    "ApiError",
    "AuthError",
    "CodabenchClient",
    "CodabenchError",
    "CompetitionFile",
    "Credentials",
    "DEFAULT_URL",
    "TERMINAL_STATES",
    "__version__",
    "collect_files",
    "default_env_path",
    "description_markdown",
    "find_phase",
    "load_dotenv",
    "pages",
    "parse_competition_id",
    "phases",
    "primary_metric",
    "save_description",
]
