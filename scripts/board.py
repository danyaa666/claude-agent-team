#!/usr/bin/env python3
"""Team board CLI: the only sanctioned way for dev/qa to touch .team/README.md.

    python3 scripts/board.py --as <leader|dev|qa|human> <command> ...

The README is the single source of truth. Free-form text in it (vision, roadmap,
task descriptions, designs) belongs to the leader and is never rewritten by this
script. Dev/QA can only: change a task's Status along allowed transitions, set
Branch/PR on their own task, and append comments. Every write is locked + atomic.
Run `board.py --as leader --help` for the command list.
"""
import argparse
import contextlib
import fcntl
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teamlib as tl  # noqa: E402

ROLES = ("leader", "dev", "qa", "human")
STATUS_ORDER = ["BACKLOG", "TODO", "IN_PROGRESS", "READY_FOR_QA", "IN_QA", "QA_FAIL", "QA_PASS",
                "CHANGES_REQUESTED", "MERGED", "DONE", "BLOCKED", "NEEDS_DECISION", "CANCELLED"]
DEP_OK = {"MERGED", "DONE"}
PRIO = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
OWNER = {"IN_PROGRESS": "dev", "IN_QA": "qa", "QA_PASS": "leader"}  # every other status -> "—"
NONE = "—"
PENDING = "_(pending)_"

TRANSITIONS = {}


def _allow(old, new, *roles):
    TRANSITIONS.setdefault((old, new), set()).update(roles)


_allow("BACKLOG", "TODO", "leader")
_allow("TODO", "IN_PROGRESS", "dev")
_allow("QA_FAIL", "IN_PROGRESS", "dev")
_allow("CHANGES_REQUESTED", "IN_PROGRESS", "dev")
_allow("IN_PROGRESS", "READY_FOR_QA", "dev")
_allow("IN_PROGRESS", "BLOCKED", "dev", "leader")
_allow("READY_FOR_QA", "IN_QA", "qa")
_allow("IN_QA", "QA_PASS", "qa")
_allow("IN_QA", "QA_FAIL", "qa")
_allow("IN_QA", "BLOCKED", "qa", "leader")
_allow("QA_PASS", "MERGED", "leader")
_allow("QA_PASS", "CHANGES_REQUESTED", "leader")
_allow("QA_PASS", "READY_FOR_QA", "leader")          # re-test after rebase / new commits
_allow("READY_FOR_QA", "CHANGES_REQUESTED", "leader")
_allow("IN_PROGRESS", "TODO", "leader")              # reclaim a stalled dev task
_allow("IN_QA", "READY_FOR_QA", "leader")            # reclaim a stalled QA task
_allow("MERGED", "DONE", "leader", "human")          # human accepted
_allow("QA_FAIL", "TODO", "leader")                  # re-plan a parked task (resets its rework budget)
_allow("CHANGES_REQUESTED", "TODO", "leader")
_allow("BLOCKED", "TODO", "leader")
_allow("NEEDS_DECISION", "TODO", "leader")
_allow("NEEDS_DECISION", "BACKLOG", "leader")
for _old in ("BACKLOG", "TODO", "IN_PROGRESS", "READY_FOR_QA", "IN_QA", "QA_FAIL", "QA_PASS",
             "CHANGES_REQUESTED", "BLOCKED", "NEEDS_DECISION"):
    for _new in ("BLOCKED", "NEEDS_DECISION", "CANCELLED", "BACKLOG"):
        if _old != _new:
            _allow(_old, _new, "leader")

DEV_KEYS = {"branch": "Branch", "pr": "PR"}
META_KEYS = {"branch": "Branch", "pr": "PR", "priority": "Priority", "type": "Type",
             "milestone": "Milestone", "depends-on": "Depends-on", "depends": "Depends-on",
             "assignee": "Assignee", "risk": "Risk"}


class BoardError(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- parsing
META_RE = re.compile(r"^- \*\*([A-Za-z][A-Za-z -]*):\*\*[ \t]*(.*)$")
REGION_RE = re.compile(r"(<!-- (tasks|questions):start -->)(.*?)(<!-- \2:end -->)", re.S)
SUMMARY_RE = re.compile(r"<!-- summary:start -->.*?<!-- summary:end -->", re.S)
COMMENTS_HEADING = "#### Comments"


class Item:
    """A `### T-001 — title` (or Q-001) block: ordered meta list + opaque body."""

    def __init__(self, ident, title):
        self.id, self.title = ident, title
        self.meta, self.rest = [], []

    def get(self, key, default=""):
        for k, v in self.meta:
            if k.lower() == key.lower():
                return v
        return default

    def set(self, key, value):
        for pair in self.meta:
            if pair[0].lower() == key.lower():
                pair[1] = value
                return
        self.meta.append([key, value])

    def render(self):
        lines = ["### %s — %s" % (self.id, self.title)]
        lines += [("- **%s:** %s" % (k, v)).rstrip() for k, v in self.meta]
        lines.append("")
        lines += self.rest
        return "\n".join(lines).rstrip("\n") + "\n"

    def _comments_at(self):
        for i, line in enumerate(self.rest):
            if line.strip() == COMMENTS_HEADING:
                return i
        return -1

    def comments(self):
        at = self._comments_at()
        out = []
        if at < 0:
            return out
        for line in self.rest[at + 1:]:
            if line.startswith("#"):
                break
            if line.startswith("- "):
                out.append([line])
            elif line.startswith("  ") and out:
                out[-1].append(line)
        return ["\n".join(c) for c in out]

    def add_comment(self, role, text):
        body = text.strip().split("\n")
        entry = ["- %s · %s · %s" % (tl.stamp(), role, body[0])] + ["  " + ln for ln in body[1:]]
        if self._comments_at() < 0:
            self.rest += ["", COMMENTS_HEADING]
        while self.rest and not self.rest[-1].strip():
            self.rest.pop()
        self.rest += entry


class Section:
    def __init__(self, name, inner):
        self.name = name
        regex = re.compile(r"^###\s+([TQ]-\d+)\s+[—–-]+\s+(.*?)\s*$")
        pre, self.items, cur = [], [], None
        for line in inner.split("\n"):
            m = regex.match(line)
            if m:
                cur = Item(m.group(1), m.group(2))
                cur.lines = []
                self.items.append(cur)
            elif cur is None:
                pre.append(line)
            else:
                cur.lines.append(line)
        self.pre = "\n".join(pre).strip("\n")
        for it in self.items:
            i = 0
            while i < len(it.lines) and not it.lines[i].strip():
                i += 1
            while i < len(it.lines):
                m = META_RE.match(it.lines[i])
                if not m:
                    break
                it.meta.append([m.group(1).strip(), m.group(2).strip()])
                i += 1
            rest = it.lines[i:]
            while rest and not rest[0].strip():
                rest.pop(0)
            while rest and not rest[-1].strip():
                rest.pop()
            it.rest = rest
            del it.lines

    def render(self):
        chunks = ([self.pre + "\n"] if self.pre else []) + [it.render() for it in self.items]
        inner = "\n".join(chunks)
        return "<!-- %s:start -->\n\n%s%s<!-- %s:end -->" % (
            self.name, inner, "\n" if inner else "", self.name)


class Board:
    def __init__(self, text):
        self.parts, self.sec, pos = [], {}, 0
        for m in REGION_RE.finditer(text):
            self.parts.append(text[pos:m.start()])
            sec = Section(m.group(2), m.group(3))
            self.sec[m.group(2)] = sec
            self.parts.append(sec)
            pos = m.end()
        self.parts.append(text[pos:])
        if "tasks" not in self.sec:
            raise BoardError("README has no <!-- tasks:start --> / <!-- tasks:end --> markers")
        self.dirty = False

    @property
    def tasks(self):
        return self.sec["tasks"].items

    @property
    def questions(self):
        return self.sec["questions"].items if "questions" in self.sec else []

    def task(self, ident):
        ident = normalize_id(ident, "T")
        for t in self.tasks:
            if t.id == ident:
                return t
        raise BoardError("no such task: %s" % ident, 4)

    def question(self, ident):
        ident = normalize_id(ident, "Q")
        for q in self.questions:
            if q.id == ident:
                return q
        raise BoardError("no such question: %s" % ident, 4)

    def render(self):
        text = "".join(p if isinstance(p, str) else p.render() for p in self.parts)
        summary = "<!-- summary:start -->\n%s\n<!-- summary:end -->" % summary_md(self)
        return SUMMARY_RE.sub(lambda _m: summary, text)


def normalize_id(raw, prefix):
    m = re.fullmatch(r"(?i)%s-?(\d+)" % prefix, raw.strip())
    if not m:
        raise BoardError("bad id %r (expected %s-001)" % (raw, prefix))
    return "%s-%03d" % (prefix, int(m.group(1)))


def deps(task):
    return re.findall(r"T-\d+", task.get("Depends-on"))


def deps_met(board, task):
    by_id = {t.id: t for t in board.tasks}
    return all(d in by_id and by_id[d].get("Status") in DEP_OK for d in deps(task))


def q_state(q):
    if q.get("Status") == "RESOLVED":
        return "RESOLVED"
    return "ANSWERED" if q.get("Answer", PENDING) not in ("", PENDING, NONE, "pending") else "OPEN"


def summary_md(board):
    by_status = {}
    for t in board.tasks:
        by_status.setdefault(t.get("Status"), []).append(t.id)
    lines = ["| Status | # | Tasks |", "|---|---:|---|"]
    for s in STATUS_ORDER:
        if s in by_status:
            lines.append("| %s | %d | %s |" % (s, len(by_status[s]), ", ".join(by_status[s])))
    if not by_status:
        lines.append("| _no tasks yet_ | 0 | |")
    merged = ["%s (%s)" % (t.id, t.title) for t in board.tasks if t.get("Status") == "MERGED"]
    openq = ["%s (%s)" % (q.id, q.title) for q in board.questions if q_state(q) != "RESOLVED"]
    lines += ["", "**Awaiting your review (MERGED):** " + ("; ".join(merged) or "nothing"),
              "", "**Open questions for you:** " + ("; ".join(openq) or "none"),
              "", "_Board last written %s_" % tl.stamp()]
    return "\n".join(lines)


# --------------------------------------------------------------------------- storage
@contextlib.contextmanager
def locked(root, exclusive=True):
    with open(os.path.join(tl.state_dir(root), "board.lock"), "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


@contextlib.contextmanager
def open_board(root, write=False):
    path = os.path.join(tl.team_dir(root), "README.md")
    with locked(root, exclusive=write):
        try:
            with open(path, encoding="utf-8") as fh:
                board = Board(fh.read())
        except FileNotFoundError:
            raise BoardError("no board at %s — run /team-init" % path)
        yield board
        if write and board.dirty:
            tl.write_atomic(path, board.render())


def leases_path(root):
    return os.path.join(tl.state_dir(root), "leases.json")


def load_leases(root):
    try:
        with open(leases_path(root), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def active_lease(leases, role):
    lease = leases.get(role)
    if lease and tl.parse_iso(lease["expires_at"]) > tl.utcnow():
        return lease
    return None


def save_leases(root, leases):
    tl.write_atomic(leases_path(root), json.dumps(leases, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- helpers
class Ctx:
    def __init__(self, role):
        self.role, self.root = role, tl.repo_root()
        self.cfg = tl.load_config(self.root)


def require(ctx, *roles):
    if ctx.role not in roles:
        raise BoardError("role %r may not do this (allowed: %s)" % (ctx.role, ", ".join(roles)))


def fmt(t):
    deps_s = t.get("Depends-on")
    deps_s = "" if deps_s in ("", NONE) else " deps:%s" % deps_s.replace(" ", "")
    risk = " RISK:HIGH" if t.get("Risk", "low").lower() == "high" else ""
    return "%s [%s] %s %s %s%s%s — %s" % (
        t.id, t.get("Status"), t.get("Priority", "P2"), t.get("Type", "-"),
        t.get("Milestone", "-"), deps_s, risk, t.title)


def prio_key(t):
    return (PRIO.get(t.get("Priority", "P2"), 2), t.id)


def unread(t):
    seen = int(t.get("Comments-seen", "0") or 0)
    return t.comments()[seen:]


def capacity(ctx, board, role):
    leases = load_leases(ctx.root)
    if role == "dev":
        wip = sum(1 for t in board.tasks if t.get("Status") == "IN_PROGRESS" and t.get("Assignee") == "dev")
        cap, per_wake = ctx.cfg["dev"]["wip_limit"] - wip, ctx.cfg["dev"]["tasks_per_wake"]
    else:
        wip = sum(1 for t in board.tasks if t.get("Status") == "IN_QA" and t.get("Assignee") == "qa")
        per_wake = ctx.cfg["qa"]["tasks_per_wake"]
        cap = per_wake - wip
    lease = active_lease(leases, role)
    if lease:
        cap = min(cap, per_wake - len(lease.get("claims", [])))
    return max(cap, 0)


def candidates(board, role, cfg=None):
    cfg = cfg or tl.load_config()
    if role == "dev":
        rework = sorted((t for t in board.tasks if t.get("Status") in ("QA_FAIL", "CHANGES_REQUESTED")
                         and not parked(cfg, t)),
                        key=prio_key)
        ready = sorted((t for t in board.tasks if t.get("Status") == "TODO" and deps_met(board, t)),
                       key=prio_key)
        return rework + ready
    return sorted((t for t in board.tasks if t.get("Status") == "READY_FOR_QA"),
                  key=lambda t: (t.get("Updated"), t.id))


def events_path(root):
    return os.path.join(tl.state_dir(root), "events.jsonl")


def log_event(task, old, new, role):
    try:
        with open(events_path(tl.repo_root()), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": tl.iso(), "task": task.id, "title": task.title, "from": old,
                                 "to": new, "role": role}) + "\n")
    except OSError:
        pass  # the digest is best-effort; never fail a board write over it


def read_events(root, since):
    out = []
    try:
        with open(events_path(root), encoding="utf-8") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if tl.parse_iso(ev["ts"]) >= since:
                    out.append(ev)
    except FileNotFoundError:
        pass
    return out


def rework_count(t):
    try:
        return int(t.get("Rework", "0") or 0)
    except ValueError:
        return 0


def parked(cfg, t):
    """Sent back more often than leader.max_rework allows: needs a new spec, not another dev pass."""
    return t.get("Status") in ("QA_FAIL", "CHANGES_REQUESTED") and rework_count(t) > cfg["leader"]["max_rework"]


def needs_owner_approval(t):
    return t.get("Risk", "low").lower() == "high" and t.get("Owner-approved", NONE).lower() != "yes"


def set_status(board, task, new, role, note=None):
    old = task.get("Status")
    if new in ("QA_FAIL", "CHANGES_REQUESTED"):
        task.set("Rework", str(rework_count(task) + 1))
    elif new in ("TODO", "BACKLOG"):
        task.set("Rework", "0")  # leader re-planned the task: fresh budget
    log_event(task, old, new, role)
    task.set("Status", new)
    task.set("Assignee", OWNER.get(new, NONE))
    task.set("Updated", "%s by %s" % (tl.stamp(), role))
    if note:
        add_comment(task, role, note)
    board.dirty = True


def add_comment(task, role, text):
    total_before = len(task.comments())
    seen = int(task.get("Comments-seen", "0") or 0)
    task.add_comment(role, text)
    if role == "leader" and seen == total_before:  # leader's own notes aren't "unread" for leader
        task.set("Comments-seen", str(total_before + 1))


def read_text(args_text, args_file):
    if args_file:
        return sys.stdin.read() if args_file == "-" else open(args_file, encoding="utf-8").read()
    return args_text or ""


# --------------------------------------------------------------------------- commands
def cmd_list(ctx, args):
    with open_board(ctx.root) as b:
        wanted = {s.upper() for s in args.status or []}
        rows = [t for t in b.tasks if not wanted or t.get("Status") in wanted]
        print("\n".join(fmt(t) for t in rows) or "(no tasks)")


def cmd_get(ctx, args):
    with open_board(ctx.root) as b:
        print(b.task(args.id).render().rstrip("\n"))


def cmd_summary(ctx, args):
    with open_board(ctx.root) as b:
        leases = load_leases(ctx.root)
        counts = {}
        for t in b.tasks:
            counts[t.get("Status")] = counts.get(t.get("Status"), 0) + 1
        print("TASKS " + (" ".join("%s=%d" % (s, counts[s]) for s in STATUS_ORDER if s in counts) or "none"))
        ready_dev = [t for t in candidates(b, "dev", ctx.cfg)]
        print("DEV_QUEUE %d (rework %d)" % (len(ready_dev), sum(
            1 for t in ready_dev if t.get("Status") != "TODO")))
        print("QA_QUEUE %d" % len(candidates(b, "qa")))
        print("LEADER_REVIEW " + (", ".join(t.id for t in b.tasks if t.get("Status") == "QA_PASS"
                                       and not needs_owner_approval(t)) or "none"))
        print("HUMAN_REVIEW " + (", ".join(t.id for t in b.tasks if t.get("Status") == "MERGED") or "none"))
        print("BLOCKED " + (", ".join("%s(%s)" % (t.id, t.get("Status")) for t in b.tasks
                                        if t.get("Status") in ("BLOCKED", "NEEDS_DECISION")) or "none"))
        ready = sum(1 for t in b.tasks if t.get("Status") in ("TODO", "IN_PROGRESS", "READY_FOR_QA", "IN_QA",
                                                             "QA_FAIL", "QA_PASS", "CHANGES_REQUESTED"))
        print("PIPELINE %d (min_ready_tasks=%d)%s" % (
            ready, ctx.cfg["leader"]["min_ready_tasks"],
            " LOW->plan more work" if ready < ctx.cfg["leader"]["min_ready_tasks"] else ""))
        n_unread = sum(len(unread(t)) for t in b.tasks)
        print("PARKED " + (", ".join("%s(x%d)" % (t.id, rework_count(t)) for t in b.tasks if parked(ctx.cfg, t))
                           or "none") + "  <- re-plan: rewrite or split, then status TODO")
        print("OWNER_APPROVAL " + (", ".join(t.id for t in b.tasks if t.get("Status") == "QA_PASS"
                                            and needs_owner_approval(t)) or "none"))
        print("UNREAD_COMMENTS %d" % n_unread)
        qs = [q for q in b.questions if q_state(q) != "RESOLVED"]
        print("QUESTIONS " + (", ".join("%s(%s)" % (q.id, q_state(q)) for q in qs) or "none"))
        for role in ("dev", "qa"):
            lease = active_lease(leases, role)
            print("LEASE %s %s" % (role, "until %s claims=%s" % (lease["expires_at"], ",".join(
                lease.get("claims", [])) or "-") if lease else "none"))
        stale = []
        for t in b.tasks:
            st = t.get("Status")
            if st in ("IN_PROGRESS", "IN_QA") and not active_lease(leases, OWNER[st]):
                try:
                    when = tl.dt.datetime.strptime(t.get("Updated").split(" by")[0], "%Y-%m-%d %H:%MZ")
                    age = (tl.utcnow().replace(tzinfo=None) - when).total_seconds() / 60
                except ValueError:
                    age = 1e9
                if age > ctx.cfg["leader"]["stale_after_min"]:
                    stale.append("%s(%s,%dm)" % (t.id, st, min(age, 99999)))
        print("STALE " + (", ".join(stale) or "none"))


def cmd_next(ctx, args):
    require(ctx, "dev", "qa", "leader")
    role = ctx.role if ctx.role in ("dev", "qa") else args.for_role
    if role not in ("dev", "qa"):
        raise BoardError("leader must pass --for dev|qa")
    with open_board(ctx.root) as b:
        cap = capacity(ctx, b, role)
        picks = candidates(b, role, ctx.cfg)[:max(0, min(args.limit or cap, cap))]
        print("CAPACITY %d" % cap)
        if not picks:
            print("NONE")
        for t in picks:
            print(("REWORK " if t.get("Status") in ("QA_FAIL", "CHANGES_REQUESTED") else "PICK ") + fmt(t))


def cmd_claim(ctx, args):
    require(ctx, "dev", "qa")
    with open_board(ctx.root, write=True) as b:
        t = b.task(args.id)
        old = t.get("Status")
        if ctx.role == "dev":
            if parked(ctx.cfg, t):
                raise BoardError("%s was sent back %d times (cap %d): the leader must re-plan it (rewrite/split), then move it to TODO" % (t.id, rework_count(t), ctx.cfg["leader"]["max_rework"]))
            ok = old in ("QA_FAIL", "CHANGES_REQUESTED") or (old == "TODO" and deps_met(b, t))
            new = "IN_PROGRESS"
        else:
            ok, new = old == "READY_FOR_QA", "IN_QA"
        if not ok:
            raise BoardError("%s is %s — not claimable by %s (unmet deps?)" % (t.id, old, ctx.role))
        if capacity(ctx, b, ctx.role) <= 0:
            raise BoardError("no capacity left for %s (WIP or per-wake limit reached)" % ctx.role, 3)
        set_status(b, t, new, ctx.role)
        leases = load_leases(ctx.root)
        lease = active_lease(leases, ctx.role)
        if lease:
            lease.setdefault("claims", []).append(t.id)
            save_leases(ctx.root, leases)
        print("CLAIMED %s %s -> %s" % (t.id, old, new))


def cmd_status(ctx, args):
    new = args.new.upper()
    if new not in STATUS_ORDER:
        raise BoardError("unknown status %s; valid: %s" % (new, ", ".join(STATUS_ORDER)))
    with open_board(ctx.root, write=True) as b:
        t = b.task(args.id)
        old = t.get("Status")
        if ctx.role in ("dev", "qa") and new in ("IN_PROGRESS", "IN_QA"):
            raise BoardError("use `claim` to start work (enforces WIP limits)")
        allowed = TRANSITIONS.get((old, new))
        if not allowed or ctx.role not in allowed:
            opts = sorted(n for (o, n), r in TRANSITIONS.items() if o == old and ctx.role in r)
            raise BoardError("%s: %s -> %s not allowed for %s. Allowed from %s: %s" % (
                t.id, old, new, ctx.role, old, ", ".join(opts) or "nothing"))
        if new == "MERGED" and needs_owner_approval(t):
            raise BoardError("%s is Risk: high — the owner must approve the merge first (bin/team approve %s)" % (t.id, t.id))
        if ctx.role in ("dev", "qa") and old in OWNER and OWNER[old] == ctx.role \
                and t.get("Assignee") != ctx.role:
            raise BoardError("%s is not assigned to %s" % (t.id, ctx.role))
        if ctx.role == "dev" and new == "READY_FOR_QA":
            if t.get("Branch") in ("", NONE) or t.get("PR") in ("", NONE):
                raise BoardError("set Branch and PR first: board.py --as dev set %s branch=... pr=..." % t.id)
        set_status(b, t, new, ctx.role, args.note)
        print("%s %s -> %s" % (t.id, old, new))


def cmd_comment(ctx, args):
    text = sys.stdin.read() if args.text == "-" else args.text
    if not text.strip():
        raise BoardError("empty comment")
    with open_board(ctx.root, write=True) as b:
        t = b.task(args.id)
        add_comment(t, ctx.role, text)
        if ctx.role in ("dev", "qa"):  # a comment doubles as a liveness signal for stale detection
            t.set("Updated", "%s by %s" % (tl.stamp(), ctx.role))
        b.dirty = True
        print("COMMENTED %s (#%d)" % (t.id, len(t.comments())))


def cmd_set(ctx, args):
    require(ctx, "leader", "dev")
    with open_board(ctx.root, write=True) as b:
        t = b.task(args.id)
        if ctx.role == "dev" and t.get("Assignee") != "dev":
            raise BoardError("%s is not assigned to dev" % t.id)
        for pair in args.pairs:
            key, _, val = pair.partition("=")
            norm = META_KEYS.get(key.strip().lower())
            if key.strip().lower() == "title" and ctx.role == "leader":
                t.title = val.strip()
                continue
            if norm is None or (ctx.role == "dev" and key.strip().lower() not in DEV_KEYS):
                raise BoardError("key %r not settable by %s" % (key, ctx.role))
            t.set(norm, val.strip() or NONE)
        t.set("Updated", "%s by %s" % (tl.stamp(), ctx.role))
        b.dirty = True
        print("SET %s" % t.id)


def cmd_add_task(ctx, args):
    require(ctx, "leader")
    body = read_text(args.body, args.body_file).strip("\n")
    if re.search(r"(?m)^###\s+[TQ]-\d+\s", body):
        raise BoardError("body must not contain '### T-xxx' headings")
    with open_board(ctx.root, write=True) as b:
        nxt = max([int(t.id[2:]) for t in b.tasks] or [0]) + 1
        t = Item("T-%03d" % nxt, args.title.strip())
        t.meta = [["Status", args.status], ["Priority", args.priority], ["Type", args.type],
                  ["Milestone", args.milestone or NONE], ["Depends-on", args.depends or NONE],
                  ["Risk", args.risk], ["Rework", "0"], ["Owner-approved", NONE],
                  ["Assignee", NONE], ["Branch", NONE], ["PR", NONE],
                  ["Updated", "%s by leader" % tl.stamp()], ["Comments-seen", "0"]]
        t.rest = body.split("\n") if body else []
        if COMMENTS_HEADING not in [ln.strip() for ln in t.rest]:
            t.rest += ["", COMMENTS_HEADING]
        b.sec["tasks"].items.append(t)
        b.dirty = True
        print("ADDED %s" % t.id)


def cmd_unread(ctx, args):
    require(ctx, "leader")
    with open_board(ctx.root) as b:
        shown = False
        for t in b.tasks:
            new = unread(t)
            if new:
                shown = True
                print("%s [%s] — %s" % (t.id, t.get("Status"), t.title))
                print("\n".join(new))
        print("" if shown else "(no unread comments)")


def cmd_ack(ctx, args):
    require(ctx, "leader")
    with open_board(ctx.root, write=True) as b:
        for ident in args.ids:
            t = b.task(ident)
            t.set("Comments-seen", str(len(t.comments())))
        b.dirty = True
        print("ACKED " + " ".join(args.ids))


def cmd_questions(ctx, args):
    with open_board(ctx.root) as b:
        rows = [q for q in b.questions if args.all or q_state(q) != "RESOLVED"]
        for q in rows:
            print("%s [%s] %s | blocks: %s | answer: %s" % (
                q.id, q_state(q), q.title, q.get("Blocks", NONE), q.get("Answer", PENDING)))
        if not rows:
            print("(no open questions)")


def cmd_ask(ctx, args):
    require(ctx, "leader")
    body = read_text(args.body, args.body_file).strip("\n")
    with open_board(ctx.root, write=True) as b:
        if "questions" not in b.sec:
            raise BoardError("README has no questions region (<!-- questions:start -->)")
        sec = b.sec["questions"]
        q = Item("Q-%03d" % (max([int(x.id[2:]) for x in sec.items] or [0]) + 1), args.title.strip())
        q.meta = [["Status", "OPEN"], ["Asked", tl.stamp()], ["Blocks", args.blocks or NONE],
                  ["Recommendation", args.recommendation or NONE], ["Answer", PENDING]]
        q.rest = body.split("\n") if body else []
        sec.items.append(q)
        b.dirty = True
        print("ASKED %s" % q.id)


def cmd_answer(ctx, args):
    require(ctx, "leader", "human")
    with open_board(ctx.root, write=True) as b:
        q = b.question(args.id)
        q.set("Answer", args.text.strip().replace("\n", " "))
        b.dirty = True
        print("ANSWERED %s" % q.id)


def cmd_resolve(ctx, args):
    require(ctx, "leader")
    with open_board(ctx.root, write=True) as b:
        q = b.question(args.id)
        q.set("Status", "RESOLVED")
        b.dirty = True
        print("RESOLVED %s" % q.id)


def cmd_approve(ctx, args):
    require(ctx, "human")
    with open_board(ctx.root, write=True) as b:
        t = b.task(args.id)
        t.set("Owner-approved", "yes")
        add_comment(t, "human", "owner approved merge")
        b.dirty = True
        print("APPROVED %s" % t.id)


def heartbeat_path(root):
    return os.path.join(tl.state_dir(root), "heartbeat.json")


def load_heartbeat(root):
    try:
        with open(heartbeat_path(root), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def digest_text(ctx, board, hours):
    since = tl.utcnow() - tl.dt.timedelta(hours=hours)
    ev = read_events(ctx.root, since)

    def ids(pred):
        seen = []
        for e in ev:
            if pred(e) and e["task"] not in seen:
                seen.append(e["task"])
        return seen

    def names(task_ids):
        by = {t.id: t for t in board.tasks}
        return "; ".join("%s %s" % (i, by[i].title if i in by else "") for i in task_ids) or "none"

    lines = ["# Team digest — %s (last %dh)" % (tl.stamp(), hours), ""]
    lines += ["**Shipped to develop:** " + names(ids(lambda e: e["to"] == "MERGED")),
              "**Passed QA:** " + names(ids(lambda e: e["to"] == "QA_PASS")),
              "**Sent back:** QA_FAIL %d, CHANGES_REQUESTED %d" % (
                  sum(e["to"] == "QA_FAIL" for e in ev), sum(e["to"] == "CHANGES_REQUESTED" for e in ev)),
              "**Started:** " + names(ids(lambda e: e["to"] == "IN_PROGRESS")),
              "**Blocked / need a decision:** " + names(ids(lambda e: e["to"] in ("BLOCKED", "NEEDS_DECISION"))), ""]
    lines.append("## Waiting on you")
    merged = [t for t in board.tasks if t.get("Status") == "MERGED"]
    appr = [t for t in board.tasks if t.get("Status") == "QA_PASS" and needs_owner_approval(t)]
    qs = [q for q in board.questions if q_state(q) != "RESOLVED"]
    lines += ["- Accept merged work (`bin/team accept T-xx`): " + ("; ".join("%s %s" % (t.id, t.title) for t in merged) or "nothing")]
    lines += ["- Approve high-risk merges (`bin/team approve T-xx`): " + ("; ".join("%s %s" % (t.id, t.title) for t in appr) or "nothing")]
    lines += ["- Questions (`bin/team answer Q-xx \"...\"`): " + ("; ".join("%s %s" % (q.id, q.title) for q in qs) or "none")]
    stuck = [t for t in board.tasks if parked(ctx.cfg, t)]
    if stuck:
        lines += ["", "**Parked after %d+ rework rounds (leader re-planning):** %s" % (
            ctx.cfg["leader"]["max_rework"] + 1, ", ".join(t.id for t in stuck))]
    try:
        import usage_gate as ug
        v = ug.evaluate(ctx.cfg, ug.read_cache(ug.default_cache()), tl.utcnow().timestamp())
        use = "%s (5h %s%%, 7d %s%%)" % (v["decision"], "?" if v["five_hour"] is None else round(v["five_hour"]),
                                         "?" if v["seven_day"] is None else round(v["seven_day"]))
    except Exception:  # noqa: BLE001 - digest must not fail on usage lookup
        use = "unknown"
    ready = sum(1 for t in board.tasks if t.get("Status") in ("TODO", "IN_PROGRESS", "READY_FOR_QA", "IN_QA",
                                                             "QA_FAIL", "QA_PASS", "CHANGES_REQUESTED"))
    lines += ["", "**Usage gate now:** " + use, "**Pipeline:** %d active/ready tasks, %d done or merged" % (
        ready, sum(1 for t in board.tasks if t.get("Status") in ("MERGED", "DONE")))]
    return "\n".join(lines) + "\n"


def cmd_digest(ctx, args):
    require(ctx, "leader", "human")
    hours = args.hours or ctx.cfg["leader"]["digest_every_hours"]
    hb = load_heartbeat(ctx.root)
    if args.due:
        last = hb.get("last_digest")
        due = not last or (tl.utcnow() - tl.parse_iso(last)).total_seconds() >= hours * 3600
        print("DUE" if due else "NOT_DUE")
        return
    with open_board(ctx.root) as b:
        text = digest_text(ctx, b, hours)
    if args.write:
        require(ctx, "leader")
        folder = os.path.join(tl.team_dir(ctx.root), "digests")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, tl.utcnow().strftime("%Y-%m-%d") + ".md")
        tl.write_atomic(path, text)
        hb["last_digest"] = tl.iso()
        tl.write_atomic(heartbeat_path(ctx.root), json.dumps(hb, indent=2) + "\n")
        print("WROTE " + os.path.relpath(path, ctx.root))
    print(text, end="")


def lease_ttl(ctx, target):
    return 45 if target == "tick" else ctx.cfg[target]["lease_ttl_min"]


def cmd_lease(ctx, args):
    target = args.target
    if args.action in ("release", "touch"):
        require(ctx, "leader", target)
    elif args.action == "acquire":
        require(ctx, "leader")
    if target not in ("dev", "qa", "tick"):
        raise BoardError("lease target must be dev, qa or tick")
    with locked(ctx.root):
        leases = load_leases(ctx.root)
        cur = active_lease(leases, target)
        if args.action == "show":
            print("%s %s" % (target, json.dumps(cur) if cur else "no active lease"))
            return
        if args.action == "acquire":
            if cur:
                raise BoardError("%s already running (lease until %s)" % (target, cur["expires_at"]), 3)
            ttl = args.ttl or lease_ttl(ctx, target)
            leases[target] = {"acquired_at": tl.iso(),
                              "expires_at": tl.iso(tl.utcnow() + tl.dt.timedelta(minutes=ttl)),
                              "claims": []}
            print("LEASE %s until %s" % (target, leases[target]["expires_at"]))
        elif args.action == "touch":
            if not cur:
                raise BoardError("no active %s lease to touch" % target, 3)
            ttl = args.ttl or lease_ttl(ctx, target)
            cur["expires_at"] = tl.iso(tl.utcnow() + tl.dt.timedelta(minutes=ttl))
            print("LEASE %s until %s" % (target, cur["expires_at"]))
        elif args.action == "release":
            leases.pop(target, None)
            print("RELEASED %s" % target)
        save_leases(ctx.root, leases)


# --------------------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(prog="board.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--as", dest="role", required=True, choices=ROLES, help="who is calling")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("summary", cmd_summary, "queue sizes, leases, stale work, questions")
    sp = add("list", cmd_list, "one line per task")
    sp.add_argument("--status", nargs="*")
    sp = add("get", cmd_get, "print one task block")
    sp.add_argument("id")
    sp = add("next", cmd_next, "tasks you may pick now (dev/qa), with remaining capacity")
    sp.add_argument("--for", dest="for_role", choices=("dev", "qa"))
    sp.add_argument("--limit", type=int)
    sp = add("claim", cmd_claim, "start work on a task (enforces WIP/per-wake limits)")
    sp.add_argument("id")
    sp = add("status", cmd_status, "move a task along an allowed transition")
    sp.add_argument("id")
    sp.add_argument("new")
    sp.add_argument("--note", help="also append this as a comment")
    sp = add("comment", cmd_comment, "append a comment ('-' reads stdin)")
    sp.add_argument("id")
    sp.add_argument("text")
    sp = add("set", cmd_set, "set meta: dev may set branch=/pr=; leader any meta or title=")
    sp.add_argument("id")
    sp.add_argument("pairs", nargs="+")
    sp = add("add-task", cmd_add_task, "leader: create a task from a markdown body")
    sp.add_argument("--title", required=True)
    sp.add_argument("--priority", default="P2", choices=list(PRIO))
    sp.add_argument("--type", default="feature")
    sp.add_argument("--milestone")
    sp.add_argument("--depends", help="e.g. 'T-001, T-002'")
    sp.add_argument("--status", default="TODO", choices=("TODO", "BACKLOG"))
    sp.add_argument("--risk", default="low", choices=("low", "high"),
                    help="high = auth/data/migrations/payments/public API/infra: owner approves before merge")
    sp.add_argument("--body")
    sp.add_argument("--body-file", help="path or '-' for stdin")
    add("unread", cmd_unread, "leader: comments not yet acknowledged")
    sp = add("ack", cmd_ack, "leader: mark all current comments on tasks as seen")
    sp.add_argument("ids", nargs="+")
    sp = add("questions", cmd_questions, "list questions (default: unresolved)")
    sp.add_argument("--all", action="store_true")
    sp = add("ask", cmd_ask, "leader: add a question/decision for the human")
    sp.add_argument("--title", required=True)
    sp.add_argument("--blocks", help="task ids waiting on this")
    sp.add_argument("--recommendation")
    sp.add_argument("--body")
    sp.add_argument("--body-file")
    sp = add("answer", cmd_answer, "leader/human: record the human's answer")
    sp.add_argument("id")
    sp.add_argument("text")
    sp = add("resolve", cmd_resolve, "leader: mark a question fully processed")
    sp.add_argument("id")
    sp = add("approve", cmd_approve, "owner only: approve merging a Risk: high task")
    sp.add_argument("id")
    sp = add("digest", cmd_digest, "activity digest; --write saves .team/digests/<date>.md, --due says if one is due")
    sp.add_argument("--hours", type=int)
    sp.add_argument("--write", action="store_true")
    sp.add_argument("--due", action="store_true")
    sp = add("lease", cmd_lease, "dispatch leases: acquire|release|touch|show dev|qa|tick")
    sp.add_argument("action", choices=("acquire", "release", "touch", "show"))
    sp.add_argument("target")
    sp.add_argument("--ttl", type=int, help="minutes")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.fn(Ctx(args.role), args)
    except BoardError as exc:
        print("board.py: %s" % exc, file=sys.stderr)
        return exc.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
