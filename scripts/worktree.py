#!/usr/bin/env python3
"""One git worktree per task, at .team/worktrees/<TASK-ID>, on branch task/<id>-<slug>.

    worktree.py ensure T-001    create or reuse; prints the absolute path
    worktree.py path   T-001    print the path (no creation)
    worktree.py prune           leader: remove clean worktrees of MERGED/DONE/CANCELLED tasks

Dev and QA both use `ensure`: a task is only ever worked by one of them at a time
(the board statuses guarantee that), so they share the checkout. The branch is taken
from origin/<branch> when it already exists (rework after QA_FAIL), otherwise cut
from origin/<integration_branch> (local one when there is no remote).
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board as bd  # noqa: E402
import teamlib as tl  # noqa: E402


def git(root, *args, check=True):
    out = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True)
    if check and out.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(args), out.stderr.strip()))
    return out


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "task"


def wt_path(root, task_id):
    return os.path.join(root, ".team", "worktrees", task_id)


def ensure(task_id):
    root, cfg = tl.repo_root(), None
    cfg = tl.load_config(root)
    tid = bd.normalize_id(task_id, "T")
    path = wt_path(root, tid)
    with bd.open_board(root, write=True) as b:
        t = b.task(tid)
        branch = t.get("Branch")
        if branch in ("", bd.NONE) or not branch.startswith("task/"):
            branch = "task/%s-%s" % (tid.lower(), slug(t.title))
            t.set("Branch", branch)
            b.dirty = True
    if os.path.isdir(path):
        print(path)
        return 0
    has_origin = git(root, "remote", check=False).stdout.strip() != ""
    if has_origin:
        git(root, "fetch", "origin", "--prune", check=False)
    remote_branch = has_origin and git(root, "rev-parse", "--verify", "-q", "origin/" + branch,
                                       check=False).returncode == 0
    base = ("origin/" + branch) if remote_branch else (
        ("origin/" if has_origin else "") + cfg["integration_branch"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    git(root, "worktree", "add", "-B", branch, path, base)
    if remote_branch:
        git(path, "branch", "--set-upstream-to=origin/" + branch, branch, check=False)
    print(path)
    return 0


def prune():
    root = tl.repo_root()
    removed, kept = [], []
    with bd.open_board(root) as b:
        done = {t.id for t in b.tasks if t.get("Status") in ("MERGED", "DONE", "CANCELLED")}
    base = os.path.join(root, ".team", "worktrees")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if name not in done:
            continue
        path = os.path.join(base, name)
        if git(path, "status", "--porcelain", check=False).stdout.strip():
            kept.append(name + " (dirty)")
            continue
        git(root, "worktree", "remove", path, check=False)
        removed.append(name)
    git(root, "worktree", "prune", check=False)
    print("removed: %s | kept: %s" % (", ".join(removed) or "none", ", ".join(kept) or "none"))
    return 0


def main(argv):
    if len(argv) >= 2 and argv[0] in ("ensure", "path"):
        if argv[0] == "path":
            print(wt_path(tl.repo_root(), bd.normalize_id(argv[1], "T")))
            return 0
        try:
            return ensure(argv[1])
        except bd.BoardError as exc:
            print("worktree.py: %s" % exc, file=sys.stderr)
            return exc.code
    if argv[:1] == ["prune"]:
        return prune()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
