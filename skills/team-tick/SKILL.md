---
name: team-tick
description: The team's 30-minute heartbeat. Checks plan usage first (sleeps if over budget), then runs one leader cycle - read comments, review and merge QA_PASS tasks, reclaim stalled work, plan ahead, dispatch dev and QA, sync the board. Fired by the scheduled job /team-tick; safe to run by hand.
---

# Team heartbeat

**Step 0 — usage gate. Do this before anything else; read and plan nothing first.**

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/usage_gate.py --wait-fresh
```

- Output starts with `SLEEP` → reply with exactly one line, `💤 sleeping until next tick — <reason>`, and **stop**.
  Do not read the board, do not plan, do not dispatch.
- Output starts with `GO` → continue.

**Step 1 — no overlapping ticks.**

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as leader lease acquire tick
```

(The tick lease expires by itself after 45 minutes, so an interrupted tick never blocks the heartbeat for long.)

Exit code 3 (a previous tick is still running) → reply `⏳ previous tick still running`, and stop.

**Step 2 — run the cycle.** Read `${CLAUDE_SKILL_DIR}/cycle.md` and execute it top to bottom. Release the tick lease at the end
(`... lease release tick`), even when you stop early.
