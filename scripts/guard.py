#!/usr/bin/env python3
"""PreToolUse hook: seatbelt that keeps each team role inside its lane.

Reads the hook JSON on stdin and exits 2 (with a reason on stderr) to block a call.
$TEAM_ROLE=human always wins, checked before anything else: the human's escape hatch even
when the installed plugin's default agent (or `--agent leader`) makes Claude Code report
`agent_type: "leader"` for the main session too. Otherwise: role = hook `agent_type`
(dev / qa / leader) when present, else $TEAM_ROLE (`bin/team start` sets TEAM_ROLE=leader,
which is what arms the leader restrictions). A plain `claude` session in this repo has no role
and is unrestricted, so maintaining the tooling is never blocked — unless
guard.strict_main_session_is_leader is true, which treats every role-less main session as the leader.

What it enforces
  dev/qa   Edit/Write only inside .team/worktrees/ (qa: test files only);
           board changes only via board.py with `--as <own role>`;
           no push to main/master/develop, no force push, no PR merge, no API file writes.
  leader   Edit/Write only under leader.write_globs (.team/**, docs/**, ...) — it plans and
           reviews, it does not write product code; no force push.
This is a guard-rail against model mistakes, not a security boundary against a hostile
agent (a determined `bash -c` can dodge regexes). Pair it with branch protection on main.
The hook fails OPEN on internal errors so a bug here can never brick the session.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teamlib as tl  # noqa: E402

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
PROTECTED = re.compile(r"\.team/(README\.md|config\.json|state|epics)")
# A real board.py *invocation* (`python3 [flags] [dir/]board.py`, or the script run directly after
# ^ ; & |). A bare mention — `grep x scripts/board.py`, `cat board.py` — is not a call and needs no --as.
BOARD_CALL = re.compile(r"""(?:\bpython3?\s+(?:-\S+\s+)*|(?:^|[;&|]\s*))["']?(?:\S*/)?board\.py\b""")
WRITEY = re.compile(r"(>|\bsed\s+-[a-z]*i|\btee\b|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bdd\b|"
                    r"\bperl\s+-[a-z]*i|\bpython3?\b|\bnode\b|\bruby\b|\bawk\s+-i|\binstall\b|\bgit\s+(checkout|restore|apply))")
MERGE_TOOL = re.compile(r"mcp__.*(merge_pull_request|enable_pr_auto_merge|create_or_update_file|push_files|"
                        r"delete_file|create_branch)")


def glob_match(rel, pattern):
    """fnmatch-style glob where `**/` spans directories and `*` stays within one."""
    rx, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            rx, i = rx + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            rx, i = rx + ".*", i + 2
        elif pattern[i] == "*":
            rx, i = rx + "[^/]*", i + 1
        elif pattern[i] == "?":
            rx, i = rx + "[^/]", i + 1
        else:
            rx, i = rx + re.escape(pattern[i]), i + 1
    return re.fullmatch(rx, rel) is not None


def deny(reason):
    print("team-guard: " + reason, file=sys.stderr)
    sys.exit(2)


def role_of(data, cfg):
    env = os.environ.get("TEAM_ROLE", "")
    if env == "human":
        return None
    agent = data.get("agent_type")
    if agent in ("dev", "qa", "leader"):
        return agent
    if env in ("dev", "qa", "leader"):
        return env
    if agent:  # some other subagent (Explore, Plan...): not ours to police
        return None
    return "leader" if cfg["guard"]["strict_main_session_is_leader"] else None


def rel_to_root(path, root, cwd):
    full = path if os.path.isabs(path) else os.path.join(cwd or root, path)
    return os.path.realpath(full), os.path.realpath(root)


def check_write(role, path, cfg, root, cwd):
    full, root_real = rel_to_root(path, root, cwd)
    rel = os.path.relpath(full, root_real)
    if rel.startswith(".."):
        return  # outside the repo: Claude Code's own permission system decides
    if role == "leader":
        if not any(glob_match(rel, g) for g in cfg["leader"]["write_globs"]):
            deny("leader does not write product code (%s). Put it in a task for dev. "
                 "Leader may write: %s" % (rel, ", ".join(cfg["leader"]["write_globs"])))
        return
    if not rel.startswith(".team/worktrees/"):
        worktree_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worktree.py")
        deny("%s may only edit inside its task worktree (.team/worktrees/<TASK>/), not %s. "
             "Create one with: python3 %s ensure <TASK-ID>" % (role, rel, worktree_py))
    inner = rel.split("/", 3)[-1] if rel.count("/") >= 3 else rel
    if re.search(r"(^|/)\.team/(README\.md|config\.json|state|epics)", inner):
        deny("%s must not edit the board inside a worktree; use board.py" % role)
    if role == "qa":
        if not any(glob_match(inner, g) for g in cfg["guard"]["qa_write_globs"]):
            deny("qa may only add/modify test files (%s is not matched by guard.qa_write_globs). "
                 "Report product-code problems as QA_FAIL instead." % inner)


def check_bash(role, cmd):
    board = BOARD_CALL.search(cmd)
    if board:
        m = re.search(r"--as[ =]+(\w+)", cmd)
        if not m:
            deny("board.py needs --as <role>")
        if m.group(1) != role:
            deny("%s may not call board.py as %r" % (role, m.group(1)))
    elif PROTECTED.search(cmd) and WRITEY.search(cmd) and role != "leader":
        deny("the board/config/state are changed only through board.py (--as %s), not by shell edits" % role)
    if re.search(r"\bgit\s+push\b", cmd):
        if re.search(r"(\s--force(?!-with-lease)\b|\s-f\b|\s\+\S)", cmd):
            deny("force-push is not allowed (use --force-with-lease on your own task branch if you must)")
        if role in ("dev", "qa") and re.search(r"(?<![\w/.-])(main|master|develop)(?![\w/.-])|HEAD:(main|master|develop)", cmd):
            deny("%s never pushes to main/master/develop. Push your task branch and open a PR." % role)
    if role in ("dev", "qa") and re.search(r"\bgh\s+pr\s+(merge|review --approve)|\bgh\s+api\b.*merge", cmd):
        deny("only the leader merges PRs")
    if role in ("dev", "qa") and re.search(r"\bgit\s+(checkout|switch)\s+(main|master|develop)\b", cmd):
        deny("do not switch a checkout to a shared branch; work in your task worktree")


def main():
    try:
        data = json.load(sys.stdin)
        root = tl.repo_root(data.get("cwd"))
        cfg = tl.load_config(root)
        role = role_of(data, cfg)
        if role is None:
            return 0
        tool, tin = data.get("tool_name", ""), data.get("tool_input") or {}
        if tool in WRITE_TOOLS:
            check_write(role, tin.get("file_path") or tin.get("notebook_path") or "", cfg, root, data.get("cwd"))
        elif tool == "Bash":
            check_bash(role, tin.get("command", ""))
        elif role in ("dev", "qa") and MERGE_TOOL.search(tool):
            deny("%s may not use %s (merging/writing to GitHub is leader-only)" % (role, tool))
    except SystemExit:
        raise
    except Exception as exc:  # fail open
        print("team-guard: internal error ignored (%s)" % exc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
