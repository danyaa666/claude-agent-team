---
name: qa-workflow
description: Procedure for the QA agent's wake-up - usage gate, pick READY_FOR_QA tasks, verify against acceptance criteria in the task worktree (build, full tests, exploratory, edge and security checks), add missing tests, then record QA_PASS or QA_FAIL with reproducible notes. Preloaded into the qa agent.
user-invocable: false
---

# QA wake-up procedure

Commands run from the **main checkout root**. `B` means `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as qa`.
Never `cd` elsewhere: use `git -C <worktree>` and `(cd <worktree> && cmd)` subshells.

## Step 0 — usage gate (first, always)
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/usage_gate.py
```
`SLEEP ...` → `B lease release qa`, answer `SLEEP: <reason>`, **stop**. `GO ...` → continue (re-check before a second task).

## Step 1 — find work
`B next` → `CAPACITY n` and tasks in `READY_FOR_QA`, oldest first. `NONE` → release the lease, answer "nothing to test", stop.
At most 2 tasks per wake-up (`claim` enforces it).

## Step 2 — for each task
1. **Claim**: `B claim T-xxx` (READY_FOR_QA → IN_QA).
2. **Understand the contract**: `B get T-xxx` — description, acceptance criteria (AC), design, test plan, dev's notes and earlier QA notes.
   If it starts with an `EPIC <slug> — PRD: <path>` line, read the PRD too: its goals, non-goals and edge-case list are what to probe
   beyond the AC (read-only; never edit it).
3. **Get the code**: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/worktree.py ensure T-xxx` prints the worktree path; then
   `git -C <wt> pull --ff-only` (branch must equal the PR head). Also check the PR's CI status (`gh pr checks` or GitHub MCP
   `pull_request_read`). Red CI on the PR head is an automatic `QA_FAIL`.
4. **Mechanical checks** (commands from README §5 / `.team/config.json`): build, full test suite, lint/format — `(cd <wt> && <cmd>)`.
   Run flaky-looking failures up to 2 more times; a test that passes only sometimes is a finding, not a pass.
   **New or changed HTTP endpoint**: the epic's `postman/<epic>.postman_collection.json` must exist and cover it (full flow +
   an edge-case entry for this change) per `dev-workflow/postman-collections.md` — missing or stale is a finding, same as a
   missing unit test. Run it twice back to back (`newman run postman/<epic>.postman_collection.json -e ...`, or the Postman
   app if `newman` isn't wired up) — the second run failing on a uniqueness conflict means the auto-variable is scoped wrong
   (should be a folder-level pre-request script, not a one-off literal).
5. **Acceptance testing** — build a short test-case table yourself, then execute it:
   - every AC, happy path; - boundaries and invalid input; - error handling and failure modes;
   - security basics relevant to the change (authn/authz, injection, secrets in logs, unsafe defaults);
   - regression in neighbouring features; - performance sanity if a hot path or query changed;
   - if the change has runtime behaviour, start it and exercise it for real (HTTP call, CLI run, UI flow), don't only read code.
6. **Add missing tests** (test files only — a hook blocks anything else): commit on the task branch
   (`git -C <wt> add <files> && git -C <wt> commit -m "test(T-xxx): ..."`, `git -C <wt> push`).
7. **Verdict** — only via the board:
   - **Pass** (every AC has evidence you produced): `B status T-xxx QA_PASS --note "<evidence table: AC → how verified → result; commands run; non-blocking observations>"`.
   - **Fail**: `B status T-xxx QA_FAIL --note "<numbered issues>"`. Each issue: severity (blocker/major/minor), exact steps to reproduce,
     expected vs actual, suspected area. Dev must be able to fix it without asking you anything. Minor polish that doesn't violate an AC
     goes in the pass note as non-blocking, not as a fail.

## Step 3 — finish
`B lease release qa`. Final answer, ≤ 8 lines: tasks tested, verdicts, top issues.

## Hard rules
- Verify, don't fix product code. Don't merge. Don't push `main` or `develop`. Don't edit `.team/README.md` by hand.
- No evidence, no pass. "Looks fine" is not evidence; a command and its result is.
- If a hook denies something, read the message and adapt; never work around it.
