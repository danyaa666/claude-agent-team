# Claude Agent Team

A Claude Code **plugin**: a leader (Opus, xhigh effort) plans, specifies, and reviews; a dev
and a QA (Sonnet, high effort) implement and test. They wake on a 30-minute heartbeat, work
only while your plan usage is under budget, and coordinate through one file in your repo:
`.team/README.md`. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design, the usage gate,
and troubleshooting.

## Install (once per machine)

```bash
claude plugin marketplace add danyaa666/claude-agent-team
claude plugin install agent-team@claude-agent-team
```

Or from a local clone (e.g. to hack on it): `git clone https://github.com/danyaa666/claude-agent-team.git`
then `claude plugin marketplace add ./claude-agent-team` and the same `install` line.

This repo is itself a single-plugin marketplace (`.claude-plugin/marketplace.json`, named
`claude-agent-team`), so no separate marketplace repo is needed. The name after `@` is that
marketplace `name`, not your clone's folder name — it's `claude-agent-team` wherever you put the
clone. Run `claude plugin marketplace list` if you're unsure what's registered.

Verify:

```bash
claude plugin list             # agent-team@claude-agent-team  ...  Status: enabled
claude plugin details agent-team
```

To update after pulling new commits: `claude plugin marketplace update claude-agent-team &&
claude plugin update agent-team`, then restart your session.

`Status: enabled`, `scope: user` means it's now available in **every** project on this
machine — installing once covers all your repos.

## Set up a project to use it

Two things the plugin *cannot* configure for you (Claude Code only lets a plugin's own
`settings.json` set the default `agent` — not `statusLine`, not `permissions`), so add these
once to that project's own `.claude/settings.json`:

```jsonc
{
  "statusLine": {
    "type": "command",
    "command": "bash -c 'exec python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/statusline.py\"'",
    "refreshInterval": 60
  },
  "permissions": {
    "allow": [
      "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)",
      "Bash(git fetch*)", "Bash(git add*)", "Bash(git commit*)", "Bash(git push*)",
      "Bash(git pull --ff-only*)", "Bash(git switch*)", "Bash(git branch*)",
      "Bash(git worktree*)", "Bash(git -C *)",
      "Bash(go build*)", "Bash(go test*)", "Bash(go vet*)", "Bash(gofmt*)", "Bash(make *)",
      "Bash(gh *)",
      "mcp__github__pull_request_read", "mcp__github__list_pull_requests",
      "mcp__github__create_pull_request", "mcp__github__merge_pull_request",
      "mcp__github__update_pull_request_branch", "mcp__github__add_issue_comment",
      "mcp__github__get_file_contents", "mcp__github__get_job_logs",
      "mcp__github__actions_get", "mcp__github__actions_list",
      "CronCreate", "CronList", "CronDelete"
    ],
    "deny": [
      "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git reset --hard origin*)",
      "Bash(rm -rf /*)", "Read(./.env)", "Read(./.env.*)"
    ]
  }
}
```

Swap the `go build`/`go test`/`gofmt` entries for your actual stack (`npm test`, `pytest`, …).

That list intentionally **excludes** `board.py`/`usage_gate.py`/`worktree.py` invocations:
those run from `${CLAUDE_PLUGIN_ROOT}/scripts/...`, which resolves to a real, *versioned*
install path (e.g. `~/.claude/plugins/cache/<marketplace>/agent-team/0.1.0/scripts/board.py`)
that changes on every plugin update — a rule hardcoded against today's path silently stops
matching after the next `claude plugin update`. Don't guess a wildcard for it: the first time
the leader/dev/qa runs one of those commands you'll get a normal permission prompt showing the
exact resolved command — choose **Always allow**, which is the one place Claude Code itself
gets this pattern right, and it'll keep working across updates.

Then, from inside that project:

```bash
claude   # first time: accept the folder-trust prompt
```

The leader agent activates automatically (the plugin's own `settings.json` sets that part) and,
on a fresh `.team/README.md`, runs `/team-init`: it reads your repo, interviews you, fills the
board, sets build/test/lint commands, creates the first tasks, and arms the 30-minute heartbeat.

Convenience launcher (optional): put this repo's `bin/` on your `PATH`, then use `team start`,
`team status`, `team answer Q-001 "…"`, `team accept T-007`, etc. from any project — see
`bin/team`'s header comment for the full command list, or [ARCHITECTURE.md](ARCHITECTURE.md)
§3 for the guided walkthrough.

## Developing this plugin itself

```bash
python3 -m unittest discover -s scripts/tests -v   # 34 tests
claude plugin validate .                            # schema check
```

To try a change before committing: `claude --plugin-dir .` in any project loads this working
copy directly (no marketplace/install step, no reload needed between edits to skills/agents —
only script changes need a fresh session). `/reload-plugins` picks up edits to an *installed*
copy without restarting.

## What's actually different from a vendored copy

This used to be copied straight into a project's `.claude/` (the pattern this plugin's history
came from — see `ARCHITECTURE.md` for the full rationale of every design choice). As a plugin
it installs once and applies everywhere, but two things a plugin genuinely cannot export
(statusLine, permissions) need the one-time per-project step above — that's a Claude Code
plugin limitation, not something this package left unfinished.
