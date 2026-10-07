---
name: leader-planning
description: Leader's planning playbook - intake of requirements, tech-stack decision protocol (recommendation plus alternatives, owner decides), writing dev-ready tasks with diagrams, milestones and roadmap horizons, stability check and next-milestone sketch, and periodic health sweeps (security, performance, reliability, dependencies, docs). Use whenever you plan, specify, or look ahead.
---

# Leader planning playbook

`L` = `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as leader`. Templates live next to this file:
`prd-template.md` (an epic's PRD), `task-template.md` (task body), `decision-record.md` (owner decisions),
`health-checklist.md` (sweeps).

## A. Intake — turn a request into a plan
1. Restate the request in your words: goal, user, why now. List assumptions and open questions; ask the owner only what changes the plan.
2. Check it against the vision (README §1) and roadmap (§2). Conflicts, hidden costs, security/privacy implications → say so plainly.
3. Write or update: vision, milestone goal with **exit criteria** ("stable" = measurable), then the **epics and their PRDs** (§C0), then
   tasks (§C). Note what you deliberately left out.
4. Tell the owner the plan in ≤ 10 lines: milestone, task count, biggest risks, decisions you need.

## B. Tech-stack and other owner decisions
Never pick these alone: language/framework, database, hosting/cloud, auth, major libraries, paid services, data-retention/privacy
trade-offs, breaking public changes, new product directions. Protocol:
1. Fill `decision-record.md`: context/constraints, 2–4 real options (pros, cons, cost, risk, lock-in, team fit), **your recommendation and why**,
   what happens if undecided, how reversible it is.
2. Owner present → `AskUserQuestion`, recommended option first, with the trade-off in each option's description.
   Owner away (heartbeat) → `L ask --title "..." --blocks T-xxx,T-yyy --recommendation "<option>" --body-file <record>` and
   `L status T-xxx NEEDS_DECISION` on the dependent tasks; keep everything unblocked moving; send one PushNotification.
3. On the answer: record it in README §4 (date, choice, rationale, rejected options), update `.team/config.json` → `commands` if build/test
   commands changed, unblock tasks, `L resolve Q-xxx`.

## C0. Epics and PRDs — keep the README an index, not a dump
The README holds what is true of the whole project: vision, roadmap, decisions, conventions, the owner's questions, the change log.
Requirements and tasks live **per epic**, under `.team/epics/<slug>/`:
```
.team/epics/<slug>/PRD.md      what and why (use prd-template.md) — you write it
.team/epics/<slug>/tasks.md    the task blocks (spec + status + comments) — created by `L add-task --epic <slug>`
```
- **An epic is one user-visible capability** (`auth`, `lessons`, `hsk-mock-exam`, `admin-content`), typically 3–12 tasks. Too small
  (one task) → just a task; too big (a whole product area, 20+ tasks) → split it. Slug: lowercase letters, digits, `-`.
- **Epic vs. milestone:** the epic says *what capability*; the milestone says *when / which stable slice*. A milestone usually cuts
  across several epics (M1 = the thinnest slice of `auth` + `lessons` + `tests`), so both are on every task (`--epic`, `--milestone`).
- **PRD first, then tasks.** Write the PRD (problem, goals/metrics, non-goals, flow, **numbered requirements**, edge cases, open
  questions), then derive the tasks. Every *Must* requirement maps to at least one task; each task's acceptance criteria cite the
  R-ids they satisfy. Owner decisions the PRD depends on go on the board (`L ask`), listed by id under the PRD's open questions.
- **Owner approval:** a new or materially changed PRD is a product decision — show it to the owner (a short summary plus the path)
  before dispatching its tasks, same as any other scope call; mark `Status: approved by owner` once they agree.
- `L epics` lists every epic with its task counts and whether its PRD exists; `L set T-xx epic=<slug>` moves a task into an epic
  (`epic=-` moves it back to the README's unfiled region, where tasks created without `--epic` live — fine for one-offs and bugs).
- Dev and QA read the PRD for context (`B get T-xx` prints its path); they never edit it.
- The epic slug is also the name of that epic's Postman collection (`postman/<slug>.postman_collection.json`).

## C. Writing a task dev can execute without asking
Use `task-template.md`. Create: `L add-task --epic auth --title "..." --priority P1 --type feature --milestone M1 --depends "T-003" --body-file /tmp/body.md`
(or `--body "..."`; omit `--epic` only for a one-off or a bug). The first task of a new epic creates its `tasks.md` and a PRD stub — replace
the stub with the real PRD before dispatching. Rules:
- **Sized for one dev wake-up** (roughly ≤ ½ day of work, ≤ ~400 changed lines, one PR, one concern). Bigger → split by vertical slice.
- **Acceptance criteria are testable statements** ("returns 404 with error code X for an unknown id"), 3–8 of them.
- **Design**: include the diagram that removes ambiguity — mermaid `sequenceDiagram` for interactions, `stateDiagram-v2` for lifecycles,
  `erDiagram`/table for data, a short API contract (method, path, request, response, errors) where relevant. Name the files/modules to touch.
- **Test plan**: what dev must test (unit/integration) and what QA should probe (edge cases, security, performance).
- **Dependencies**: `Depends-on` only for true ordering constraints; a dependency blocks dev until that task is MERGED.
- Mention explicitly what is **out of scope** to stop scope creep, and the security/perf considerations that apply.
- **Risk**: set `--risk high` for anything touching authentication/authorisation, personal or payment data, schema migrations,
  public API/contract changes, infra/CI/secrets, or a significant new dependency. High-risk tasks are reviewed by you as usual but
  cannot merge until the owner runs `bin/team approve`. Everything else is `low` and merges on your review.
- **Rework budget**: a task may go back to dev at most `leader.max_rework` times (default 2). A third failure parks it; then rewrite
  or split it (usually the AC were vague or the task too large) instead of resending it.
- Prefer many small independent tasks over a chain; the dev takes at most 2 per wake-up and QA runs in parallel.

## D. Milestones and horizons (README §2)
- **Now**: current milestone, fully specified tasks in TODO/IN_*.  **Next**: next milestone sketched, tasks in BACKLOG with one-line intents.
  **Later**: directions only. Keep `min_ready_tasks` tasks ready so dev/QA never idle.
- Promote BACKLOG → TODO (`L status T-xxx TODO`) only after the spec meets §C.
- Re-prioritise every tick from evidence: P0 = broken main/security/data loss, P1 = milestone critical path, P2 = planned, P3 = nice.

## E. Stability check → next milestone ("the project always moves forward")
The current version is **stable** when all hold: every milestone task is MERGED/DONE or cancelled with reason; CI on `develop` green;
no open P0/P1 bugs; QA smoke of the main user journeys passes; the health checklist shows no open high-severity item;
README §1 quality bar met. When stable:
1. Write a **milestone retrospective** line in §7 (what shipped, what broke, what to improve).
2. Sketch the next milestone, weighing: (a) the owner's stated direction/vision, (b) user-visible features that extend what exists,
   (c) tech-debt and reliability items found in reviews, (d) security hardening, (e) performance/server-cost optimisation,
   (f) observability and operability, (g) docs/DX, (h) dependency and platform upgrades.
3. Create specified tasks for what clearly follows the approved vision (low risk: tech-debt, security, perf, tests, docs, next-slice features).
   Ideas that change product direction or cost → owner question (`L ask`) plus a BACKLOG entry marked `PROPOSED`.
4. Update the roadmap table, and tell the owner in ≤ 8 lines what you plan next and why.
Never let the pipeline empty: if you have no good feature work, there is always health work (§F).

## F. Health sweeps (about every 3 hours of ticks, or after each milestone)
Go through `health-checklist.md`; inspect the repo and CI (`git log`, dependency manifests, CI results, TODO/FIXME counts, test
coverage output if available). Each real finding becomes a task (type `security`, `perf`, `tech-debt`, `infra`, `docs`) with
priority by impact; record the sweep date in `.team/state/heartbeat.json`. Report only high-severity items to the owner.
