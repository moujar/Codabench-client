#!/usr/bin/env python3
"""Create a competition from a bundle zip (organizers).

Equivalent CLI: ``codabench create -b assets/bundle.zip``

Mirrors the web "Upload competition" page:

    1. POST /api/datasets/                  create a competition_bundle dataset
    2. PUT  <signed url>                    upload the bundle
    3. PUT  /api/datasets/completed/<key>/  finalise; starts unpacking
    4. GET  /api/competitions/{status_id}/creation_status/   poll

Tip: try this against https://dev.codabench.org/ first. Accounts there are
separate from www.codabench.org, so set CODABENCH_URL and matching credentials.

    python examples/05_create_competition.py assets/bundle.zip
"""

import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codabench import CodabenchClient, default_env_path

BUNDLE = sys.argv[1] if len(sys.argv) > 1 else "assets/bundle.zip"

client = CodabenchClient(env_path=default_env_path())
print(f"[..] creating a competition on {client.base_url}")

result = client.create_competition(BUNDLE, interval=5, timeout=900)
competition_id = result["competition_id"]

print(f"[ok] competition id={competition_id}")
print(f"     {client.url(f'/competitions/{competition_id}/')}")
