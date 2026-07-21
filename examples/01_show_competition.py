#!/usr/bin/env python3
"""Read a competition and save its description.

Equivalent CLI: ``codabench show 17363 --save-dir workdir/17363``

Shows that one payload — ``GET /api/competitions/{id}/`` — already contains the
pages, phases, tasks, datasets and leaderboard, so the helpers in
``codabench.competitions`` need no further requests.

    python examples/01_show_competition.py 17363
"""

import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codabench import CodabenchClient, collect_files, default_env_path, phases, primary_metric, save_description

COMPETITION = sys.argv[1] if len(sys.argv) > 1 else "17363"

# No credentials needed for a public competition; .env is used when present.
client = CodabenchClient(env_path=default_env_path())
competition = client.competition(COMPETITION)

print(f"{competition['title']}\n")
print(f"  organizer    : {competition.get('owner_display_name')}")
print(f"  participants : {competition.get('participants_count')}")

print("\nPhases (submit to these ids):")
for phase in phases(competition):
    print(f"  id={phase['id']:<6} {phase.get('status'):<9} {phase.get('name')}")

print("\nFiles listed on the competition:")
for entry in collect_files(competition):
    print(f"  {entry.type:<18} {entry.name}")

metric = primary_metric(competition)
if metric:
    direction = "higher" if metric["higher_is_better"] else "lower"
    print(f"\nRanked by: {metric['title']} ({direction} is better)")

# description.md + one markdown file per page
for path in save_description(competition, f"workdir/{competition['id']}"):
    print(f"[ok] wrote {path}")
