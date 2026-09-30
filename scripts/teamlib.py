"""Shared helpers for the team scripts (stdlib only)."""
import copy
import datetime as dt
import json
import os
import subprocess

DEFAULT_CONFIG = {
    "project_name": "",
    "main_branch": "main",            # production branch: only the owner promotes into it
    "integration_branch": "develop",  # PR target; agents merge here
    "heartbeat_minutes": 30,
    "autostart_heartbeat": True,
    "merge_method": "squash",
    "limits": {"weekly_max_pct": 75, "session_max_pct": 60},
    "usage": {"max_cache_age_sec": 300, "on_unknown": "sleep"},
    "dev": {"wip_limit": 2, "tasks_per_wake": 2, "lease_ttl_min": 90},
    "qa": {"tasks_per_wake": 2, "lease_ttl_min": 60},
    "leader": {
        "reviews_per_tick": 3,
        "min_ready_tasks": 4,
        "stale_after_min": 120,
        "max_rework": 2,
        "digest_every_hours": 24,
        "write_globs": [".team/**", "docs/**", "CLAUDE.md", "README.md", ".gitignore"],
    },
    "commands": {"build": "", "test": "", "lint": ""},
    "guard": {
        "strict_main_session_is_leader": False,
        "qa_write_globs": [
            "**/*_test.go", "**/*.test.*", "**/*.spec.*", "**/test/**", "**/tests/**",
            "**/__tests__/**", "**/e2e/**", "**/test_*.py", "**/*_test.py",
        ],
    },
}


def repo_root(start=None):
    """Main checkout root, even when called from inside a linked worktree."""
    override = os.environ.get("TEAM_ROOT")
    if override:
        return os.path.realpath(override)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=start or os.getcwd(), capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            gd = os.path.realpath(out.stdout.strip())
            return os.path.dirname(gd) if os.path.basename(gd) == ".git" else gd
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.realpath(start or os.getcwd())


def team_dir(root=None):
    return os.path.join(root or repo_root(), ".team")


def state_dir(root=None):
    path = os.path.join(team_dir(root), "state")
    os.makedirs(path, exist_ok=True)
    return path


def _merge(base, extra):
    for key, val in (extra or {}).items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _merge(base[key], val)
        else:
            base[key] = val
    return base


def load_config(root=None):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    path = os.path.join(team_dir(root), "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            _merge(cfg, json.load(fh))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:  # corrupt config must not crash hooks
        cfg["_config_error"] = str(exc)
    return cfg


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def stamp(when=None):
    return (when or utcnow()).strftime("%Y-%m-%d %H:%M") + "Z"


def iso(when=None):
    return (when or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def write_atomic(path, text):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
