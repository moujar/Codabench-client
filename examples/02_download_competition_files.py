#!/usr/bin/env python3
"""Download a competition's files — the starting kit, public data, programs.

Equivalent CLI: ``codabench files 16161``

Downloads go through ``/datasets/download/<key>/``, the same route the web
"Files" tab uses. That view authenticates by *session cookie*, not the API
token, which is why ``CodabenchClient`` keeps both (see ``codabench/auth.py``).

Files Codabench refuses are skipped: reference data is never served to
participants, and programs only when the organizer publishes them.

    python examples/02_download_competition_files.py 16161
"""

import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codabench import CodabenchClient, collect_files, default_env_path

COMPETITION = sys.argv[1] if len(sys.argv) > 1 else "16161"
OUT_DIR = f"files/{COMPETITION}"

client = CodabenchClient(env_path=default_env_path())
if client.session() is None:
    sys.exit("error: file downloads need a login — set CODABENCH_USERNAME / "
             "CODABENCH_PASSWORD in .env")

competition = client.competition(COMPETITION)
files = collect_files(competition)
print(f"{competition['title']}: {len(files)} file(s) listed\n")

for entry in files:
    # Returns None when this account may not download the file.
    path = client.download_dataset(entry.key, OUT_DIR, entry.filename)
    status = f"-> {path}" if path else "(not authorized for this account)"
    print(f"  {entry.type:<18} {entry.name:<40} {status}")
