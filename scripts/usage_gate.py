#!/usr/bin/env python3
"""Usage gate: decide whether the team may work right now.

    usage_gate.py [--wait-fresh] [--json] [--cache PATH]

Prints `GO ...` (exit 0) or `SLEEP reason=...` (exit 10).

Data source: Claude Code's statusLine JSON (`rate_limits.five_hour / seven_day
.used_percentage`), cached by statusline.py. Thresholds live in .team/config.json:
    limits.weekly_max_pct (default 75)   limits.session_max_pct (default 60)
Both are strict: a window AT the limit sleeps. Unknown/stale data sleeps too
(`usage.on_unknown: "sleep"`), because guessing "GO" is how a plan gets burned.

--wait-fresh: the statusline only learns new numbers when an API response
arrives, so right after a wake-up the cache may still describe the previous turn.
With this flag the gate waits (<= 10 s) for the cache to advance past the value
it saw on the previous --wait-fresh run, then decides either way.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teamlib as tl  # noqa: E402

SLEEP_EXIT = 10


def default_cache():
    return os.environ.get("TEAM_USAGE_CACHE") or os.path.join(os.path.expanduser("~"), ".claude", "team-usage.json")


def read_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def window_pct(win, now):
    """Return (pct, resets_at) or (None, None). A window whose reset time passed is 0%."""
    if not isinstance(win, dict) or win.get("used_percentage") is None:
        return None, None
    resets = win.get("resets_at")
    if resets is not None and float(resets) <= now:
        return 0.0, None
    return float(win["used_percentage"]), resets


def human_delta(seconds):
    seconds = max(0, int(seconds))
    return "%dh%02dm" % (seconds // 3600, seconds % 3600 // 60)


def evaluate(cfg, cache, now):
    lim, use = cfg["limits"], cfg["usage"]
    verdict = {"decision": "SLEEP", "five_hour": None, "seven_day": None, "reason": "", "resets_in": None}

    def unknown(why):
        verdict["reason"] = "usage unknown: " + why
        if use.get("on_unknown") == "go":
            verdict["decision"] = "GO"
        return verdict

    if not cache:
        return unknown("no cache yet (is the statusLine configured and trusted? needs a Pro/Max login)")
    age = now - float(cache.get("written_at", 0))
    if age > use["max_cache_age_sec"]:
        return unknown("cache is %ds old, max %ds (statusline not running?)" % (age, use["max_cache_age_sec"]))
    five, five_reset = window_pct(cache.get("five_hour"), now)
    seven, seven_reset = window_pct(cache.get("seven_day"), now)
    verdict["five_hour"], verdict["seven_day"] = five, seven
    if five is None or seven is None:
        return unknown("rate_limits missing from statusline data (API-key login or no response yet)")
    reasons = []
    if seven >= lim["weekly_max_pct"]:
        reasons.append("seven_day %.1f%% >= %s%%" % (seven, lim["weekly_max_pct"]))
        if seven_reset:
            verdict["resets_in"] = human_delta(seven_reset - now)
    if five >= lim["session_max_pct"]:
        reasons.append("five_hour %.1f%% >= %s%%" % (five, lim["session_max_pct"]))
        if five_reset and verdict["resets_in"] is None:
            verdict["resets_in"] = human_delta(five_reset - now)
    if reasons:
        verdict["reason"] = "; ".join(reasons)
        return verdict
    verdict["decision"] = "GO"
    return verdict


def wait_for_fresh(path, state_path, deadline_s=10):
    prev = read_cache(state_path) or {}
    last_seen = prev.get("api_ms")
    end = time.time() + deadline_s
    cache = read_cache(path)
    while cache and cache.get("api_ms") == last_seen and last_seen is not None and time.time() < end:
        time.sleep(0.5)
        cache = read_cache(path)
    fresh = not (cache and last_seen is not None and cache.get("api_ms") == last_seen)
    if cache:
        tl.write_atomic(state_path, json.dumps({"api_ms": cache.get("api_ms")}))
    return cache, fresh


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wait-fresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cache", default=default_cache())
    args = ap.parse_args(argv)
    cfg = tl.load_config()
    fresh = True
    if args.wait_fresh:
        cache, fresh = wait_for_fresh(args.cache, os.path.join(tl.state_dir(), "gate-state.json"))
    else:
        cache = read_cache(args.cache)
    v = evaluate(cfg, cache, time.time())
    v["fresh"] = fresh
    if args.json:
        print(json.dumps(v))
    else:
        parts = [v["decision"]]
        if v["five_hour"] is not None:
            parts.append("five_hour=%.1f%%(<%s)" % (v["five_hour"], cfg["limits"]["session_max_pct"]))
        if v["seven_day"] is not None:
            parts.append("seven_day=%.1f%%(<%s)" % (v["seven_day"], cfg["limits"]["weekly_max_pct"]))
        if v["reason"]:
            parts.append("reason=" + v["reason"])
        if v["resets_in"]:
            parts.append("window_resets_in=" + v["resets_in"])
        if not fresh:
            parts.append("note=no new API response seen since last check; numbers may lag")
        print(" ".join(parts))
    return 0 if v["decision"] == "GO" else SLEEP_EXIT


if __name__ == "__main__":
    sys.exit(main())
