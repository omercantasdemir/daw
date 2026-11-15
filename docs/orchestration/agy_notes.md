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

**Result: `agentapi` cannot be called from an outside terminal.**
`get-conversation-metadata` returned `ANTIGRAVITY_LS_ADDRESS is not set`. The
app sets that variable only for its own agent processes, so this command is
for agents running inside Antigravity, not for launching runs from outside.
It was not forced.

The launcher reads `ANTIGRAVITY_LS_ADDRESS` and `ANTIGRAVITY_CSRF_TOKEN`
(names found in the binary). The values exist in
`%USERPROFILE%\.gemini\antigravity\daemon\hub_<port>.json`, but supplying the
app's session token from an outside process was blocked by the planner's own
permission system as unauthorized access, and it stays that way unless the
owner explicitly allows it. So the planner cannot start Antigravity runs by
itself today.

## Current working loop

The builder session stays open and the `todo/` folder is the planner's way to
instruct it (set up 2026-11-15 at the owner's request):

1. Once per session, the owner types in the Antigravity app:
   `Start the work loop described in AGENTS.md`
2. The builder runs `docs/orchestration/wait_for_task.py`, which blocks until
   a committed task file is in `todo/` and the tree is clean, then does that
   task and commits.
3. The builder runs the wait script again and idles. The planner's watcher
   sees the `task NNN` commit; the planner reviews, pushes the review and
   queues the next task (or a fix task), which the waiting builder picks up.
4. To end the builder's session, create the file `docs/handoffs/STOP`
   (git-ignored). Delete it before the next session.

The planner never commits while a task is in `doing/`.

## How task 001 actually ran (2026-11-15)

The owner opened the repo in the Antigravity app and typed the manual-fallback
prompt. The agent picked up `AGENTS.md`, followed `BUILDER_RULES.md`, and
finished in about 20 minutes (first file change 14:09, commit 14:29). This is
the working method until the `agy` CLI is installed.

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
