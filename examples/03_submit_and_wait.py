#!/usr/bin/env python3
"""Submit a zip, wait for scoring, print the metrics, keep the outputs.

Equivalent CLI:
    codabench submit 17525 -z assets/sample_code_submission.zip --wait \\
        --download-dir outputs

The full flow the web UI performs:

    1. GET  /api/can_make_submission/{phase}/  quota / eligibility
    2. POST /api/datasets/                     create dataset, get upload URL
    3. PUT  <signed url>                       upload the zip
    4. POST /api/submissions/                  attach it to the phase
    5. GET  /api/submissions/{id}/             poll until terminal
    6. GET  .../get_details/                   scores + artifact URLs

WARNING: this consumes submission quota. Check the phase's daily limit first.

    python examples/03_submit_and_wait.py 17525 assets/sample_code_submission.zip
"""

import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codabench import CodabenchClient, default_env_path, find_phase

COMPETITION = sys.argv[1] if len(sys.argv) > 1 else "17525"
ZIP_PATH = sys.argv[2] if len(sys.argv) > 2 else "assets/sample_code_submission.zip"

client = CodabenchClient(env_path=default_env_path())

# Resolve which phase to submit to (the single or currently-open one).
phase = find_phase(client.competition(COMPETITION))
print(f"[ok] phase id={phase['id']} ({phase['name']!r})")

client.can_submit(phase["id"])          # raises CodabenchError when out of quota
submission = client.submit(phase["id"], ZIP_PATH)
submission_id = submission["id"]
print(f"[ok] submitted: id={submission_id}")

finished = client.wait_for_submission(submission_id, interval=15, timeout=1800)
results = client.results(submission_id, finished)

print(f"\nstatus: {results['status']}")
for name, value in results["metrics"].items():
    print(f"  {name}: {value}")

# Keep the prediction and scoring output for inspection / debugging.
for artifact in ("prediction", "scoring"):
    path = client.download_artifact(submission_id, artifact, f"outputs/{submission_id}")
    print(f"[ok] {artifact}: {path}")
