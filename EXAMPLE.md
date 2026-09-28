# Using flow day to day

This is a walkthrough, not a reference (see [README.md](README.md) for that).
It follows one fictitious ticket from `flow start` to a merged PR, then pulls
out the two habits that make flow pay off every day after: the workflow loop,
and picking agents deliberately instead of using whatever's on PATH by default.

By the end you should be able to: run a ticket start to finish, keep several
tickets moving in parallel, assign specific agents/models to specific stages
on purpose, and know which knobs in `config.toml` to reach for and when.

## Before you start

You need Python 3.11+, git, and at least one agent CLI (`claude`, `codex`,
`cursor-agent`, or `opencode`) on PATH.

```sh
flow init
```

This writes `~/.flow/config.toml`, the stage prompts in `~/.flow/prompts/`,
and (in Claude Code) `/flow-plan`, `/flow-build`, `/flow-deslop`, `/flow-fix`,
`/flow-defend` under `~/.claude/commands/`. It also prints two copy-paste
extras: a shell function for switching tickets by name, and a status line
that always shows your next step. Add both - you'll use them constantly:

```sh
fs() { cd "$(flow path "$1")" || return; flow status; }
```

Then open `~/.flow/config.toml` and set `test_cmd` to whatever runs your
tests. Everything else has a working default. Run `flow agents` once to see
what flow found:

```
agents:
  + claude     2.1.283 (Claude Code)    anthropic   default model   plan, build, deslop, fix
  + codex      codex-cli 0.157.1        openai      default model   defend, pr, review
  - opencode   not installed (opencode) unknown     default model   -
  - cursor     not installed (cursor-agent) unknown default model   -
```

If a CLI you know you installed shows as "not installed" here, check whether
it's actually on PATH in the shell flow runs in (`which claude`, etc.) - a GUI
install doesn't always add one. When flow can also find that agent's config
directory (`~/.claude`, `~/.codex`, `~/.cursor`, `~/.config/opencode`) it says
so next to "not installed", e.g. `not installed (codex) - found ~/.codex, not
on PATH` - that's the signal it's installed but not linked into your shell,
not a general filesystem scan (flow never reads outside those well-known
dirs, and never touches anything without your say-so).

## The walkthrough: PAY-482

Meet Priya, working `PAY-482: retry webhook delivery on transient failures` in
`~/src/billing-service`.

**1. Start the ticket.** This fetches the ticket text once (so every agent
reads the same thing) and links this clone to it.

```sh
cd ~/src/billing-service
flow start PAY-482
flow
```

```
PAY-482  ~/src/billing-service · main

 ▶ · Plan           flow plan          no plan yet
   ○ Plan review    flow review --plan optional
   · Build          flow build
   · Deslop         flow deslop
   · Code review    flow review
   · Fix            flow fix
   · Check          flow check
   · Push           git push
   · Defend         flow defend
   · PR review      flow pr

 Next: flow plan   plan the change with the agent
```

**2. Plan.** `flow plan` (or `/flow-plan` in Claude Code) opens the agent
assigned to `plan` in plan mode. It reads `.flow/ticket.md`, asks Priya a few
grounding questions in chat, proposes an approach, and - once she agrees -
writes `.flow/plan.md`:

```markdown
## Files that change
- `webhooks/delivery.py` - add retry-with-backoff around the POST
- `webhooks/config.py` - add `WEBHOOK_MAX_RETRIES` setting

## Expected scope
Files: 2 · New abstractions: none · New dependencies: none
Public API or schema changes: none

## Steps
- [ ] P1. add retry loop with exponential backoff - proven by: test simulates two 503s then a 200
- [ ] P2. make retry count configurable - proven by: test overrides the setting and observes 1 retry

## Test strategy
- webhook eventually delivered despite transient 5xx → P1 → `deliver()` → new test → 200 after retries, no more than max attempts
```

Optionally, `flow review --plan` gets a second model's opinion on the plan
itself before any code exists - cheaper to fix a bad plan than a bad diff.

**3. The build loop.** This is the part that repeats. For each step:

```sh
flow build          # or flow next - see below
```

The builder writes a failing test, makes it pass, runs the suite, ticks the
step's checkbox, and stops - it never commits. Priya looks at the diff:

```sh
flow diff
```

```
expected: Files: 2 · New abstractions: none · New dependencies: none

  ✓ M webhooks/delivery.py  +18 -2  why: add retry-with-backoff around the POST
  ✓ M tests/test_delivery.py  +21 -0  (new, untracked)

  +39 -2
```

Every file is marked against the plan (`✓` in scope, `!` not) with the reason
the plan gave for touching it, so "why was this touched" never means
re-reading the plan separately. Looks right, so she accepts - accepting *is*
committing, nothing else does:

```sh
flow accept
```

If the agent had also touched a file the plan didn't mention, `flow accept`
would stop and ask why, rather than silently letting scope grow. Repeat for
P2. Once both steps are done, `flow` shows Build as done and points at the
next stage - or just run `flow next` and let it figure out what that is:

```sh
flow next    # runs whatever's next: build, accept, review, check, ...
```

**4. Deslop.** Fresh eyes (a subagent with a clean context, in Claude Code)
list anything the ticket doesn't need - a stray comment, an unused helper.
Priya picks what actually goes; nothing is removed without her say.

```sh
flow deslop
```

**5. Code review.** A second model, from a different family than the
builder, reviews the diff independently:

```sh
flow review
```

Findings come back as `[Important]` / `[Question]` / `[Nit]`. They're
hypotheses, not orders:

```sh
flow fix
```

`flow fix` verifies each finding against the actual code before touching
anything - it fixes real ones and disputes wrong ones with evidence, then
appends counts (`fixed: 2, disputed: 1, skipped: 0`) that `flow stats` later
uses to judge whether that reviewer is worth listening to.

**6. Check, push, defend, PR.**

```sh
flow check     # tests pass, and nothing from .flow is staged
git push
flow defend    # a skeptical reviewer quizzes Priya on the change, live
flow pr        # independent review in an isolated worktree of HEAD + PR description
```

`flow pr` runs headless, in a temporary worktree with no `.flow` directory and
no memory of the fixes above - it can't be talked into agreeing with itself.
Its output becomes the PR description. Push, open the PR, let Copilot/Bugbot
comment, then `flow fix` again to work through those the same way as any
other review.

## Establishing the workflow loop

Two loops, nested:

- **The inner loop**, run once per plan step: `flow build` → `flow diff` →
  `flow accept` → `flow next`. You almost never need to remember which stage
  comes after which - `flow` (no args) or `flow next` always says.
- **The outer loop**, run once per ticket: plan → build (steps) → deslop →
  review → fix → check → push → defend → pr → address PR comments. `flow`
  shows this as a tracker with a `▶` pointing at where you are.

**Several tickets at once.** flow expects you to run several tickets in
parallel, each in its own clone. Switch with the `fs` function from setup:

```sh
fs 482        # cd's into PAY-482's clone (matches key, alias, branch, or substring)
flow ls       # every ticket you've started, and where
```

Drop `flow watch` in a side pane of whichever clone you're actively in - it
updates in place as you and the agent make progress, so you don't have to
keep re-running `flow`.

If a ticket's state ever gets tangled (a bad plan, a stuck review),
`flow clear PAY-482` deletes its flow data and unlinks every clone, so
`flow start PAY-482` begins clean without touching your git history.

## Using multiple providers well

flow's independence guarantee - the reviewer should not share the builder's
blind spots - is enforced by model *family*, not by brand loyalty, and it's
automatic by default:

```toml
prefer = ["claude", "codex", "cursor", "opencode"]

[roles]
plan = "auto"
build = "auto"
review = "auto"
```

With everything set to `"auto"`, flow builds with the first installed agent
in `prefer`, then for `review`/`defend`/`pr` picks the first *other* installed
agent whose `family` differs from the builder's - Priya builds with Claude,
so review/defend/pr default to Codex, without her configuring anything.
`flow agents` always shows the reasoning:

```
roles:
  build   -> claude   first installed in `prefer`
  review  -> codex    different model family from builder (claude)
```

**Pin a stage on purpose** when you want a specific model for a specific job,
not just "the first other one":

```toml
[roles]
build = "claude"
review = "gpt5-review"

[agents.gpt5-review]
base = "codex"
model = "gpt-5"
```

**One-off overrides** don't touch config at all:

```sh
flow review --with cursor     # just this run
```

**Reach more models through one CLI.** `opencode` can drive many providers;
add each as its own named agent so it shows up in `flow agents` and can be
pinned to a role:

```toml
[agents.fireworks]
base = "opencode"
model = "fireworks/<model-id>"   # ids: `opencode models`
family = "fireworks"             # so independence logic knows it differs from claude/codex
```

**Use a Claude Code skill for one stage**, without making flow itself
Claude-only - `prompt_prefix` just prepends an instruction to that stage's
prompt, and only for agents that understand it:

```toml
[agents.claude-tdd]
base = "claude"
prompt_prefix = "Use your test-driven-development skill for this step, but still follow the report format below."

[roles]
build = "claude-tdd"
```

Because this lives in `[agents.*]`, it's per-role and per-agent: `fix` can
still run on plain `claude`, or on `codex`, unaffected.

## Tuning reference

All of this lives in `~/.flow/config.toml`, written once by `flow init` and
never touched by flow again after that - it's yours.

| Setting | What it controls | Change it when |
|---|---|---|
| `base_branch` | what `flow diff`/`accept`/`deslop`/`pr` compare against | origin/HEAD guesses wrong, or you don't use `main` |
| `test_cmd` | what `flow accept`/`check` run before letting you commit | always - it's blank by default |
| `diff_cmd` | how `flow diff` shows the line-by-line change, after its own summary | you prefer `delta` or `difftastic` over plain `git diff` |
| `ticket_prefer` / `[tickets.*]` | how `.flow/ticket.md` gets fetched | you use something other than `acli`/Jira |
| `prefer` | the order agents are tried for "auto" roles | you want a different default builder |
| `[roles]` | pin one stage to one agent instead of "auto" | you always want e.g. `review` on a specific model |
| `review_timeout` | how long a headless review/defend/pr run can take | reviews are timing out on a big diff |
| `[agents.*]` (`base`, `model`, `family`, `prompt_prefix`) | define a new agent, or a variant of a built-in one | a new model, a Fireworks/OpenCode combo, or a skill hookup |

Stage prompts themselves (`~/.flow/prompts/*.md`) are separate from config -
edit them directly; `flow init --force` only overwrites a prompt that's
unedited or a known old default, never your changes.

## Checklist

After this guide you should be able to: start and run a ticket end to end;
read `flow diff`'s in/out-of-plan marks before accepting; use `flow next` and
`flow watch` instead of memorizing stage order; run several tickets in
parallel clones with `fs`/`flow ls`; see what's installed with `flow agents`
(including the on-disk hint for a not-on-PATH GUI install); and pin, override,
or extend agents per role in `[agents.*]`/`[roles]` without touching flow.py.
