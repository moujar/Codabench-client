#!/usr/bin/env python3
"""Download the outputs of a submission you already made.

Equivalent CLI: ``codabench outputs 17525 --last 1``

These are the three links in the web UI's submission panel:

    Submission File               -> data_file
    Output from prediction step   -> prediction_result
    Output from scoring step      -> scoring_result

all exposed by ``GET /api/submissions/{id}/get_details/`` as signed URLs.

    python examples/04_download_submission_outputs.py 17525
"""

import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codabench import CodabenchClient, default_env_path, find_phase

COMPETITION = sys.argv[1] if len(sys.argv) > 1 else "17525"

client = CodabenchClient(env_path=default_env_path())
phase = find_phase(client.competition(COMPETITION))

submissions = client.list_submissions(phase["id"])
print(f"{len(submissions)} submission(s) on phase {phase['id']}:")
for sub in submissions[:5]:
    print(f"  {sub['id']:>8}  {sub.get('status'):<10} {str(sub.get('created_when'))[:19]}")

latest = client.pick_submission(phase["id"], last=1)   # last=2 -> the one before
print(f"\nusing submission {latest['id']} ({latest.get('status')})")

# Fetch details once, then reuse for every artifact.
details = client.submission_details(latest["id"])
for artifact in ("submission", "prediction", "scoring"):
    path = client.download_artifact(latest["id"], artifact,
                                    f"outputs/{latest['id']}", details=details)
    print(f"  {artifact:<11} -> {path or '(not available)'}")
