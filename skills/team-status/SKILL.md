---
name: team-status
description: Show the team's current state - plan-usage gate, board summary by status, leases and stale work, and open questions for the owner. Cheap and read-only; the leader runs it at session start and the owner can run it any time.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*)
---

# Team status

## Usage gate (GO = team may work; thresholds in .team/config.json)
!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/usage_gate.py || true`

## Board
!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as leader summary || true`

## Questions waiting on the owner
!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/board.py --as leader questions || true`

Summarise the above for the owner in a few lines. Flag: `SLEEP`/unknown usage, `STALE` work, `LOW` pipeline, tasks in `MERGED`
(need their review), and any `ANSWERED` question you still have to process. If the board command printed "no board" or the
README has no vision yet, say the team has not been initialised and offer to run `/team-init`.
