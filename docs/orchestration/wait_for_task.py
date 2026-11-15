"""Wait until the planner has queued a task, then print which one.

The builder runs this after finishing a task instead of ending its session:

    python docs/orchestration/wait_for_task.py

It prints exactly one line and exits:

    TASK: docs/handoffs/todo/NNN_slug.md     do this task now
    RESUME: docs/handoffs/doing/NNN_slug.md  a task was left unfinished; finish it
    WAIT: ...                                nothing yet; run this command again
    STOP: ...                                the owner asked the builder to stop

A task is reported only when its file is committed and the working tree is
clean, so the builder never starts while the planner is in the middle of
writing or committing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFFS = ROOT / "docs" / "handoffs"
STOP_FILE = HANDOFFS / "STOP"


def git(*args: str) -> subprocess.CompletedProcess:
    """Run a git command in the repo root and capture its output."""
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def task_files(folder: str) -> list[Path]:
    """Task files in a handoff folder, lowest number first."""
    return sorted((HANDOFFS / folder).glob("*.md"))


def relative(path: Path) -> str:
    """Repo-relative path with forward slashes."""
    return path.relative_to(ROOT).as_posix()


def check() -> str | None:
    """Return the line to print, or None if there is nothing to do yet."""
    if STOP_FILE.exists():
        return "STOP: docs/handoffs/STOP exists; end the session and say so"
    doing = task_files("doing")
    if doing:
        return f"RESUME: {relative(doing[0])}"
    todo = task_files("todo")
    if not todo:
        return None
    task = relative(todo[0])
    committed = git("ls-files", "--error-unmatch", task).returncode == 0
    clean = git("status", "--porcelain").stdout.strip() == ""
    if committed and clean:
        return f"TASK: {task}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=240.0,
                        help="seconds to wait before printing WAIT (default 240)")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="seconds between checks (default 10)")
    args = parser.parse_args()

    deadline = time.monotonic() + args.timeout
    while True:
        line = check()
        if line:
            print(line)
            return 0
        if time.monotonic() >= deadline:
            print("WAIT: no task queued yet; run this command again")
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
