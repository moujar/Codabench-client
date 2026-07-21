#!/usr/bin/env python3
"""Re-run an existing submission on another task (robot accounts).

Equivalent CLI: ``codabench rerun --submission 42 --task <uuid>``

Reuses the uploaded submission data and only changes the task, which is how
you run a pre-built algorithm against a private task that belongs to no
competition. Requires an account flagged as a robot (``is_bot``) — otherwise
the API answers 403.

    python examples/06_rerun_submission.py            # list submissions
    python examples/06_rerun_submission.py 42         # list task keys
    python examples/06_rerun_submission.py 42 <uuid>  # re-run
"""

import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codabench import CodabenchClient, default_env_path

client = CodabenchClient(env_path=default_env_path())
submission_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
task_key = sys.argv[2] if len(sys.argv) > 2 else None

if submission_id and task_key:
    result = client.rerun_submission(submission_id, task_key)
    print(f"[ok] new submission id={result.get('id')}")
elif submission_id:
    print("Task keys you can re-run on:")
    for task in client.list_tasks():
        print(f"  {task.get('key')}  {task.get('name')}")
else:
    print("Your submissions:")
    for sub in client.list_submissions()[:20]:
        print(f"  {sub.get('id'):>8}  {sub.get('owner')}")
