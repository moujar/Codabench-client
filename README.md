# codabench-client

A small, readable Python client and CLI for the [Codabench](https://www.codabench.org/) API.

Codabench is a great benchmark platform, but a lot of what you can do in its web UI —
grabbing a starting kit, submitting a zip, pulling the scoring logs of a failed run —
is tedious to click through and awkward to automate. This package does all of it from
the terminal or from Python.

```bash
codabench show 17363                        # everything about a competition
codabench files 16161                       # download the starting kit & public data
codabench submit 17525 -z run.zip --wait    # submit and watch the score come back
codabench outputs 17525                     # fetch the prediction & scoring output
```

---

## Install

```bash
pip install codabench-client
```

That puts the `codabench` command on your PATH and makes `import codabench` available.
Pin it if you want a fixed version: `pip install codabench-client==0.1.0`.

To work on the package itself:

```bash
git clone https://github.com/moujar/codabench-client.git
cd codabench-client
pip install -e .
```

Python 3.9+ and `requests` are the only requirements. Without installing, everything
also works as `python -m codabench ...` and `python examples/01_show_competition.py`.

## Credentials

Copy the template and fill it in:

```bash
cp .env.example .env
```

```ini
CODABENCH_USERNAME=your_username
CODABENCH_PASSWORD=your_password
# CODABENCH_URL=https://dev.codabench.org/   # optional; default is www.codabench.org
```

`.env` is gitignored. Environment variables win over the file, so CI can just set
`CODABENCH_USERNAME` / `CODABENCH_PASSWORD`. Reading a **public** competition needs no
credentials at all.

## Commands


| Command                                      | What it does                                             |
| ---------------------------------------------- | ---------------------------------------------------------- |
| `codabench competitions [--search TEXT]`     | List competitions                                        |
| `codabench show <id\|url>`                    | Pages, phases, tasks, files, leaderboard                 |
| `codabench files <id\|url>`                   | List / download the "Files" tab                          |
| `codabench submit <id\|url> -z FILE`          | Upload a submission, optionally wait for the score       |
| `codabench outputs <id\|url>`                 | Download a submission's zip, prediction & scoring output |
| `codabench rerun --submission ID --task KEY` | Re-run a submission on another task (robot accounts)     |
| `codabench create -b bundle.zip`             | Create a competition from a bundle                       |


Every command takes `--url`, `--username`, `--password`, `--env`, and `--help`.

### Inspect a competition

```bash
codabench show 17363                # or the full https://www.codabench.org/competitions/17363/ URL
codabench show 17363 --pages        # full text of every page
codabench show 17363 --json         # raw API payload
```

Save the whole thing — description, one markdown file per page, and every file you are
allowed to download:

```bash
codabench show 17363 --save-dir workdir/17363
```

```
workdir/17363/
├── description.md
├── pages/
│   ├── 00-overview.md
│   ├── 01-data.md
│   └── ...
└── input/
    └── Track 1 Starting Kit V5/
```

Add `--no-download` for the text only.

### Download competition files

```bash
codabench files 16161 --list                 # see what exists first
codabench files 16161                        # download into files/16161/
codabench files 16161 --only starting_kit    # filter by type or name
codabench files 16161 --no-extract           # keep the zips
```

### Submit and get scored

```bash
codabench submit 17525 -z submission.zip --wait
codabench submit 17525 -z submission.zip --wait \
    --results-json results.json --download-dir outputs
```

The phase is resolved automatically (the only one, or the currently open one); pass
`--phase <id>` or `--phase-index <n>` when a competition has several open at once.
Submitting **consumes your daily quota** — the command checks eligibility first and
tells you if you are out.

### Get a submission's output

```bash
codabench outputs 17525 --list              # your submissions on the phase
codabench outputs 17525                     # newest submission
codabench outputs 17525 --last 2            # the one before it
codabench outputs --submission 856524       # a specific id
codabench outputs 17525 --only scoring      # just the scoring step
```

Everything lands in `outputs/<submission id>/` with the zips extracted, plus a
`details.json` holding the scores, logs and exit statuses — which is usually where the
answer is when a submission fails.

## Python API

```python
from codabench import CodabenchClient, collect_files, find_phase

client = CodabenchClient()                     # reads .env / environment

competition = client.competition(17363)        # id or URL
phase = find_phase(competition)                # the open phase

for entry in collect_files(competition):
    path = client.download_dataset(entry.key, "input/", entry.filename)
    print(entry.name, "->", path or "not authorized")

submission = client.submit(phase["id"], "run.zip")
client.wait_for_submission(submission["id"])
print(client.results(submission["id"])["metrics"])
```

The client raises `CodabenchError` (with `AuthError` and `ApiError` subclasses) and
never calls `sys.exit`, so it is safe to use inside a notebook or a larger program.

## What you can actually download

This trips everyone up, so it is worth stating plainly. Codabench decides per file, and
this tool cannot widen what your account is allowed to see:


| File                            | Who can download it                                                   |
| --------------------------------- | ----------------------------------------------------------------------- |
| Starting kit, public data       | Any approved participant                                              |
| Ingestion / scoring program     | Participants**only if** the organizer set `make_programs_available`   |
| Input data                      | Participants**only if** the organizer set `make_input_data_available` |
| Reference data (the answer key) | Organizers only, always                                               |
| Competition bundle              | Organizers only                                                       |

Files your account may not fetch are skipped, not treated as an error. `codabench show`
prints the organizer's two flags so you can see why something is missing.

## How authentication works

Codabench uses **two** mechanisms and you need both — the reason `CodabenchClient` holds
a token *and* a session:


| Endpoint                    | Auth                                                  |
| ----------------------------- | ------------------------------------------------------- |
| `/api/...`                  | Token from`POST /api/api-token-auth/`                 |
| `/datasets/download/<key>/` | Django**session cookie** from `POST /accounts/login/` |

The download route behind the "Files" tab is a plain Django view that ignores the API
token, which is why a token-only client gets 403s on files a participant can plainly
download in the browser. Both schemes read the same credentials, so callers never have
to think about it.

(There is also `GET /api/competitions/{id}/get_files/`, but it is organizer-only and
returns 403 for participants — this package does not rely on it.)

## Repository layout

```
codabench/              the library
├── auth.py             credentials, token auth, session login
├── client.py           CodabenchClient — every API call
├── competitions.py     pure helpers over a competition payload
├── downloads.py        saving & extracting artifacts
├── text.py             HTML→text, slugs, sizes
├── errors.py           CodabenchError / AuthError / ApiError
└── cli.py              the `codabench` command

examples/               the same flows as standalone scripts
├── 01_show_competition.py
├── 02_download_competition_files.py
├── 03_submit_and_wait.py
├── 04_download_submission_outputs.py
├── 05_create_competition.py
└── 06_rerun_submission.py

assets/                 a sample submission zip and competition bundle
```

Run any example directly — no install needed:

```bash
python examples/01_show_competition.py 17363
```

## Notes

* **Organizers**: `codabench create -b bundle.zip` uploads a competition bundle and polls
  until it is unpacked. Try it on `https://dev.codabench.org/` first.
* **Robot accounts**: `codabench rerun` re-runs an existing submission against another
  task, reusing the uploaded data. It needs an account flagged `is_bot`, or the API
  answers 403.

## License

MIT.
