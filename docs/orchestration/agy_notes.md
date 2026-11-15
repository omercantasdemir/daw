# Antigravity CLI (`agy`) notes

Last checked: 2026-11-15

## Status: `agy` is NOT installed, so runs use the manual fallback

- `agy` is not on PATH (`Get-Command agy` finds nothing).
- The Antigravity **IDE** is installed at
  `%LOCALAPPDATA%\Programs\antigravity\Antigravity.exe`, but it ships no `agy`
  binary. The IDE is not the CLI.
- `%USERPROFILE%\.gemini\` exists with an `antigravity\` subfolder, so the IDE
  has been signed in on this machine.

## Still unknown (do not guess; fill in from `agy --help` after install)

| question | answer |
|---|---|
| one-shot / headless flag (prompt or prompt file, no TUI) | unknown |
| model selection flag and the exact model ids | unknown |
| permission / approval level flag | unknown |
| project rules file name and location | unknown |

Once `agy` is installed: run `agy --version`, `agy --help` and
`agy <subcommand> --help`, replace this table with the real flags and the exact
launch command, then copy or link `BUILDER_RULES.md` to the rules file `agy`
reads.

## Alternative found: Gemini CLI (`gemini` 0.68.0) IS installed

Path: `%APPDATA%\npm\gemini.ps1`, signed in with the personal Google account
(`oauth-personal`). It is a different product from Antigravity and offers a
different model list. Flags below are copied from `gemini --help` on
2026-11-15.

| question | answer |
|---|---|
| headless run | `-p "<prompt>"` (stdin is prepended if given) |
| model | `-m <id>` |
| models on this account (`gemini --list-models`) | `gemini-2.5-pro`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `auto`. **No `gemini-3.1-pro`.** |
| approval level | `--approval-mode default \| auto_edit \| yolo \| plan`; finer control with `--policy <file>` |
| isolation | `-w <name>` runs in a new git worktree; `-s` sandbox |
| output | `-o text \| json \| stream-json` |
| rules file | not stated in `--help`; the task prompt names `BUILDER_RULES.md` explicitly, so no rules file is relied on |

Not yet used for a build. Open points before the first run: the owner's OK to
use this CLI instead of Antigravity, which model replaces Gemini 3.1 Pro, and
the approval mode (a headless run cannot answer prompts, so running tests and
committing needs `yolo` or a policy file; with `auto_edit` alone the builder
can edit files but not run the checks).

## How runs are launched until then (manual fallback)

1. The planner writes the task to `docs/handoffs/todo/NNN_slug.md` and commits.
2. The user opens Antigravity in the repo folder and types:
   `Do docs/handoffs/todo/NNN_slug.md following docs/orchestration/BUILDER_RULES.md`
3. The user tells the planner `review NNN`. The planner reads the status report
   and the diff and writes `docs/handoffs/review/NNN_slug_review.md`.
