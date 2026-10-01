---
name: dev-workflow
description: Procedure for the dev agent's wake-up - usage gate, pick at most 2 board tasks, implement in a per-task git worktree, write tests, build, self-review, open a PR, mark READY_FOR_QA, and fix QA/leader feedback. Preloaded into the dev agent.
user-invocable: false
---

# Dev wake-up procedure

Commands below run from the **main checkout root** (your starting directory). `B` means
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as dev`. Never `cd` elsewhere: use `git -C <worktree>` and `(cd <worktree> && cmd)` subshells.

## Step 0 — usage gate (first, always)
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/usage_gate.py
```
- Starts with `SLEEP` → run `B lease release dev`, answer `SLEEP: <reason>` and **stop**. Touch nothing else.
- Starts with `GO` → continue. Re-run this gate before starting a **second** task.

## Step 1 — find work
```bash
B next
```
Prints `CAPACITY n` and up to n picks; `REWORK` (sent back by QA/leader) comes before new `PICK`s. `NONE` → `B lease release dev`,
answer "no work" and stop. Never take more than 2 tasks in one wake-up — `claim` enforces it.

## Step 2 — for each task
1. **Claim**: `B claim T-xxx` (TODO/QA_FAIL/CHANGES_REQUESTED → IN_PROGRESS).
2. **Read everything**: `B get T-xxx` — description, acceptance criteria (AC), design/diagram, test plan, and **all comments**
   (on rework they list exactly what to fix). Read `.team/README.md` §5 for build/test/lint commands and conventions.
   Unclear or contradictory spec, too big for one wake-up, or needs a new dependency / technology / product decision →
   `B comment T-xxx "<specific question or proposal>"` then `B status T-xxx BLOCKED` and move on. Do not guess.
3. **Worktree**: `WT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/worktree.py ensure T-xxx)` — prints `.team/worktrees/T-xxx`
   (branch `task/t-xxx-slug`, cut from `origin/develop`, the integration branch, or the existing remote branch on rework). Bash variables don't survive
   between calls, so re-run `worktree.py path T-xxx` or use the literal path. Edit files only under that path.
4. **Implement** in small commits (`git -C $WT add -A && git -C $WT commit -m "feat(T-xxx): ..."`). Follow the existing code style and
   architecture; smallest change that satisfies the AC; no drive-by refactors; no secrets, no debug leftovers, no new dependency
   without noting it in the PR. Handle errors and validate inputs at the boundary.
5. **Tests — carefully**: for every AC at least one test that fails without your change; edge cases (empty, max, invalid, concurrent);
   for bugs a regression test written first. **New or changed HTTP endpoint** → also add/update that epic's Postman collection
   (`postman/<epic>.postman_collection.json`) per `postman-collections.md` next to this file: full flow + edge-case folder,
   folder-level pre-request script for any auto-variable a multi-step flow needs to stay consistent across its own requests.
   Then run build, full test suite, lint/format from the project commands (`(cd $WT && <cmd>)`); `newman run postman/...` too if
   it's wired up. Everything green before you continue. Flaky test → fix or report it, never ignore it.
6. **Self-review like a hostile reviewer**: read `git -C $WT diff origin/develop...HEAD` top to bottom. Check AC coverage, security
   (injection, authz, secrets, unsafe deserialisation), performance (N+1, unbounded loops/queries), error paths, naming, docs,
   leftover TODOs. Fix what you find.
7. **Push + PR**: `git -C $WT push -u origin <branch>`; open a PR into `develop` titled `[T-xxx] <title>` with: what/why, AC checklist with
   evidence, how it was tested (commands), risks/migrations. Use `gh pr create` if available, otherwise the GitHub MCP
   `create_pull_request`. On rework the existing PR updates itself with your push — don't open a second one.
8. **Board**: `B set T-xxx branch=<branch> pr=<url-or-#n>` then
   `B status T-xxx READY_FOR_QA --note "<what changed, how to test, known gaps>"`.
   On rework the note maps each QA/leader issue number to the fix and the test that covers it.
   A task comes back to you at most twice; after that the leader re-plans it. Make each round count: fix the root cause, not the symptom.

## Step 3 — finish
`B lease release dev`. Final answer, ≤ 8 lines: tasks, new status, PR links, blockers.

## Hard rules
- Never merge, never push to `main`/`master`/`develop`, never force-push; hooks block these anyway.
- Never edit `.team/README.md` by hand; only `B ...`. Comments are how you talk to the leader and QA — be specific.
- Three failed approaches on the same problem → stop, write down what you tried, set `BLOCKED`.
- If a command is denied by a hook, read its message and adapt; do not look for a way around it.
