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

## How runs are launched until then (manual fallback)

1. The planner writes the task to `docs/handoffs/todo/NNN_slug.md` and commits.
2. The user opens Antigravity in the repo folder and types:
   `Do docs/handoffs/todo/NNN_slug.md following docs/orchestration/BUILDER_RULES.md`
3. The user tells the planner `review NNN`. The planner reads the status report
   and the diff and writes `docs/handoffs/review/NNN_slug_review.md`.
