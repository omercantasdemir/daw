# Antigravity CLI (`agy`) notes

Last checked: 2026-11-15

## Launcher in use: `agentapi` (ships with the Antigravity app)

Found 2026-11-15. The app installs
`%USERPROFILE%\.gemini\antigravity\bin\agentapi.bat`, which runs
`%LOCALAPPDATA%\Programs\antigravity\resources\bin\language_server.exe agentapi`.
It talks to the running Antigravity app, so the app must be open. Help output,
copied verbatim:

```
Usage: agentapi <command> [args]
  get-conversation-metadata <conversation_id>
  new-conversation [--model=<flash_lite|flash|pro|model_id>] [--title=<title>] [--profile=<profile>] <prompt>
  send-message [--title=<title>] <recipient_id> <content>
```

| question | answer |
|---|---|
| one-shot run | `agentapi new-conversation --model=pro --title=<title> "<prompt>"` |
| model | `--model=flash_lite \| flash \| pro` or a model id |
| follow-up / status | `send-message <conversation_id> <content>`, `get-conversation-metadata <conversation_id>` |
| permission level | no flag; approvals follow the Antigravity app's own settings |
| rules file | `AGENTS.md` or `GEMINI.md`, found by walking up to the repo root; also `.agents/rules/*.md` (source: the app's built-in `agy-customizations` docs). This repo uses a root `AGENTS.md` that points to `BUILDER_RULES.md`. |

Call `language_server.exe agentapi ...` directly from PowerShell, not through
the `.bat`: the repo path contains non-ASCII characters and `cmd` can garble
them. Observations from real runs are added below as they happen.

## Status of the separate `agy` CLI: not installed

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

**Result: the Gemini CLI cannot be used on this account.** The first headless
run (task 001, 2026-11-15 13:59) failed at sign-in, before doing any work:

```
IneligibleTierError: This client is no longer supported for Gemini Code Assist
for individuals. To continue using Gemini, please migrate to the Antigravity
suite of products: https://antigravity.google
```

`--help` and `--list-models` work without this check, which is why it looked
usable. Do not retry it. The builder has to be Antigravity: the `agy` CLI once
installed, or the IDE through the manual fallback.

Still useful to know for `agy`: a headless run cannot answer approval prompts,
so running tests and committing needs an auto-approve mode or a policy file.
Run it in a git worktree on a task branch so a bad run can be thrown away.

## How runs are launched until then (manual fallback)

1. The planner writes the task to `docs/handoffs/todo/NNN_slug.md` and commits.
2. The user opens Antigravity in the repo folder and types:
   `Do docs/handoffs/todo/NNN_slug.md following docs/orchestration/BUILDER_RULES.md`
3. The user tells the planner `review NNN`. The planner reads the status report
   and the diff and writes `docs/handoffs/review/NNN_slug_review.md`.
