#!/usr/bin/env python3
"""Claude Code statusLine command: caches plan usage for usage_gate.py and prints a status line.

Claude Code pipes JSON to this script on stdin (see the statusLine docs). We store
`rate_limits` (five_hour / seven_day used_percentage + resets_at) in
~/.claude/team-usage.json (override: TEAM_USAGE_CACHE). The file is account-level,
so every project that uses this script shares one fresh reading.

Nothing is written when `rate_limits` is absent (API-key login, or before the first
API response) — a stale cache must age out so the gate fails closed.

Optional chaining: set TEAM_STATUSLINE_CHAIN (env) to another statusLine command; the
same JSON is piped to it and its output is shown instead of ours.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teamlib as tl  # noqa: E402


def cache_path():
    return os.environ.get("TEAM_USAGE_CACHE") or os.path.join(os.path.expanduser("~"), ".claude", "team-usage.json")


def pick(win):
    if isinstance(win, dict) and win.get("used_percentage") is not None:
        return {"used_percentage": float(win["used_percentage"]), "resets_at": win.get("resets_at")}
    return None


def update_cache(data, path=None):
    limits = data.get("rate_limits") or {}
    five, seven = pick(limits.get("five_hour")), pick(limits.get("seven_day"))
    if five is None and seven is None:
        return False
    record = {
        "written_at": time.time(),
        "five_hour": five,
        "seven_day": seven,
        "api_ms": (data.get("cost") or {}).get("total_api_duration_ms"),
        "session_id": data.get("session_id"),
    }
    path = path or cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tl.write_atomic(path, json.dumps(record))
    return True


def line(data):
    model = (data.get("model") or {}).get("display_name", "?")
    limits = data.get("rate_limits") or {}
    bits = ["[%s]" % model]
    for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
        win = pick(limits.get(key))
        bits.append("%s %s" % (label, "%.0f%%" % win["used_percentage"] if win else "n/a"))
    ctx = (data.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        bits.append("ctx %s%%" % int(ctx))
    role = os.environ.get("TEAM_ROLE")
    return ("team:%s " % role if role else "") + " · ".join(bits)


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        data = {}
    try:
        update_cache(data)
    except OSError:
        pass  # never break the status line over a cache write
    chain = os.environ.get("TEAM_STATUSLINE_CHAIN")
    if chain:
        try:
            out = subprocess.run(chain, shell=True, input=raw, capture_output=True, text=True, timeout=5)
            if out.stdout.strip():
                print(out.stdout.rstrip("\n"))
                return 0
        except (OSError, subprocess.SubprocessError):
            pass
    print(line(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
