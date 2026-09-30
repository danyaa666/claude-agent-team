# Team Board

> **Source of truth for the leader / dev / QA team.**
> **Leader** writes everything here. **Dev and QA** may only change a task's status and add comments (through `board.py`). **You** answer the questions in §3 — edit the `Answer` line in place or just tell the leader.
> Status flow: `BACKLOG → TODO → IN_PROGRESS → READY_FOR_QA → IN_QA → QA_PASS | QA_FAIL → (leader review) → MERGED → DONE`.
> `MERGED` = merged to `develop` and **waiting for your review**; tell the leader "accept T-007" (or `bin/team accept T-007`) to make it `DONE`.

## 0. At a glance

<!-- summary:start -->
| Status | # | Tasks |
|---|---:|---|
| _no tasks yet_ | 0 | |

**Awaiting your review (MERGED):** nothing

**Open questions for you:** none
<!-- summary:end -->

## 1. Vision & orientation

_(leader fills this in during `/team-init`: product goal, target users, non-goals, quality bar, what "stable" means for this project.)_

## 2. Roadmap

_(leader maintains three horizons — **Now** (current milestone, fully specified), **Next** (sketched, tasks in BACKLOG), **Later** (direction only). When the current version is stable the leader proposes the next milestone here.)_

| Horizon | Milestone | Goal | Exit criteria ("stable") | Status |
|---|---|---|---|---|
| Now | M0 | _(set at team-init)_ | | planned |

## 3. Questions & decisions for you

<!-- questions:start -->

<!-- questions:end -->

## 4. Architecture & decision log

_(tech-stack choices with the options considered and why; links to `docs/`.)_

## 5. Engineering conventions

- Build: _(set at team-init; mirrored in `.team/config.json` → `commands`)_
- Test: _(…)_
- Lint / format: _(…)_
- Branches: `task/t-<id>-<slug>`, one per task, PR to `develop`, squash-merged by the leader; you promote `develop` → `main` with `bin/team promote`.
- Definition of done: acceptance criteria met, tests written and green, build + lint green, PR open, QA_PASS, leader review passed.

## 6. Tasks

Task block anatomy (leader-written; dev/qa touch only `Status`, `Branch`, `PR`, and the Comments list):

```text
### T-007 — Short imperative title
- **Status:** TODO
- **Priority:** P1            (P0 urgent … P3 nice-to-have)
- **Type:** feature | bug | tech-debt | security | perf | docs | infra
- **Milestone:** M1
- **Depends-on:** T-003, T-004
- **Assignee:** —            (maintained automatically)
- **Branch:** —   **PR:** —
#### Description / Acceptance criteria / Design (mermaid) / Test plan
#### Comments                (one line per comment: timestamp · role · text)
```

<!-- tasks:start -->

<!-- tasks:end -->

## 7. Change log

_(leader appends one line per merge or major decision.)_
