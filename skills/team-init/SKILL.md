---
name: team-init
description: One-time project onboarding for the leader - read the repo and docs, interview the owner (goal, users, stack, quality bar, constraints), fill the board's vision/roadmap/conventions, set build/test/lint commands, create the first specified tasks, verify the usage gate works, and arm the 30-minute heartbeat. Run at the first session or when the vision changes substantially.
---

# Team init (leader, interactive — the owner is present)

`L` = `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as leader`. Use AskUserQuestion freely here; the owner is in the room.

1. **Read before asking.** Skim `README.md`, `docs/`, manifests (`go.mod`, `package.json`, …), CI config, `git log --oneline | head -30`.
   Note what is already decided (stack, architecture) and what is missing. Existing design docs are the starting point, not a blank page.
2. **Interview** (ask in small batches of ≤ 4 questions, each with your recommendation first): product goal and target users; what
   "stable / good enough to ship" means; non-goals; hard constraints (budget, timeline, hosting, compliance, team skills);
   stack decisions that are still open — for each use `leader-planning` §B (options, trade-offs, your recommendation; the owner decides).
3. **Write the board** (`.team/README.md`, edit directly): §1 vision and quality bar, §2 roadmap with milestone **M0** (foundation:
   repo layout, CI, lint/test tooling, branch protection) and **M1** (first usable slice) fully specified and M2+ as "Next/Later",
   §4 decisions so far, §5 real build/test/lint commands.
4. **Config**: set `project_name`, `main_branch`, `integration_branch`, and `commands.build|test|lint` in `.team/config.json` (Edit tool; the guard allows `.team/**`).
   Ensure `.gitignore` contains `.team/worktrees/`, `.team/state/`, `.claude/settings.local.json`.
5. **Epics, PRDs, tasks** (`leader-planning` §C0): split M0–M1 into epics (one user-visible capability each). For each epic write
   `.team/epics/<slug>/PRD.md` from `leader-planning/prd-template.md` and show the owner a short summary of each before dispatching.
   Then create 6–10 tasks via `L add-task --epic <slug>` using `leader-planning/task-template.md` (real acceptance criteria citing the
   PRD's R-ids, diagrams where they remove ambiguity, dependencies only when truly needed). Put later work in `BACKLOG`.
   The README keeps the vision, roadmap (naming the epics under each milestone) and decisions — not the PRDs or task bodies.
6. **Verify the machinery**:
   - `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/usage_gate.py --json` — if it says "usage unknown", the statusLine cache is not filling yet: it needs a
     Claude Pro/Max login, a trusted workspace, and one API response after the session starts. Tell the owner what to check
     (see docs/team-system.md §Troubleshooting); do not lower thresholds or switch `on_unknown` to `go` without their explicit say-so.
   - `L summary` works; `git remote -v` shows `origin`; `gh auth status` or the GitHub MCP tools are available for PRs.
   - Ensure the integration branch exists (`git ls-remote --heads origin develop`; if missing, `git branch develop origin/main && git push -u origin develop`).
   - Recommend (don't do) GitHub branch protection on `main` **and** `develop`: required CI checks, no force-push, PRs required on `main`.
7. **Commit** `.team/` and `.gitignore` with `chore(team): initialise board`, push, then arm the heartbeat
   (`CronCreate`, cron `7,37 * * * *`, prompt `/team-tick`) and record `armed_at` in `.team/state/heartbeat.json`.
8. **Brief the owner** (≤ 10 lines): vision as you understood it, milestone plan, the first tasks the team will pick up, decisions still
   waiting on them, and how to watch progress (`.team/README.md`, `bin/team status`).
