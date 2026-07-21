"""Writing downloaded bytes to disk.

Every Codabench artifact arrives as a zip (datasets, submissions, prediction
and scoring output), so the default is to extract; anything that is not a zip
is written as-is.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path


def save_bytes(content: bytes, dest_dir: "str | Path", filename: str,
               extract: bool = True) -> Path:
    """Write ``content`` into ``dest_dir`` and return what was created.

    When ``content`` is a zip and ``extract`` is set, it is unpacked into a
    directory named after ``filename`` (without the ``.zip`` suffix) and that
    directory is returned; otherwise the saved file path is returned.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if extract and zipfile.is_zipfile(io.BytesIO(content)):
        target = dest / filename[:-4] if filename.lower().endswith(".zip") else dest / filename
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            zf.extractall(target)
        return target
    path = dest / filename
    path.write_bytes(content)
    return path


def save_json(data: object, path: "str | Path") -> Path:
    """Write ``data`` as indented UTF-8 JSON, creating parent directories."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def read_scores(content: bytes) -> dict:
    """Best-effort ``metric -> value`` extraction from a scoring output zip.

    Reads any JSON/txt/YAML member: JSON objects are merged as-is, other files
    are scanned for ``key: value`` / ``key= value`` lines (the ``scores.txt``
    convention). Used as a fallback when the API returns no inline scores.
    """
    out: dict = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return out
    for name in zf.namelist():
        if not name.lower().endswith((".json", ".txt", ".yaml", ".yml")):
            continue
        raw = zf.read(name).decode("utf-8", errors="replace")
        if name.lower().endswith(".json"):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    out.update(data)
                continue
            except json.JSONDecodeError:
                pass  # fall through to line parsing
        for line in raw.splitlines():
            line = line.strip()
            for sep in (":", "="):
                if sep in line:
                    key, _, value = line.partition(sep)
                    key, value = key.strip(), value.strip()
                    if key:
                        try:
                            out[key] = float(value)
                        except ValueError:
                            out[key] = value
                    break
    return out
