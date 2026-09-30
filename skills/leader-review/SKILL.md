---
name: leader-review
description: Leader's final review of a task that reached QA_PASS - verify the PR against the spec, security and performance, then merge into the integration branch (develop) and mark MERGED (awaiting owner review) or send it back as CHANGES_REQUESTED. Use for each QA_PASS task during the heartbeat.
---

# Leader review of a QA_PASS task

`L` = `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as leader`. Arguments: a task id (`$ARGUMENTS`), or review every `QA_PASS` task.
You review, you don't patch. Anything that needs a code change goes back to dev.

## 1. Gather
- `L get T-xxx` — spec, AC, design, test plan, dev notes, QA evidence.
- The PR: `gh pr view <pr> --json mergeable,statusCheckRollup,headRefOid` and `gh pr diff <pr>`, or GitHub MCP `pull_request_read`
  (details, diff, checks, mergeability). Also `git fetch origin` so you can read files at the PR head if the diff is unclear.
- Did the PR head change after QA passed? Compare `headRefOid` with the commit QA recorded in its note. New commits since
  QA ⇒ `L status T-xxx READY_FOR_QA --note "new commits after QA; re-test"` and stop.

## 2. Judge (write a short list of findings; blocking vs non-blocking)
1. **Spec**: every AC satisfied by the diff, not just by the tests? scope creep? design followed (or deviation justified)?
2. **Correctness & edge cases**: error paths, concurrency, idempotency, migrations reversible, backwards compatibility.
3. **Security**: input validation, authn/authz on every new entry point, injection, secrets/PII in code or logs, new dependencies
   (licence, maintenance, known CVEs), permissive defaults, CORS/CSRF if web.
4. **Performance & server cost**: query count/indexes, N+1, unbounded lists/loops, payload size, caching, blocking calls on hot paths,
   memory growth. Ask: what happens at 100× the data?
5. **Reliability & ops**: timeouts/retries, graceful failure, logging/metrics where an on-call would need them, config via env.
6. **Tests**: would they catch a regression? meaningful assertions, not only coverage; edge cases present; no skipped/flaky tests.
7. **Maintainability**: naming, duplication, layering, docs/README/ADR updated.
8. CI is green on the PR head and the PR is mergeable. (Behind `develop` but conflict-free and green is fine.)

## 3. Decide
- **Risk: high task** (the board shows `RISK:HIGH` and refuses `MERGED` until the owner approves): finish your review, then post the
  verdict as a comment (`L comment T-xxx "review OK; awaiting owner approval: <what to look at>"`), raise it with the owner
  (`L ask --title "Approve merge of T-xxx?" --blocks T-xxx --recommendation "approve|hold"`, PushNotification), leave it in `QA_PASS`,
  and move on. The owner runs `bin/team approve T-xxx`; only then merge as below. You cannot approve for them.
- **Pass** → merge with the configured method (`merge_method`, default squash): `gh pr merge <pr> --squash --delete-branch`
  or GitHub MCP `merge_pull_request`. Then in the main checkout `git pull --ff-only origin develop`, and
  `L status T-xxx MERGED --note "merged <short-sha>. Review: <1–3 lines>. For owner to check: <what to look at>"`.
  Add one line to README §7 (change log). Non-blocking findings become new P3/P2 tasks (`add-task`), not a reason to hold the merge.
  `MERGED` means "merged and waiting for the owner's review" — never mark `DONE` yourself; the owner accepts.
- **Fail** → `L status T-xxx CHANGES_REQUESTED --note "<numbered blocking issues, each with file:line and what 'fixed' looks like>"`.
  Conflicts with `develop` ⇒ "merge develop into the branch, re-run tests, then READY_FOR_QA". It returns to dev, then QA again.
- Can't judge because of a missing owner decision → `L ask ...` (see leader-planning §B) and `L status T-xxx NEEDS_DECISION`.

## 4. After merging
If the task changed public behaviour, update docs or add a docs task. If it shifted the plan, update the roadmap. If `develop` now
breaks CI, stop merging, create a P0 fix task, and tell the owner.
