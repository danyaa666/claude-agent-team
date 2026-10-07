# Leader cycle (runs only after the usage gate said GO and the tick lease is held)

`L` = `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as leader`. Stay in the main checkout. Be terse — this runs every 30 minutes.
**Never use AskUserQuestion here** (the owner may be away; it would freeze the loop). Questions go to the board.

## 1. Orient
`L summary` — queue sizes, leases, stale work, unread comments, open questions, pipeline size.
`git fetch origin --prune`. If the main checkout has uncommitted changes outside `.team/` (the README, `epics/`, `digests/`), note it and leave them alone.

## 2. Owner input
`L questions`: for each `ANSWERED` question — record the decision in README §4 (date, choice, rationale), move the dependent
tasks `NEEDS_DECISION → TODO` (or `BACKLOG`), adjust specs if the answer changes them, then `L resolve Q-xxx`.
For a task in `MERGED`, the owner accepts by telling you (or `bin/team accept T-xxx`); nothing to do until then.

## 3. Team comments
`L unread`. For every comment decide and act:
- **Blocker/question from dev or QA** → answer with a comment (`L comment T-xxx "..."`), sharpen the task description, create a
  prerequisite task, or raise a decision (`L ask`, see `leader-planning` §B). Unblock with `L status T-xxx TODO`.
- **Suggestion / out-of-scope finding** → accept (new task, often P3/P2), or decline with a one-line reason.
Then `L ack T-xxx ...`.

## 4. Stale work
`summary` lists `STALE` tasks (IN_PROGRESS / IN_QA with no activity beyond `stale_after_min` and no live lease).
Reclaim: `L status T-xxx TODO` (from IN_PROGRESS) or `READY_FOR_QA` (from IN_QA) with a comment; the worktree is reused by the next wake-up.
Repeatedly stalling task → split it or rewrite its spec.

**Parked tasks** (`summary` → `PARKED`: sent back more than `leader.max_rework` times): do not send them to dev again. Find the
root cause in the comment history — vague AC, wrong design, task too big, environment problem — then rewrite the spec, split it
into smaller tasks (cancel the original), or ask the owner; moving it to `TODO`/`BACKLOG` resets its rework budget.

## 5. Review and merge
For each task in `LEADER_REVIEW` (at most `leader.reviews_per_tick`, highest priority first) run the **leader-review** skill.
Tasks listed under `OWNER_APPROVAL` are `Risk: high`: review them, but they wait for `bin/team approve` (see the skill).

## 6. Plan ahead (when `PIPELINE ... LOW`, or the milestone just finished, or roadmap "Next" is thin)
Run **leader-planning** §D–E: stability check → next-milestone sketch → a PRD for each new epic (§C0; a new or changed PRD
goes to the owner as a question before its tasks are dispatched) → new tasks with full specs. Every ~6th tick
(see `.team/state/heartbeat.json` → `last_health_sweep`) also run §F health sweep and update that timestamp.
New product directions not covered by the approved vision go to the owner as a question, not straight into TODO.

## 7. Dispatch (re-check the gate first: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/usage_gate.py` — `SLEEP` ⇒ skip this step)
Both roles can run in parallel; issue both Agent calls in the same message.
1. `L next --for dev` → if it lists work: `L lease acquire dev` (exit 3 = still running, skip), then
   `Agent(subagent_type: "dev", run_in_background: true, prompt: "Wake-up. The dev lease is held for you. Follow your dev-workflow, starting with the usage gate.")`.
2. `L next --for qa` → if it lists work: `L lease acquire qa`, then
   `Agent(subagent_type: "qa", run_in_background: true, prompt: "Wake-up. The qa lease is held for you. Follow your qa-workflow, starting with the usage gate.")`.
Nothing eligible → don't spawn; an idle agent still costs tokens.

## 8. Persist the board
Only the board should be dirty: `.team/README.md`, `.team/epics/` (PRDs and task files), `.team/digests`. `git checkout develop` (the main checkout lives on the integration branch) then `git pull --ff-only origin develop`, then if anything changed:
`git add .team && git commit -m "chore(team): board sync" && git push origin develop`
(`.team/worktrees` and `.team/state` are git-ignored, so this stages only the board files; unlike naming `.team/epics` or
`.team/digests` explicitly, it can't fail on a folder that doesn't exist yet).
(If pushing to `develop` is protected, stop and tell the owner in one line; don't improvise.)
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/worktree.py prune` to remove worktrees of merged/cancelled tasks.

## 9. Heartbeat housekeeping
`CronList` — confirm the `/team-tick` job exists; re-arm per the leader instructions if missing or older than 6 days.
Update `.team/state/heartbeat.json` (`last_tick`, `armed_at`, `last_health_sweep`). Create the file if absent.

## 10. Daily digest
`L digest --due` → if `DUE`: `L digest --write` (saves `.team/digests/<date>.md`, updates `last_digest`), then send its
"Waiting on you" lines as one PushNotification. Skip when `NOT_DUE`.

## 11. Tell the owner only what matters
Use PushNotification (if available) once per tick at most, and only for: a new question that blocks work, tasks newly `MERGED`
awaiting review, a stuck/blocked pipeline, or usage sleeping for more than ~3 hours. Otherwise stay quiet.

## 12. Close
`L lease release tick`. Final reply ≤ 6 lines: merged/sent back, dispatched, blocked, questions for the owner.
