"""Small text helpers: HTML to readable text, slugs, human-readable sizes."""

from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RUNS_RE = re.compile(r"[ \t]*\n[ \t]*\n[ \t]*\n+")
_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'",
}


def strip_html(text: str) -> str:
    """Best-effort HTML -> readable text: drop tags, collapse blank runs.

    Codabench pages are authored in markdown but served as HTML, so this is
    enough to make them readable in a terminal or a .md file.
    """
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    return _BLANK_RUNS_RE.sub("\n\n", text).strip()


def slug(text: str) -> str:
    """Lowercase, hyphenated, filesystem-safe version of ``text``."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "page"


def safe_name(text: str, fallback: str = "file") -> str:
    """Filesystem-safe filename that keeps the original casing and spaces."""
    name = re.sub(r"[^\w.\- ]+", "_", (text or "").strip()).strip()
    return name or fallback


def human_size(size: object) -> str:
    """Format a byte count as ``12.3 MB``; ``?`` when it is not a number."""
    try:
        value = float(size)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.1f} {unit}"
        value /= 1024
    return "?"


def truncate(text: str, limit: int) -> str:
    """One-line preview of ``text``, ellipsised at ``limit`` characters."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "..."
