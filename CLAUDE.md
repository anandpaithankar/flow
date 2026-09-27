# flow: notes for Claude Code

Context for continuing development. Read this before changing anything.

## What flow is

A local helper for working Jira tickets with AI coding agents (Claude Code,
Codex, OpenCode, Cursor). It adds discipline around agents the user already
runs: shared ticket context, one plan per ticket, small steps, independent
second-model review, and human acceptance by commit. It's one dependency-free
Python 3.11 file, `flow.py`.

The workflow it serves: fetch a ticket -> plan with an agent -> build step by
step -> review locally with another model -> fix -> commit and push -> Copilot
reviews the PR -> address comments -> human reviewers. The user works on
several tickets at once, in separate clones of the same repos.

## Principles (don't break these)

1. **flow coordinates the workflow; it doesn't own the environment.** Agents
   stay ordinary CLIs. Git is the source of truth.
2. **Derive state, don't store it.** `compute()` works out progress from
   `.flow/` files and git, so it stays correct when work happens outside flow
   (slash commands, other agents, plain git). `state.toml` is only a snapshot.
3. **Working tree = proposal. Commit = acceptance.** Agents never commit. The
   user accepts by committing (`flow accept`, or plain `git commit`).
4. **Review findings are hypotheses, not instructions.** `fix` verifies each
   finding and disputes wrong ones with evidence.
5. **Independence is real.** Reviewers (`review`, `defend`, `pr`) default to a
   different model family than the builder. `flow pr` runs headless in a
   temporary worktree of HEAD with no `.flow` and no fix history.
6. **Everything stays local.** Task files live in `~/.flow/tasks/<KEY>/`,
   linked into each clone as a `.flow` symlink listed in `.git/info/exclude`.
   flow never pushes and never talks to GitHub.
7. **The user never fills in files.** Agents write every artifact; the user
   reviews in chat and decides.
8. **Keep it one small file.** Stdlib only. No daemon, database, server, MCP
   server, plugin framework, workflow DSL, or full TUI. Add features only when
   real use shows friction.

## Layout of flow.py

- Top: docstring (command summary), constants, `DEFAULT_CONFIG`,
  `PROMPT_FILES` (the stage prompt defaults), `BUILTIN_AGENTS`, `ROLES`,
  `FRESH_EYES`, `OLD_DEFAULT_PROMPTS`.
- Helpers: `git()`, `repo_root()`, TOML writing, config loading.
- Tasks: `find()`/`resolve()` (key, alias, branch, then substring; never
  guesses on ambiguity), `current()` (task linked into the clone),
  `link_repo()`, `repo_fingerprint()` (blocks resuming a key in an unrelated
  repo), `fetch_ticket()` and its `ticket_fetchers()`/`pick_ticket_fetcher()`
  (`[tickets.*]` config, same pick-from-`prefer` pattern as agents).
- Plan parsing and diffs: `plan_files()`, `plan_file_reasons()` (the `- why`
  after each backticked path), `plan_expected_scope()`, `plan_steps()`,
  `in_plan()`, `merge_base()`, `diff_with_new_files()`, `diff_summary()`
  (shared by `cmd_diff()` and `cmd_accept()`: per-file plan mark, +/- lines,
  reason).
- Tracker: `compute()` (stages, statuses, next step), `render()`,
  `show_tracker()`, `cmd_next()`, `cmd_statusline()`, `cmd_watch()`.
- Acceptance: `cmd_accept()` (scope gate, tests, commit), `add_to_plan()`,
  `cmd_diff()`.
- Agents: `agents()` (built-ins merged with `[agents.*]` config), `pick()`
  (role -> agent, with the reason), `build_argv()` (`{prompt}`, `{model}`,
  `prompt_prefix`), `cmd_stage()` (interactive launch), `cmd_review()` and
  `cmd_pr()` (headless, read-only), `cmd_stats()`.

## Contracts the code parses (keep prompts and code in sync)

- plan.md: a heading containing "files" (`## Files that change`) with
  backticked paths as bullets, each followed by `- why this file must change`
  (`plan_file_reasons()` parses it back out for `flow diff`/`flow accept`);
  steps as `- [ ]` / `- [x]` checkboxes; a heading containing "expected scope"
  whose body is shown verbatim next to the actual diff.
- Review findings start with `[Important]`, `[Question]`, or `[Nit]`.
- `fix` appends `## Outcome` with `fixed:`, `disputed:`, `skipped:`,
  `questions:` counts; `flow stats` and the tracker read them.
- `deslop.md` and `defend.md` end with a `## Result` block.
- Review files begin with a header comment containing `agent=` and `model=`.

## Prompt upgrade mechanism (important)

Prompts are written to `~/.flow/prompts/` with a first-line `MARKER`.
`flow init` rewrites a prompt only if it's missing, lacks the marker, or its
sha256 matches a known old default in `OLD_DEFAULT_PROMPTS`. That keeps user
edits and upgrades untouched copies.

**Whenever you change a default in `PROMPT_FILES`, add the sha256 of
`MARKER + "\n" + <old text>` to `OLD_DEFAULT_PROMPTS[name]`.** Otherwise users
with the old default never get the new one.

## Testing approach

There's no test suite yet; changes were verified with scripts that:
- set `HOME` to a temp dir (so `~/.flow` and `~/.claude` are sandboxed),
- put stub agent CLIs first on `PATH` (shell scripts that echo their
  arguments or print fake findings),
- create a bare "origin" repo plus two clones to exercise switching, pushes,
  and the isolated PR worktree.
Adding a pytest suite built the same way is a reasonable first task.

Real agent CLI flags (especially OpenCode and Cursor) were not verified
against the actual tools; `tools/agent_spike.py` checks headless runs and
read-only behavior. Don't assume flags; check each tool's `--help`.

## Decisions already made (and why)

- Removed: `intent.md` stage and all user-filled templates (friction).
- Removed: Claude Code scope hook and `flow approve`; scope is enforced at
  `flow accept` instead, which works for every agent. `flow hook` remains
  as a no-op so an old hook config can't block edits.
- `/flow-pr` is not a slash command: the PR review must not run inside the
  working session. `/flow-deslop` and `/flow-defend` need fresh eyes for
  their judgment call if the conversation already contains work on the
  ticket: dispatch a subagent with a clean context for that part (Claude
  Code only - a subagent can't pause for the interactive part, so that
  still happens in the working session), falling back to "run it in a new
  terminal" for agents without subagents.
- herdr integration and a TUI were deferred. If a TUI comes, build single
  screens over the same files (review triage first), not an app.
- Reviewer choice is by model family, never by stats. Stats only collect
  evidence.

## Possible next steps (only if real use asks for them)

- Import PR comments (Copilot, Cursor Bugbot, humans) via `gh` into `.flow`
  so `flow fix` and `flow stats` cover them. Read-only toward GitHub.
- Per-repository notes that every prompt picks up.
- A pytest suite (see Testing approach).
