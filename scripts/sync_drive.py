#!/usr/bin/env python3
"""
sync_drive.py - Copy results/ and eval/ to the team Google Drive with rclone.

Targets on the team Drive (layout in the Drive's README.md):
    results/ -> <MEDRAG_DRIVE_REMOTE>/04_results/<MEDRAG_PROBLEM>/
    eval/    -> <MEDRAG_DRIVE_REMOTE>/03_eval/<MEDRAG_PROBLEM>/

Runs at the end of every Claude Code session (SessionEnd hook in .claude/settings.local.json)
and once a day from Windows Task Scheduler. Uses `rclone copy --checksum`: unchanged files are
skipped and nothing on Drive is ever deleted. data/ is never synced - it is a frozen snapshot
that goes to Drive only as a new version via make_snapshot.py (docs/DECISIONS.md D2/D3).

One-time setup:
    winget install Rclone.Rclone
    rclone config                     # remote "gdrive" -> NLP_Project Shared Drive
    # in .env:  MEDRAG_DRIVE_REMOTE=gdrive:  and  MEDRAG_PROBLEM=p1

Usage (from anywhere):
    python scripts/sync_drive.py              # copy changed files
    python scripts/sync_drive.py --dry-run    # list what would be copied
    python scripts/sync_drive.py --quiet      # no console output (for hooks / scheduler)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# local folder -> folder on the team Drive (see the Drive's README.md); {problem} = MEDRAG_PROBLEM
FOLDERS = {"results": "04_results/{problem}", "eval": "03_eval/{problem}"}
EXCLUDES = (".ipynb_checkpoints/**", "__pycache__/**", "*.tmp", "CLAUDE.md")
LOG_FILE = ROOT / "logs" / "sync.log"
SETUP_HELP = """\
Drive sync is not set up yet - skipping. One-time setup:
  1. winget install Rclone.Rclone   (then open a new terminal)
  2. rclone config                  (new remote, type 'drive', name it e.g. 'gdrive')
  3. add to .env:  MEDRAG_DRIVE_REMOTE=gdrive:  and  MEDRAG_PROBLEM=p1"""


def load_remote() -> str | None:
    """Return MEDRAG_DRIVE_REMOTE from the environment or .env."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    return os.getenv("MEDRAG_DRIVE_REMOTE") or None


def find_rclone() -> str | None:
    """Return the rclone executable, also checking winget's install folder.

    Processes started before rclone was installed (e.g. the editor running the hook) do not
    see the updated PATH, so fall back to where `winget install Rclone.Rclone` puts it.
    """
    found = shutil.which("rclone")
    if found:
        return found
    winget = Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    candidates = [winget / "Links" / "rclone.exe",
                  *sorted((winget / "Packages").glob("Rclone.Rclone_*/*/rclone.exe"))]
    return next((str(p) for p in candidates if p.is_file()), None)


RCLONE = find_rclone()


def setup_problem(remote: str | None) -> str | None:
    """Return a reason the sync cannot run, or None if rclone and the remote are ready."""
    if RCLONE is None:
        return "rclone not found on PATH or in the winget folder"
    if not remote or ":" not in remote:
        return "MEDRAG_DRIVE_REMOTE not set in .env"
    remotes = subprocess.run(
        [RCLONE, "listremotes"], capture_output=True, text=True, check=False
    ).stdout.split()
    if remote.split(":")[0] + ":" not in remotes:
        return f"rclone remote '{remote.split(':')[0]}' is not configured"
    return None


def copy_folder(folder: str, target: str, dry_run: bool) -> tuple[int, int, str]:
    """Copy one local folder to a remote target; return (files copied, exit code, stderr tail)."""
    cmd = [RCLONE, "copy", str(ROOT / folder), target,
           "--checksum", "--log-level", "INFO"]
    for pattern in EXCLUDES:
        cmd += ["--exclude", pattern]
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    marker = "Skipped copy as --dry-run is set" if dry_run else ": Copied"
    copied = sum(marker in line for line in proc.stderr.splitlines())
    tail = proc.stderr.strip().splitlines()[-1] if proc.returncode else ""
    return copied, proc.returncode, tail


def log(line: str) -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}  {line}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="list files without copying")
    ap.add_argument("--quiet", action="store_true", help="no console output")
    args = ap.parse_args()
    say = (lambda *_: None) if args.quiet else print

    remote = load_remote()
    problem = setup_problem(remote)
    if problem:
        log(f"SKIPPED  {problem}")
        say(f"{problem}.\n{SETUP_HELP}")
        return 0

    mode = "DRY-RUN" if args.dry_run else "COPY"
    problem_id = os.getenv("MEDRAG_PROBLEM", "p1")
    status = 0
    for folder, subpath in FOLDERS.items():
        if not (ROOT / folder).is_dir():
            continue
        sep = "" if remote.endswith(":") else "/"
        target = f"{remote.rstrip('/')}{sep}{subpath.format(problem=problem_id)}"
        copied, code, tail = copy_folder(folder, target, args.dry_run)
        result = "ok" if code == 0 else f"rclone exit {code}: {tail}"
        log(f"{mode:8} {folder}/ -> {target}  files={copied}  {result}")
        say(f"{folder}/: {copied} file(s) {'would be ' if args.dry_run else ''}copied ({result})")
        status = status or code
    return 1 if status else 0


if __name__ == "__main__":
    sys.exit(main())
