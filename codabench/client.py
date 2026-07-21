"""The Codabench API client.

One object covers the whole surface these scripts need:

===============================  ==========================================
What you want                    Method
===============================  ==========================================
Browse competitions              :meth:`~CodabenchClient.list_competitions`,
                                 :meth:`~CodabenchClient.competition`
Download the "Files" tab         :meth:`~CodabenchClient.download_dataset`
Submit a zip                     :meth:`~CodabenchClient.submit`
Watch a submission               :meth:`~CodabenchClient.wait_for_submission`
Read scores + artifacts          :meth:`~CodabenchClient.results`
Download submission artifacts    :meth:`~CodabenchClient.download_artifact`
Create a competition             :meth:`~CodabenchClient.create_competition`
===============================  ==========================================

Authentication is lazy: nothing logs in until a call needs it, so reading a
public competition works with no credentials at all.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .auth import Credentials, open_session, token_headers
from .competitions import find_phase, parse_competition_id
from .downloads import read_scores, save_bytes
from .errors import ApiError, CodabenchError

#: Submission states that will not change again.
TERMINAL_STATES = {"Finished", "Failed", "Cancelled"}

#: Artifact name -> key in the ``get_details`` payload. These are the rows of
#: the submission download panel in the web UI.
ARTIFACTS = {
    "submission": "data_file",          # "Submission File"
    "prediction": "prediction_result",  # "Output from prediction step"
    "scoring": "scoring_result",        # "Output from scoring step"
    "detailed": "detailed_result",      # "Detailed results"
}


class CodabenchClient:
    """HTTP client for one Codabench instance.

    :param base_url: instance URL; defaults to ``CODABENCH_URL`` or codabench.org.
    :param username: defaults to ``CODABENCH_USERNAME``.
    :param password: defaults to ``CODABENCH_PASSWORD``.
    :param env_path: optional ``.env`` file to load before reading the above.
    """

    def __init__(self, base_url: "str | None" = None, username: "str | None" = None,
                 password: "str | None" = None, env_path: "str | None" = None,
                 timeout: int = 60) -> None:
        self.credentials = Credentials.from_env(base_url, username, password, env_path)
        self.base_url = self.credentials.base_url
        self.timeout = timeout
        self._headers: "dict | None" = None
        self._session: "requests.Session | None" = None

    # ---- plumbing ---------------------------------------------------------
    @property
    def headers(self) -> dict:
        """Token auth headers, fetched once on first use (``{}`` if anonymous)."""
        if self._headers is None:
            self._headers = token_headers(self.credentials)
        return self._headers

    @property
    def authenticated(self) -> bool:
        """True when the client holds an API token."""
        return bool(self.headers)

    def session(self) -> "requests.Session | None":
        """Cookie session for the Files-tab download route (None if unavailable).

        See :func:`codabench.auth.open_session` for why this exists next to the
        API token.
        """
        if self._session is None:
            self._session = open_session(self.credentials)
        return self._session

    def url(self, path: str) -> str:
        """Absolute URL for an API path."""
        return urljoin(self.base_url, path)

    def request(self, method: str, path: str, timeout: "int | None" = None,
                **kwargs) -> requests.Response:
        """Send a request, turning transport failures into :class:`ApiError`.

        Keeps callers (and the CLI) free of ``requests`` exception handling.
        """
        try:
            return requests.request(method, self.url(path), headers=self.headers,
                                    timeout=timeout or self.timeout, **kwargs)
        except requests.Timeout as exc:
            raise ApiError(f"{method} {path} timed out after "
                           f"{timeout or self.timeout}s — the server is slow or "
                           "unreachable; retry or raise --timeout.") from exc
        except requests.RequestException as exc:
            raise ApiError(f"{method} {path} failed: {exc}") from exc

    def get(self, path: str, timeout: "int | None" = None, **params) -> object:
        """GET a JSON endpoint. Raises :class:`ApiError` on a non-200 reply."""
        resp = self.request("GET", path, timeout=timeout, params=params or None)
        if resp.status_code != 200:
            raise ApiError(f"GET {path} failed ({resp.status_code}): {resp.text[:300]}",
                           resp.status_code, resp.text)
        return resp.json()

    def try_get(self, path: str, **params) -> object:
        """Like :meth:`get`, but returns None instead of raising.

        For endpoints that legitimately 403/404 depending on your role.
        """
        try:
            return self.get(path, **params)
        except ApiError:
            return None

    def post(self, path: str, data: "dict | None" = None, **params) -> object:
        """POST form data and return the JSON reply."""
        resp = self.request("POST", path, data=data, params=params or None)
        if resp.status_code not in (200, 201):
            raise ApiError(f"POST {path} failed ({resp.status_code}): {resp.text[:300]}",
                           resp.status_code, resp.text)
        return resp.json() if resp.content else {}

    # ---- competitions -----------------------------------------------------
    def list_competitions(self, search: "str | None" = None, timeout: int = 180) -> list:
        """Competitions visible to this account, ordered by id.

        The unfiltered listing is large and slow to build server-side, hence
        the generous default timeout; pass ``search`` to narrow it down.
        """
        data = self.get("/api/competitions/", timeout=timeout,
                        **({"search": search} if search else {}))
        items = data.get("results", data) if isinstance(data, dict) else data
        return sorted(items, key=lambda c: c.get("id", 0))

    def competition(self, link: "int | str") -> dict:
        """Full competition detail from a URL or an id.

        The payload carries phases, tasks, datasets, pages and leaderboards —
        the helpers in :mod:`codabench.competitions` read it without further
        requests.
        """
        return self.get(f"/api/competitions/{parse_competition_id(str(link))}/")

    def leaderboard(self, leaderboard_id: int) -> "dict | None":
        """Leaderboard with its submissions and scores (None if not visible)."""
        return self.try_get(f"/api/leaderboards/{leaderboard_id}/")

    def resolve_phase(self, link: "int | str", phase_id: "int | None" = None,
                      phase_index: "int | None" = None) -> dict:
        """Pick the phase to work with; see :func:`codabench.competitions.find_phase`."""
        return find_phase(self.competition(link), phase_id, phase_index)

    def download_dataset(self, key: str, dest_dir: "str | Path",
                         filename: "str | None" = None, extract: bool = True) -> "Path | None":
        """Download one dataset by key, the way the "Files" tab does.

        ``GET /datasets/download/<key>/`` redirects to signed storage. Returns
        the created path, or None when there is no session or Codabench denies
        access — reference data and unpublished programs are organizer-only,
        which is a normal outcome, not an error.
        """
        session = self.session()
        if session is None:
            return None
        resp = session.get(self.url(f"/datasets/download/{key}/"),
                           timeout=max(self.timeout, 300), allow_redirects=True)
        if resp.status_code != 200:
            return None
        return save_bytes(resp.content, dest_dir, filename or f"{key}.zip", extract)

    def download_url(self, url: str, dest_dir: "str | Path", filename: str,
                     extract: bool = True) -> Path:
        """Download an already-signed artifact URL.

        Signed storage URLs authorize through query parameters, so the API
        token is deliberately not sent to a foreign host.
        """
        same_host = urlparse(url).netloc == urlparse(self.base_url).netloc
        resp = requests.get(url, headers=self.headers if same_host else {},
                            timeout=max(self.timeout, 300))
        if resp.status_code != 200:
            raise ApiError(f"download failed ({resp.status_code}) for {filename}",
                           resp.status_code, resp.text)
        return save_bytes(resp.content, dest_dir, filename, extract)

    # ---- submissions ------------------------------------------------------
    def list_submissions(self, phase_id: "int | None" = None) -> list:
        """Your submissions (optionally on one phase), newest first."""
        data = self.get("/api/submissions/", **({"phase": phase_id} if phase_id else {}))
        items = data.get("results", data) if isinstance(data, dict) else data
        return sorted(items, key=lambda s: s.get("created_when", ""), reverse=True)

    def pick_submission(self, phase_id: int, last: int = 1) -> dict:
        """The ``last``-th most recent submission on a phase (1 = latest)."""
        submissions = self.list_submissions(phase_id)
        if not submissions:
            raise CodabenchError(f"no submissions on phase {phase_id} for this account.")
        if not 1 <= last <= len(submissions):
            raise CodabenchError(f"--last {last} is out of range: "
                                 f"only {len(submissions)} submission(s) on phase {phase_id}.")
        return submissions[last - 1]

    def submission(self, submission_id: int) -> dict:
        """One submission (status, scores, phase)."""
        return self.get(f"/api/submissions/{submission_id}/")

    def submission_details(self, submission_id: int) -> dict:
        """Submission detail: signed artifact URLs, logs, leaderboard columns."""
        return self.get(f"/api/submissions/{submission_id}/get_details/")

    def can_submit(self, phase_id: int) -> None:
        """Raise :class:`CodabenchError` if the phase will not accept a submission."""
        data = self.get(f"/api/can_make_submission/{phase_id}/")
        if not data.get("can", False):
            raise CodabenchError(f"cannot submit to phase {phase_id}: "
                                 f"{data.get('reason', 'unknown reason')}")

    def upload_dataset(self, path: "str | Path", dataset_type: str = "submission",
                       progress=print) -> str:
        """Upload a zip and return its dataset key.

        Two steps, as the web UI does them: create the dataset record to get a
        pre-signed ("sassy") URL, then PUT the bytes straight to storage.
        """
        self.credentials.require()
        path = Path(path)
        if not path.is_file():
            raise CodabenchError(f"file not found: {path}")
        size = path.stat().st_size

        dataset = self.post("/api/datasets/", {
            "type": dataset_type,
            "request_sassy_file_name": path.name,
            "file_size": size,
        })
        # Some deployments hand back a docker-internal host; normalise it.
        sassy_url = dataset["sassy_url"].replace("docker.for.mac.localhost", "localhost")

        if progress:
            progress(f"[..] uploading {path.name} ({size:,} bytes) ...")
        with open(path, "rb") as fh:
            put = requests.put(sassy_url, data=fh, headers={"Content-Type": "application/zip"},
                               timeout=max(self.timeout, 600))
        if put.status_code != 200:
            raise ApiError(f"upload failed ({put.status_code}): {put.text[:300]}",
                           put.status_code, put.text)
        return dataset["key"]

    def submit(self, phase_id: int, zip_path: "str | Path", tasks: "list | None" = None,
               progress=print) -> dict:
        """Upload ``zip_path`` and attach it to ``phase_id``. Returns the submission.

        This consumes submission quota — check :meth:`can_submit` first.
        """
        data_key = self.upload_dataset(zip_path, "submission", progress)
        return self.post("/api/submissions/", {
            "phase": phase_id,
            "tasks": tasks or [],
            "data": data_key,
        })

    def wait_for_submission(self, submission_id: int, interval: int = 15,
                            timeout: int = 1800, progress=print) -> dict:
        """Poll until the submission reaches a terminal state.

        Returns the submission even when it failed, so the caller can still
        fetch logs and outputs.
        """
        deadline = time.time() + timeout
        last_status = None
        while time.time() < deadline:
            submission = self.submission(submission_id)
            status = submission.get("status")
            if status != last_status:
                if progress:
                    progress(f"    status: {status}")
                last_status = status
            if status in TERMINAL_STATES:
                return submission
            time.sleep(interval)
        raise CodabenchError(f"timed out after {timeout}s waiting for submission {submission_id}")

    def results(self, submission_id: int, submission: "dict | None" = None) -> dict:
        """Named metric scores plus artifact URLs for a submission.

        Joins the numeric scores (keyed by ``column_key``) with the leaderboard
        column titles, so metrics come back human-readable. Falls back to
        parsing the scoring output archive when the API returns no inline scores.
        """
        submission = submission or self.submission(submission_id)
        details = self.try_get(f"/api/submissions/{submission_id}/get_details/") or {}

        titles = {}
        for board in details.get("leaderboards") or []:
            for column in board.get("columns", []):
                titles[column.get("key")] = column.get("title", column.get("key"))

        metrics, primary = {}, None
        for score in submission.get("scores") or []:
            name = titles.get(score.get("column_key"), score.get("column_key"))
            try:
                value = float(score.get("score"))
            except (TypeError, ValueError):
                value = score.get("score")
            metrics[name] = value
            if score.get("is_primary"):
                primary = {"metric": name, "score": value}

        if not metrics and details.get("scoring_result"):
            try:
                resp = requests.get(details["scoring_result"], timeout=self.timeout)
                if resp.status_code == 200:
                    metrics = read_scores(resp.content)
            except requests.RequestException:
                pass

        return {
            "submission_id": submission_id,
            "status": submission.get("status"),
            "phase": submission.get("phase"),
            "phase_name": submission.get("phase_name"),
            "created_when": submission.get("created_when"),
            "primary": primary,
            "metrics": metrics,
            "artifacts": {name: details.get(key) for name, key in ARTIFACTS.items()},
            "logs": {log.get("name"): log.get("data_file") for log in details.get("logs") or []},
        }

    def download_artifact(self, submission_id: int, artifact: str, dest_dir: "str | Path",
                          details: "dict | None" = None, extract: bool = True) -> "Path | None":
        """Download one submission artifact; see :data:`ARTIFACTS` for the names.

        Returns None when the submission has no such artifact (e.g. scoring
        never ran).
        """
        if artifact not in ARTIFACTS:
            raise CodabenchError(f"unknown artifact {artifact!r}; "
                                 f"choose from {', '.join(ARTIFACTS)}")
        details = details if details is not None else self.submission_details(submission_id)
        url = details.get(ARTIFACTS[artifact])
        if not url:
            return None
        return self.download_url(url, dest_dir, f"{artifact}.zip", extract)

    def rerun_submission(self, submission_id: int, task_key: str) -> dict:
        """Re-run an existing submission on another task (robot users only).

        The submission data is reused; only the task changes.
        """
        self.credentials.require()
        try:
            return self.post(f"/api/submissions/{submission_id}/re_run_submission/",
                             task_key=task_key)
        except ApiError as exc:
            raise ApiError(f"{exc}\nIs this account marked as a robot (is_bot) user?",
                           exc.status, exc.body) from exc

    def list_tasks(self) -> list:
        """Tasks visible to this account (their ``key`` feeds :meth:`rerun_submission`)."""
        data = self.get("/api/tasks/")
        return data.get("results", data) if isinstance(data, dict) else data

    # ---- organizer --------------------------------------------------------
    def create_competition(self, bundle_path: "str | Path", interval: int = 5,
                           timeout: int = 900, wait: bool = True,
                           progress=print) -> dict:
        """Create a competition from a bundle zip, as the upload page does.

        Uploads the bundle, tells the server it is complete (which starts
        unpacking) and — unless ``wait`` is False — polls until the new
        competition exists. Returns ``{"status_id", "competition_id"}``.
        """
        self.credentials.require()
        key = self.upload_dataset(bundle_path, "competition_bundle", progress)

        resp = requests.put(self.url(f"/api/datasets/completed/{key}/"),
                            headers=self.headers, timeout=self.timeout)
        if resp.status_code not in (200, 201):
            raise ApiError(f"failed to finalize upload ({resp.status_code}): {resp.text[:300]}",
                           resp.status_code, resp.text)
        status_id = resp.json().get("status_id")
        if status_id is None:
            raise CodabenchError(f"server did not start competition creation: {resp.text[:300]}")
        if progress:
            progress(f"[ok] unpacking started (status_id={status_id}).")
        if not wait:
            return {"status_id": status_id, "competition_id": None}

        deadline = time.time() + timeout
        last_status = None
        while time.time() < deadline:
            data = self.get(f"/api/competitions/{status_id}/creation_status/")
            status = data.get("status")
            if status != last_status:
                if progress:
                    progress(f"    status: {status}")
                last_status = status
            if status == "Finished":
                return {"status_id": status_id,
                        "competition_id": data.get("resulting_competition")}
            if status == "Failed":
                raise CodabenchError(f"competition creation failed: "
                                     f"{data.get('details', 'no details')}")
            time.sleep(interval)
        raise CodabenchError(f"timed out after {timeout}s waiting for competition creation.")


def default_env_path() -> str:
    """``.env`` next to the repository root, the conventional place for credentials."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
