# flow

A small, local helper for working tickets with AI coding agents, so you can
stand behind every line you ship.

AI agents write code fast, and often too much of it. The hard part is
understanding it, trimming it, and defending it in review. `flow` keeps the
agents you already use (Claude Code, Codex, OpenCode, Cursor) and adds the
discipline around them: one plan per ticket, one small step at a time, a
second model that reviews independently, and nothing accepted until you
commit it yourself.

It's one dependency-free Python file.

## Principles

- **flow coordinates the work; it doesn't own your environment.** Agents stay
  ordinary CLIs. Git stays the source of truth. Progress is worked out from
  files and git, so it stays right when you work outside flow.
- **Working tree = proposal. Commit = acceptance.** Agents never commit. You
  accept a step by committing it (`flow accept`).
- **Review findings are hypotheses, not instructions.** The fixing agent
  verifies each one and disputes it with evidence when it's wrong.
- **Independent review means independent.** Reviewers run in a fresh
  process, on a different model family than the builder. The PR review runs in
  an isolated checkout with no access to earlier reviews or fixes.
- **Everything stays local.** Task files live in `~/.flow`. flow never pushes
  or touches GitHub.

## Install

Requires Python 3.11+ and git.

```sh
git clone https://github.com/<you>/flow.git
ln -s "$PWD/flow/flow.py" ~/.local/bin/flow     # any directory on your PATH
flow init
```

`flow init` writes `~/.flow/config.toml`, the stage prompts in
`~/.flow/prompts/`, and Claude Code slash commands in `~/.claude/commands/`.
It prints two optional additions: a shell function for switching tickets, and
a Claude Code status line that always shows the next step.

Then edit `~/.flow/config.toml`: set `test_cmd`, check `ticket_prefer` (Jira
via `acli` by default), and run `flow agents` to see which agent, and which
ticket fetcher, gets the job.

## A ticket, start to finish

```sh
flow start PROJ-123       # fetch the ticket, link this clone
flow                      # tracker: where you are and what's next
flow next                 # run the next step
```

Or step by step:

| Command | What happens |
|---|---|
| `flow plan` | Agent plans in plan mode; every claim labeled OBSERVED / INFERRED / UNKNOWN |
| `flow review` | Second model reviews the plan (before code) or the code (after) |
| `flow build` | One plan step, test first; the agent stops for you |
| `flow diff` | What's waiting for your accept, marked against the plan |
| `flow accept` | Tests, scope check, then *you* commit: that's acceptance |
| `flow deslop` | Fresh eyes list code the ticket doesn't need; you pick what goes |
| `flow fix` | Builder verifies review findings; fixes or disputes with evidence |
| `flow check` | Tests, and nothing from `.flow` staged |
| `flow defend` | A skeptical reviewer quizzes you on the change |
| `flow pr` | Isolated independent review of the committed change + PR description |

`flow accept` stops if files outside the plan changed and asks you why, then
records your reason in the plan and the commit message.

```
PROJ-123 (retry)  ~/src/repo-2 · feature/PROJ-123-retry

   ✔ Ticket         fetched
   ✔ Plan           5 steps
   ○ Plan review    optional
 ▶ ◐ Build          3/5 steps · awaiting your accept
   · Deslop
   · Code review
   ...
 Next: flow accept   review the diff and commit it (step 3 done, not accepted yet)
```

## Several tickets, several clones

`flow start KEY` in any clone links it to the ticket. Switch with
`fs 123` (the shell function from `flow init`), by key, alias, branch name, or
a unique fragment. `flow ls` lists everything.

If a ticket's state gets broken (a bad plan, a stuck review, a stale link),
`flow clear KEY` deletes its flow data entirely and unlinks every clone, so
`flow start KEY` starts it clean.

## Agents and models

Built in: `claude`, `codex`, `opencode`, `cursor`. `flow agents` shows what's
installed and the reason for each role assignment. Builders come from your
`prefer` list; reviewers from a different model family than the builder.

Add your own on top of a built-in:

```toml
[agents.fireworks]
base = "opencode"
model = "fireworks/<model-id>"
family = "<model maker>"

[agents.claude-skills]            # use an installed skill, keep flow's format
base = "claude"
prompt_prefix = "Use your code-review skill for this. Report findings in the format below."
```

Use one for a single run with `--with NAME`, or set it in `[roles]`.
`flow stats` shows, per reviewer and model, how many findings were fixed
versus disputed, so you can pick reviewers on evidence from your own code.

## Ticket fetchers

Built in: `acli` (Jira). Add another the same way as an agent - anything that
takes a key and prints the ticket works, including a script wrapping one call
to Glean, an internal API, or an MCP tool (flow only ever shells out to it,
once, before any agent starts):

```toml
ticket_prefer = ["glean", "acli"]

[tickets.glean]
cmd = "glean search --format md {key}"
```

Use one for a single run with `flow ticket --with NAME` or `flow start KEY --with NAME`.

## Prompts

Each stage's prompt is a markdown file in `~/.flow/prompts/`. Edit freely
(keep the first-line marker); `flow init --force` restores the defaults.
`flow prompt NAME` prints what an agent receives, for tools without slash
commands.

## Status

Early and personal. The workflow logic is tested against stub CLIs; agent CLI
flags change often, so if a launch fails, override that agent's command in
`[agents.*]`. `tools/agent_spike.py` checks whether each installed agent CLI
can run headless and stay read-only.

## License

MIT
