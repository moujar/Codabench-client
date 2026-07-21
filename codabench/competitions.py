"""Pure helpers that read a competition payload.

Everything here works on the JSON returned by ``GET /api/competitions/{id}/``
— no network — so it is easy to test and to reuse in your own tooling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import CodabenchError
from .text import safe_name, slug, strip_html


def parse_competition_id(link: str) -> int:
    """Extract the numeric id from a competition URL or a bare id string.

    >>> parse_competition_id("https://www.codabench.org/competitions/17363/")
    17363
    >>> parse_competition_id("17363")
    17363
    """
    link = (link or "").strip()
    if link.isdigit():
        return int(link)
    match = re.search(r"/competitions/(\d+)", link)
    if match:
        return int(match.group(1))
    raise CodabenchError(f"could not find a competition id in {link!r}")


@dataclass
class CompetitionFile:
    """One row of a competition's "Files" tab.

    ``key`` is the dataset UUID used by
    :meth:`codabench.client.CodabenchClient.download_dataset`.
    """

    key: str
    name: str
    type: str
    phase: str = ""
    task: str = ""
    size: "float | None" = None

    @property
    def filename(self) -> str:
        """Filesystem-safe ``.zip`` name to save this file under."""
        name = safe_name(self.name, fallback=self.key)
        return name if name.lower().endswith(".zip") else name + ".zip"

    @property
    def location(self) -> str:
        """``phase / task`` label, for display."""
        return self.phase + (f" / {self.task}" if self.task else "")


def phases(competition: dict) -> list:
    """Phases ordered by their index."""
    return sorted(competition.get("phases") or [], key=lambda p: p.get("index", 0))


def find_phase(competition: dict, phase_id: "int | None" = None,
               phase_index: "int | None" = None) -> dict:
    """Pick a phase: by id, by index, else the only/currently-open one.

    Raises :class:`CodabenchError` listing the candidates when the choice is
    ambiguous, so the caller can tell the user what to pass.
    """
    available = phases(competition)
    if not available:
        raise CodabenchError(f"competition {competition.get('id')} has no phases.")
    if phase_id is not None:
        for phase in available:
            if phase.get("id") == phase_id:
                return phase
        raise CodabenchError(f"no phase with id {phase_id} in this competition.")
    if phase_index is not None:
        for phase in available:
            if phase.get("index") == phase_index:
                return phase
        raise CodabenchError(f"no phase with index {phase_index} in this competition.")
    if len(available) == 1:
        return available[0]
    open_phases = [p for p in available
                   if str(p.get("status", "")).lower() in ("current", "active", "open")]
    if len(open_phases) == 1:
        return open_phases[0]
    listing = "\n".join(f"  index={p.get('index')}  id={p.get('id')}  "
                        f"status={p.get('status')!r}  name={p.get('name')!r}"
                        for p in available)
    raise CodabenchError("several phases are open; choose one with --phase:\n" + listing)


def collect_files(competition: dict) -> list:
    """Every file the competition's "Files" tab lists, as :class:`CompetitionFile`.

    Mirrors the web UI: phase-level ``public_data`` / ``starting_kit`` plus
    per-task ``public_datasets`` (input & reference data, ingestion & scoring
    programs) and ``solutions``. Whether you may actually *download* each one
    depends on your role and the organizer's settings.
    """
    files, seen = [], set()

    def add(key, name, ftype, phase, task="", size=None):
        if key and key not in seen:
            seen.add(key)
            files.append(CompetitionFile(key=key, name=name or ftype, type=ftype,
                                         phase=phase, task=task, size=size))

    for phase in phases(competition):
        phase_name = phase.get("name", "")
        for attr in ("public_data", "starting_kit"):
            dataset = phase.get(attr)
            if dataset:
                add(dataset.get("key"), dataset.get("name"), attr, phase_name,
                    size=dataset.get("file_size"))
        for task in phase.get("tasks", []):
            task_name = task.get("name", "")
            for dataset in task.get("public_datasets") or []:
                add(dataset.get("key"), dataset.get("name"), dataset.get("type", "dataset"),
                    phase_name, task_name, dataset.get("file_size"))
            for solution in task.get("solutions") or []:
                # a solution keeps its dataset key in `data`
                add(solution.get("data"), solution.get("name"), "solution",
                    phase_name, task_name, solution.get("size"))
    return files


def pages(competition: dict) -> list:
    """Prose pages (Overview, Data, Evaluation, ...) ordered by index."""
    return sorted(competition.get("pages") or [], key=lambda p: p.get("index", 0))


def description_markdown(competition: dict) -> str:
    """The whole competition description as one markdown document."""
    parts = [f"# {competition.get('title', '?')}", ""]
    for page in pages(competition):
        title = page.get("title") or ""
        body = strip_html(page.get("content") or page.get("data") or "")
        if title:
            parts.append(f"## {title}")
        if body:
            parts += [body, ""]
    if len(parts) <= 2 and competition.get("description"):
        parts.append(strip_html(competition["description"]))
    return "\n".join(parts).strip() + "\n"


def save_description(competition: dict, dest_dir: "str | Path") -> list:
    """Write ``description.md`` and ``pages/NN-title.md``; return written paths.

    Page bodies are kept as authored (markdown) rather than stripped, so the
    files stay faithful to what the organizer wrote.
    """
    dest = Path(dest_dir)
    pages_dir = dest / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for i, page in enumerate(pages(competition)):
        title = page.get("title") or f"page-{i}"
        body = page.get("content") or page.get("data") or ""
        try:
            index = int(page.get("index", i))
        except (TypeError, ValueError):
            index = i
        path = pages_dir / f"{index:02d}-{slug(title)}.md"
        header = "" if body.lstrip().startswith("#") else f"# {title}\n\n"
        path.write_text(header + body, encoding="utf-8")
        written.append(path)

    description = dest / "description.md"
    description.write_text(description_markdown(competition), encoding="utf-8")
    written.append(description)
    return written


def primary_metric(competition: dict) -> dict:
    """The leaderboard's primary column: ``{leaderboard, key, title, higher_is_better}``.

    Empty dict when the competition exposes no leaderboard.
    """
    leaderboards = competition.get("leaderboards") or []
    if not leaderboards:
        return {}
    board = leaderboards[0]
    columns = board.get("columns") or []
    index = board.get("primary_index") or 0
    column = columns[index] if index < len(columns) else (columns[0] if columns else {})
    return {
        "leaderboard_id": board.get("id"),
        "leaderboard": board.get("title"),
        "key": column.get("key"),
        "title": column.get("title"),
        "higher_is_better": column.get("sorting") == "desc",
    }
