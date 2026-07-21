"""The ``codabench`` command line.

Each subcommand is a thin wrapper over :class:`codabench.client.CodabenchClient`;
this module owns argument parsing and terminal output, nothing else.

    codabench competitions                     list competitions
    codabench show 17363                       one competition, in full
    codabench files 16161                      list/download the Files tab
    codabench submit 17525 -z run.zip --wait   submit and watch
    codabench outputs 17525                    fetch a submission's outputs
    codabench rerun --submission 42            re-run on another task (bots)
    codabench create -b bundle.zip             create a competition
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .client import ARTIFACTS, CodabenchClient, default_env_path
from .competitions import (
    collect_files,
    find_phase,
    pages,
    parse_competition_id,
    phases,
    primary_metric,
    save_description,
)
from .downloads import save_json
from .errors import CodabenchError
from .text import human_size, strip_html, truncate


# ---- output helpers ---------------------------------------------------------
def _rule(title: str = "", width: int = 74) -> None:
    print(f"\n{title}" if title else "")
    print("-" * width)


def _client(args: argparse.Namespace) -> CodabenchClient:
    return CodabenchClient(base_url=args.url, username=args.username,
                           password=args.password, env_path=args.env)


# ---- commands ---------------------------------------------------------------
def cmd_competitions(args: argparse.Namespace) -> None:
    """List the competitions visible to this account."""
    competitions = _client(args).list_competitions(args.search)
    _rule("Competitions")
    print(f"{'id':>7}  {'organizer':<22}  title")
    for comp in competitions:
        organizer = str(comp.get("created_by", ""))[:22]
        print(f"{comp.get('id', ''):>7}  {organizer:<22}  {comp.get('title', '')}")
    print(f"\n{len(competitions)} competition(s). Details: codabench show <id>\n")


def cmd_show(args: argparse.Namespace) -> None:
    """Show one competition: pages, phases, files, leaderboard."""
    client = _client(args)
    comp = client.competition(args.competition)

    if args.json:
        print(json.dumps(comp, indent=2, ensure_ascii=False))
        return

    print(f"\n{'=' * 74}\n{comp.get('title', '?')}\n{'=' * 74}")
    print(f"  id           : {comp.get('id')}")
    print(f"  organizer    : {comp.get('owner_display_name') or comp.get('created_by')}")
    print(f"  created      : {str(comp.get('created_when', ''))[:10]}")
    print(f"  participants : {comp.get('participants_count')}")
    print(f"  submissions  : {comp.get('submissions_count')}")
    print(f"  docker image : {comp.get('docker_image')}")
    print(f"  published    : input_data={comp.get('make_input_data_available')} "
          f"programs={comp.get('make_programs_available')}")

    competition_pages = pages(comp)
    if competition_pages:
        _rule(f"Pages ({len(competition_pages)})")
        for page in competition_pages:
            body = strip_html(page.get("content") or "")
            if args.pages:
                print(f"\n## {page.get('title', '?')}\n\n{body}")
            else:
                print(f"  {page.get('index', '?'):>2}. {str(page.get('title', '?')):<24} "
                      f"{truncate(body, 90)}")

    competition_phases = phases(comp)
    _rule(f"Phases ({len(competition_phases)})")
    for phase in competition_phases:
        print(f"\n  phase id={phase.get('id')}  index={phase.get('index')}  "
              f"status={phase.get('status')!r}  name={phase.get('name')!r}")
        print(f"    window : {str(phase.get('start', ''))[:10]} -> "
              f"{str(phase.get('end', ''))[:10]}")
        print(f"    quota  : {phase.get('max_submissions_per_day')}/day, "
              f"{phase.get('max_submissions_per_person')} total "
              f"(used: {phase.get('used_submissions_per_person', '?')})")
        for task in phase.get("tasks", []):
            print(f"    task id={task.get('id')}  {task.get('name')!r}")

    files = collect_files(comp)
    _rule(f"Files ({len(files)})")
    for entry in files or []:
        print(f"  {entry.type:<18} {human_size(entry.size):>10}  {entry.name}")
    if not files:
        print("  (none listed)")

    metric = primary_metric(comp)
    if metric:
        _rule(f"Leaderboard: {metric['leaderboard']}")
        print(f"  primary metric : {metric['title']} ({metric['key']}), "
              f"{'higher' if metric['higher_is_better'] else 'lower'} is better")
        board = client.leaderboard(metric["leaderboard_id"]) or {}
        submissions = board.get("submissions") or []
        print(f"  entries        : {len(submissions)}")
        scores = []
        for submission in submissions:
            for score in submission.get("scores", []):
                if score.get("is_primary") or score.get("column_key") == metric["key"]:
                    try:
                        scores.append((float(score["score"]), submission.get("owner")))
                    except (TypeError, ValueError, KeyError):
                        pass
                    break
        if scores:
            best = max(scores) if metric["higher_is_better"] else min(scores)
            print(f"  current best   : {best[0]:.5f} by {best[1]}")

    if args.save_dir:
        print()
        for path in save_description(comp, args.save_dir):
            print(f"[ok] {path}")
        if not args.no_download:
            _download_files(client, files, Path(args.save_dir) / "input", extract=True)
    print()


def _download_files(client: CodabenchClient, files: list, out_dir: "str | Path",
                    extract: bool) -> int:
    """Download every file the account is allowed to fetch. Returns the count.

    Files Codabench denies (reference data, unpublished programs) are skipped
    silently — that is the platform's policy, not a failure of this tool.
    """
    if not files:
        return 0
    if client.session() is None:
        print("[!!] cannot download files: no login. Set CODABENCH_USERNAME / "
              "CODABENCH_PASSWORD to fetch the starting kit and public data.")
        return 0
    saved = 0
    for entry in files:
        path = client.download_dataset(entry.key, out_dir, entry.filename, extract)
        if path is not None:
            saved += 1
            print(f"[ok] {entry.type:<18} -> {path}")
    if not saved:
        print("[!!] no files were downloadable for this account.")
    return saved


def cmd_files(args: argparse.Namespace) -> None:
    """List or download a competition's files."""
    client = _client(args)
    comp = client.competition(args.competition)
    files = collect_files(comp)
    if not files:
        raise CodabenchError(f"competition {comp.get('id')} lists no files.")

    if args.only:
        patterns = [p.lower() for p in args.only]
        files = [f for f in files
                 if any(p in f.type.lower() or p in f.name.lower() for p in patterns)]
        if not files:
            raise CodabenchError(f"no files match --only {args.only}.")

    _rule(f"Files — {comp.get('title', '?')}")
    print(f"{'type':<18} {'size':>10}  {'phase / task':<26}  name")
    for entry in files:
        print(f"{entry.type:<18} {human_size(entry.size):>10}  "
              f"{entry.location[:26]:<26}  {entry.name}")
    print()
    if args.list:
        return

    out_dir = Path(args.out_dir) / str(comp.get("id"))
    saved = _download_files(client, files, out_dir, extract=not args.no_extract)
    print(f"\n[ok] {saved}/{len(files)} file(s) -> {out_dir}/\n")


def cmd_submit(args: argparse.Namespace) -> None:
    """Upload a zip to a phase, optionally waiting for the score."""
    client = _client(args)
    if args.phase:
        phase_id = args.phase
    else:
        phase = find_phase(client.competition(args.competition), phase_index=args.phase_index)
        phase_id = phase["id"]
        print(f"[ok] phase id={phase_id} ({phase.get('name')!r})")

    client.can_submit(phase_id)
    print(f"[ok] phase {phase_id} accepts a submission.")
    submission = client.submit(phase_id, args.zip, args.tasks)
    submission_id = submission.get("id")
    print(f"[ok] submission created: id={submission_id} status={submission.get('status')}")

    if not (args.wait or args.results_json or args.download_dir):
        return

    print(f"[..] polling every {args.interval}s (timeout {args.timeout}s) ...")
    finished = client.wait_for_submission(submission_id, args.interval, args.timeout)
    results = client.results(submission_id, finished)
    _print_results(results)
    if args.results_json:
        print(f"[ok] results -> {save_json(results, args.results_json)}")
    if args.download_dir:
        _download_artifacts(client, submission_id, Path(args.download_dir) / str(submission_id),
                            list(ARTIFACTS), extract=not args.no_extract)


def _print_results(results: dict) -> None:
    _rule(f"Results — submission {results['submission_id']} ({results['status']})")
    if results.get("primary"):
        print(f"  primary: {results['primary']['metric']} = {results['primary']['score']}")
    for name, value in (results.get("metrics") or {}).items():
        print(f"  {name}: {value}")
    if not results.get("metrics"):
        print("  (no metrics returned)")
    print()


def _download_artifacts(client: CodabenchClient, submission_id: int, out_dir: Path,
                        wanted: list, extract: bool) -> None:
    """Download the chosen artifacts of one submission into ``out_dir``."""
    details = client.submission_details(submission_id)
    for artifact in wanted:
        path = client.download_artifact(submission_id, artifact, out_dir, details, extract)
        if path is None:
            print(f"[!!] no {artifact} artifact on submission {submission_id}.")
        else:
            print(f"[ok] {artifact:<11} -> {path}")
    print(f"[ok] details -> {save_json(details, out_dir / 'details.json')}")


def cmd_outputs(args: argparse.Namespace) -> None:
    """Download a submission's files: submission zip, prediction & scoring output."""
    client = _client(args)
    submission_id = args.submission
    if submission_id is None:
        phase_id = args.phase or find_phase(client.competition(args.competition))["id"]
        submissions = client.list_submissions(phase_id)
        if not submissions:
            raise CodabenchError(f"no submissions on phase {phase_id} for this account.")
        _rule(f"Submissions on phase {phase_id}")
        print(f"{'id':>8}  {'status':<10}  {'created (UTC)':<20}  filename")
        for sub in submissions:
            print(f"{sub.get('id', ''):>8}  {str(sub.get('status', '')):<10}  "
                  f"{str(sub.get('created_when', ''))[:19]:<20}  {sub.get('filename', '')}")
        print()
        if args.list:
            return
        picked = client.pick_submission(phase_id, args.last)
        submission_id = picked["id"]
        label = "latest" if args.last == 1 else f"#{args.last} most recent"
        print(f"[ok] using {label} submission id={submission_id} "
              f"(status={picked.get('status')}).")

    out_dir = Path(args.out_dir) / str(submission_id)
    _download_artifacts(client, submission_id, out_dir, args.only, extract=not args.no_extract)
    print()


def cmd_rerun(args: argparse.Namespace) -> None:
    """Re-run an existing submission on another task (robot accounts)."""
    client = _client(args)
    if args.submission and args.task:
        result = client.rerun_submission(args.submission, args.task)
        print(f"[ok] re-ran submission {args.submission} on task {args.task} "
              f"-> new submission {result.get('id')}")
        return
    if args.submission:
        tasks = client.list_tasks()
        _rule("Tasks")
        print(f"{'key':<38}  name")
        for task in tasks:
            print(f"{task.get('key', ''):<38}  {str(task.get('name', ''))[:32]}")
        print(f"\nRe-run with: codabench rerun --submission {args.submission} --task <key>\n")
        return
    submissions = client.list_submissions()
    _rule("Submissions")
    print(f"{'id':>8}  {'owner':<20}  task")
    for sub in submissions:
        task = sub.get("task")
        print(f"{sub.get('id', ''):>8}  {str(sub.get('owner', '')):<20}  "
              f"{task.get('id') if isinstance(task, dict) else task}")
    print("\nPick one: codabench rerun --submission <id>\n")


def cmd_create(args: argparse.Namespace) -> None:
    """Create a competition from a bundle zip."""
    client = _client(args)
    print(f"[..] target: {client.base_url}")
    result = client.create_competition(args.bundle, args.interval, args.timeout,
                                       wait=not args.no_wait)
    if result["competition_id"]:
        print(f"[ok] competition created: id={result['competition_id']}")
        print(f"     {client.url('/competitions/' + str(result['competition_id']) + '/')}")
    else:
        print(f"[ok] not waiting. Poll: GET "
              f"{client.url('/api/competitions/' + str(result['status_id']) + '/creation_status/')}")


# ---- argument parsing -------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codabench",
        description="Talk to the Codabench API: browse competitions, download "
                    "files, submit, and fetch results.",
    )
    parser.add_argument("--version", action="version", version=f"codabench {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", help="Codabench base URL (or set CODABENCH_URL).")
    common.add_argument("--username", help="Username (or set CODABENCH_USERNAME).")
    common.add_argument("--password", help="Password (or set CODABENCH_PASSWORD).")
    common.add_argument("--env", default=default_env_path(),
                        help="Path to the .env file holding your credentials.")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("competitions", parents=[common], help="List competitions.")
    p.add_argument("--search", help="Filter by title/keyword (the full listing is slow).")
    p.set_defaults(func=cmd_competitions)

    p = sub.add_parser("show", parents=[common],
                       help="Show one competition: pages, phases, files, leaderboard.")
    p.add_argument("competition", help="Competition URL or id.")
    p.add_argument("--pages", action="store_true", help="Print every page in full.")
    p.add_argument("--save-dir", help="Write description.md, pages/*.md and input/ here.")
    p.add_argument("--no-download", action="store_true",
                   help="With --save-dir: save the text only, skip file downloads.")
    p.add_argument("--json", action="store_true", help="Print the raw API payload.")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("files", parents=[common],
                       help="List or download a competition's files.")
    p.add_argument("competition", help="Competition URL or id.")
    p.add_argument("--list", action="store_true", help="List only, do not download.")
    p.add_argument("--only", nargs="+", metavar="PATTERN",
                   help="Only files whose type or name contains one of these.")
    p.add_argument("-o", "--out-dir", default="files",
                   help="Download into <out-dir>/<competition id>/.")
    p.add_argument("--no-extract", action="store_true", help="Keep archives zipped.")
    p.set_defaults(func=cmd_files)

    p = sub.add_parser("submit", parents=[common], help="Submit a zip to a phase.")
    p.add_argument("competition", nargs="?", help="Competition URL or id (resolves the phase).")
    p.add_argument("-z", "--zip", required=True, help="Submission .zip to upload.")
    p.add_argument("-p", "--phase", type=int, help="Phase id (skips competition lookup).")
    p.add_argument("--phase-index", type=int, help="With a competition: pick the phase by index.")
    p.add_argument("-t", "--tasks", type=int, nargs="*", default=[],
                   help="Task ids to target (default: all tasks on the phase).")
    p.add_argument("--wait", action="store_true", help="Poll until the submission is scored.")
    p.add_argument("--interval", type=int, default=15, help="Seconds between polls.")
    p.add_argument("--timeout", type=int, default=1800, help="Max seconds to wait.")
    p.add_argument("--results-json", help="Write the structured results here (implies --wait).")
    p.add_argument("--download-dir",
                   help="Download the outputs here when finished (implies --wait).")
    p.add_argument("--no-extract", action="store_true", help="Keep archives zipped.")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("outputs", parents=[common],
                       help="Download a submission's prediction/scoring output.")
    p.add_argument("competition", nargs="?", help="Competition URL or id (uses its phase).")
    p.add_argument("-s", "--submission", type=int, help="Submission id.")
    p.add_argument("-p", "--phase", type=int, help="Phase id.")
    p.add_argument("-l", "--last", type=int, default=1, metavar="N",
                   help="Pick the Nth most recent submission (1 = latest).")
    p.add_argument("--list", action="store_true", help="List your submissions and exit.")
    p.add_argument("--only", nargs="+", default=["submission", "prediction", "scoring"],
                   choices=list(ARTIFACTS), help="Which artifacts to download.")
    p.add_argument("-o", "--out-dir", default="outputs",
                   help="Download into <out-dir>/<submission id>/.")
    p.add_argument("--no-extract", action="store_true", help="Keep archives zipped.")
    p.set_defaults(func=cmd_outputs)

    p = sub.add_parser("rerun", parents=[common],
                       help="Re-run a submission on another task (robot accounts).")
    p.add_argument("-s", "--submission", type=int, help="Submission id to re-run.")
    p.add_argument("-t", "--task", help="Task key (UUID) to run it on.")
    p.set_defaults(func=cmd_rerun)

    p = sub.add_parser("create", parents=[common],
                       help="Create a competition from a bundle zip.")
    p.add_argument("-b", "--bundle", required=True, help="Competition bundle .zip.")
    p.add_argument("--interval", type=int, default=5, help="Seconds between status polls.")
    p.add_argument("--timeout", type=int, default=900, help="Max seconds to wait for unpacking.")
    p.add_argument("--no-wait", action="store_true", help="Start creation and exit.")
    p.set_defaults(func=cmd_create)

    return parser


def main(argv: "list | None" = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    if getattr(args, "command", None) == "submit" and not (args.phase or args.competition):
        print("error: submit needs a competition or --phase.", file=sys.stderr)
        return 2
    if getattr(args, "command", None) == "outputs" and not (
            args.submission or args.phase or args.competition):
        print("error: outputs needs a competition, --phase, or --submission.", file=sys.stderr)
        return 2
    try:
        args.func(args)
    except CodabenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
