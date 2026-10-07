"""Tests for the team scripts. Run: python3 -m unittest discover -s scripts/tests -v"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
# A static, self-contained fixture board — NOT a copy of any real project's live .team/README.md.
# This plugin's own repo has no board of its own, and even where one exists (a vendored install),
# tests must not depend on its current content: task IDs, slugs, etc. must be deterministic
# regardless of how much real work is already on whatever board happens to be nearby.
FIXTURE_BOARD = os.path.join(HERE, "fixtures", "board.md")
sys.path.insert(0, SCRIPTS)

import board as bd  # noqa: E402
import statusline  # noqa: E402
import teamlib as tl  # noqa: E402
import usage_gate as ug  # noqa: E402


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def make_root():
    root = tempfile.mkdtemp(prefix="team-test-")
    os.makedirs(os.path.join(root, ".team"))
    shutil.copy(FIXTURE_BOARD, os.path.join(root, ".team", "README.md"))
    os.environ["TEAM_ROOT"] = root
    return root


def run_board(role, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bd.main(["--as", role] + list(argv))
    return code, out.getvalue(), err.getvalue()


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(os.environ.pop, "TEAM_ROOT", None)

    def add(self, title, **kw):
        args = ["add-task", "--title", title, "--body", "#### Description\nx"]
        for k, v in kw.items():
            args += ["--" + k, v]
        code, out, _ = run_board("leader", *args)
        self.assertEqual(code, 0)
        return out.split()[-1]

    def to_ready_for_qa(self, tid):
        self.assertEqual(run_board("dev", "claim", tid)[0], 0)
        run_board("dev", "set", tid, "branch=task/x", "pr=#1")
        self.assertEqual(run_board("dev", "status", tid, "READY_FOR_QA")[0], 0)

    def test_roundtrip_is_stable(self):
        self.add("A")
        path = os.path.join(self.root, ".team", "README.md")
        text = read(path)
        again = bd.Board(text).render()
        again = bd.SUMMARY_RE.sub("S", again)
        self.assertEqual(bd.SUMMARY_RE.sub("S", text), again)

    def test_full_happy_path_and_ids(self):
        t1, t2 = self.add("A", priority="P1"), self.add("B", depends="T-001")
        self.assertEqual((t1, t2), ("T-001", "T-002"))
        self.assertIn("T-001", run_board("dev", "next")[1])
        self.assertNotIn("T-002", run_board("dev", "next")[1])        # dependency unmet
        self.to_ready_for_qa(t1)
        self.assertEqual(run_board("qa", "claim", t1)[0], 0)
        self.assertEqual(run_board("qa", "status", t1, "QA_PASS", "--note", "all AC verified")[0], 0)
        self.assertEqual(run_board("leader", "status", t1, "MERGED")[0], 0)
        self.assertIn("T-002", run_board("dev", "next")[1])            # dependency now met
        self.assertEqual(run_board("human", "status", t1, "DONE")[0], 0)

    def test_role_permissions(self):
        tid = self.add("A")
        self.assertNotEqual(run_board("dev", "add-task", "--title", "x")[0], 0)
        self.assertNotEqual(run_board("dev", "status", tid, "IN_PROGRESS")[0], 0)   # must claim
        self.assertNotEqual(run_board("dev", "status", tid, "QA_PASS")[0], 0)
        self.assertNotEqual(run_board("qa", "claim", tid)[0], 0)                   # not READY_FOR_QA
        self.assertNotEqual(run_board("dev", "set", tid, "priority=P0")[0], 0)
        self.assertNotEqual(run_board("dev", "lease", "acquire", "dev")[0], 0)
        run_board("dev", "claim", tid)
        self.assertNotEqual(run_board("dev", "status", tid, "READY_FOR_QA")[0], 0)  # no branch/PR yet
        self.assertNotEqual(run_board("qa", "status", tid, "QA_FAIL")[0], 0)

    def test_dev_wip_and_per_wake_limits(self):
        ids = [self.add("T%d" % i) for i in range(4)]
        self.assertEqual(run_board("dev", "claim", ids[0])[0], 0)
        self.assertEqual(run_board("dev", "claim", ids[1])[0], 0)
        code, _, err = run_board("dev", "claim", ids[2])
        self.assertEqual(code, 3)
        self.assertIn("no capacity", err)

    def test_per_wake_limit_with_lease(self):
        ids = [self.add("T%d" % i) for i in range(3)]
        self.assertEqual(run_board("leader", "lease", "acquire", "dev")[0], 0)
        self.assertEqual(run_board("leader", "lease", "acquire", "dev")[0], 3)     # already running
        for tid in ids[:2]:
            self.to_ready_for_qa(tid)                                              # WIP frees up, claims don't
        self.assertEqual(run_board("dev", "claim", ids[2])[0], 3)                  # 2 claims this wake
        run_board("dev", "lease", "release", "dev")
        self.assertEqual(run_board("leader", "lease", "acquire", "dev")[0], 0)
        self.assertEqual(run_board("dev", "claim", ids[2])[0], 0)

    def test_rework_comes_first_and_comments_tracked(self):
        a, b = self.add("A", priority="P3"), self.add("B", priority="P0")
        self.to_ready_for_qa(a)
        run_board("qa", "claim", a)
        run_board("qa", "status", a, "QA_FAIL", "--note", "1. broken\n   steps: x")
        nxt = run_board("dev", "next")[1]
        self.assertLess(nxt.index(a), nxt.index(b))                                # rework before P0 new work
        self.assertIn("broken", run_board("leader", "unread")[1])
        run_board("leader", "ack", a)
        self.assertIn("no unread", run_board("leader", "unread")[1])
        run_board("leader", "comment", a, "fine, dev fix it")
        self.assertIn("no unread", run_board("leader", "unread")[1])               # own comment isn't unread
        self.assertIn("fine, dev fix it", run_board("dev", "get", a)[1])

    def test_questions_flow(self):
        run_board("leader", "ask", "--title", "DB?", "--blocks", "T-001", "--recommendation", "Postgres")
        self.assertIn("[OPEN]", run_board("leader", "questions")[1])
        run_board("human", "answer", "Q-001", "Postgres please")
        self.assertIn("[ANSWERED]", run_board("leader", "questions")[1])
        run_board("leader", "resolve", "Q-001")
        self.assertIn("no open questions", run_board("leader", "questions")[1])
        self.assertIn("none", read(os.path.join(self.root, ".team", "README.md"))
                      .split("**Open questions for you:**")[1].split("\n")[0])

    def test_leader_can_reclaim_stale_work(self):
        tid = self.add("A")
        run_board("dev", "claim", tid)
        self.assertEqual(run_board("leader", "status", tid, "TODO")[0], 0)
        self.assertEqual(run_board("leader", "status", tid, "MERGED")[0], 2)       # not from TODO

    def test_stale_work_is_reported_only_without_a_live_lease(self):
        tid = self.add("A")
        run_board("dev", "claim", tid)
        path = os.path.join(self.root, ".team", "README.md")
        write(path, bd.re.sub(r"(\*\*Updated:\*\* )[^\n]*", r"\g<1>2020-01-01 00:00Z by dev", read(path)))
        self.assertIn("STALE T-001(IN_PROGRESS", run_board("leader", "summary")[1])
        run_board("leader", "lease", "acquire", "dev")                      # dev is (still) running
        self.assertIn("STALE none", run_board("leader", "summary")[1])

    def test_tick_lease_prevents_overlap(self):
        self.assertEqual(run_board("leader", "lease", "acquire", "tick")[0], 0)
        self.assertEqual(run_board("leader", "lease", "acquire", "tick")[0], 3)
        self.assertEqual(run_board("leader", "lease", "release", "tick")[0], 0)
        self.assertEqual(run_board("leader", "lease", "acquire", "tick")[0], 0)

    def fail_once(self, tid):
        self.assertEqual(run_board("dev", "claim", tid)[0], 0)
        run_board("dev", "set", tid, "branch=task/x", "pr=#1")
        self.assertEqual(run_board("dev", "status", tid, "READY_FOR_QA")[0], 0)
        run_board("qa", "claim", tid)
        self.assertEqual(run_board("qa", "status", tid, "QA_FAIL", "--note", "1. broken")[0], 0)

    def test_rework_cap_parks_task_after_max_rounds(self):
        tid = self.add("A")
        for _ in range(2):                       # max_rework=2: two rounds go back to dev
            self.fail_once(tid)
            self.assertIn("REWORK " + tid, run_board("dev", "next")[1])
        self.fail_once(tid)                      # third failure exceeds the cap
        self.assertIn("NONE", run_board("dev", "next")[1])
        code, _, err = run_board("dev", "claim", tid)
        self.assertNotEqual(code, 0)
        self.assertIn("re-plan", err)
        self.assertIn("PARKED %s(x3)" % tid, run_board("leader", "summary")[1])
        self.assertEqual(run_board("leader", "status", tid, "TODO")[0], 0)   # leader re-plans -> fresh budget
        self.assertIn("PARKED none", run_board("leader", "summary")[1])
        self.assertIn("PICK " + tid, run_board("dev", "next")[1])

    def test_high_risk_needs_owner_approval_before_merge(self):
        tid = self.add("Auth change", risk="high")
        self.assertIn("RISK:HIGH", run_board("leader", "list")[1])
        self.to_ready_for_qa(tid)
        run_board("qa", "claim", tid)
        run_board("qa", "status", tid, "QA_PASS")
        summary = run_board("leader", "summary")[1]
        self.assertIn("OWNER_APPROVAL " + tid, summary)
        self.assertIn("LEADER_REVIEW none", summary)
        code, _, err = run_board("leader", "status", tid, "MERGED")
        self.assertNotEqual(code, 0)
        self.assertIn("approve", err)
        self.assertNotEqual(run_board("leader", "approve", tid)[0], 0)      # the leader cannot approve itself
        self.assertNotEqual(run_board("dev", "approve", tid)[0], 0)
        self.assertEqual(run_board("human", "approve", tid)[0], 0)
        self.assertEqual(run_board("leader", "status", tid, "MERGED")[0], 0)

    def test_low_risk_merges_without_approval(self):
        tid = self.add("Docs")
        self.to_ready_for_qa(tid)
        run_board("qa", "claim", tid)
        run_board("qa", "status", tid, "QA_PASS")
        self.assertEqual(run_board("leader", "status", tid, "MERGED")[0], 0)

    def test_digest_reports_activity_and_waiting_items(self):
        tid = self.add("Ship it")
        self.to_ready_for_qa(tid)
        run_board("qa", "claim", tid)
        run_board("qa", "status", tid, "QA_PASS")
        run_board("leader", "status", tid, "MERGED")
        run_board("leader", "ask", "--title", "DB?")
        self.assertEqual(run_board("dev", "digest")[0], 2)                  # dev may not read/write digests
        self.assertIn("DUE", run_board("leader", "digest", "--due")[1])
        code, out, _ = run_board("leader", "digest", "--write")
        self.assertEqual(code, 0)
        self.assertIn("**Shipped to develop:** T-001 Ship it", out)
        self.assertIn("Accept merged work", out)
        self.assertIn("Q-001 DB?", out)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".team", "digests",
                                                    tl.utcnow().strftime("%Y-%m-%d") + ".md")))
        self.assertIn("NOT_DUE", run_board("leader", "digest", "--due")[1])

    def test_body_cannot_inject_task_headings(self):
        code, _, _ = run_board("leader", "add-task", "--title", "x", "--body", "### T-099 — evil")
        self.assertEqual(code, 2)

    def test_concurrent_writers_do_not_lose_updates(self):
        tid = self.add("A")
        procs = [subprocess.Popen([sys.executable, os.path.join(SCRIPTS, "board.py"), "--as", "dev", "comment", tid,
                                   "c%d" % i], env=dict(os.environ), stdout=subprocess.DEVNULL) for i in range(8)]
        for p in procs:
            self.assertEqual(p.wait(), 0)
        text = run_board("leader", "get", tid)[1]
        for i in range(8):
            self.assertIn("· dev · c%d" % i, text)

    # ---- epics: per-epic tasks.md + PRD.md next to the README board
    def epic_path(self, slug, name="tasks.md"):
        return os.path.join(self.root, ".team", "epics", slug, name)

    def readme(self):
        return read(os.path.join(self.root, ".team", "README.md"))

    def test_epic_tasks_live_in_their_own_file_with_global_ids(self):
        t1 = self.add("Sign up", epic="auth")
        t2 = self.add("Unfiled")                      # no epic: stays in the README's own region
        t3 = self.add("Charge card", epic="payments")
        self.assertEqual((t1, t2, t3), ("T-001", "T-002", "T-003"))   # ids are global, not per epic
        self.assertIn("### T-001 — Sign up", read(self.epic_path("auth")))
        self.assertIn("### T-003 — Charge card", read(self.epic_path("payments")))
        readme = self.readme()
        self.assertIn("### T-002 — Unfiled", readme)
        self.assertNotIn("### T-001", readme)         # the whole point: tasks are out of the README
        self.assertTrue(os.path.exists(self.epic_path("auth", "PRD.md")))     # stub so the PRD pointer never dangles
        lines = {ln.split()[0]: ln for ln in run_board("leader", "list")[1].splitlines()}
        self.assertIn("epic:auth", lines["T-001"])
        self.assertIn("epic:payments", lines["T-003"])
        self.assertNotIn("epic:", lines["T-002"])

    def test_status_changes_are_written_to_the_epic_file_not_the_readme(self):
        tid = self.add("Sign up", epic="auth")
        self.assertEqual(run_board("dev", "claim", tid)[0], 0)
        self.assertIn("**Status:** IN_PROGRESS", read(self.epic_path("auth")))
        readme = self.readme()
        self.assertNotIn(tid, readme.split("<!-- summary:end -->")[1])           # no task block in the README...
        self.assertIn("IN_PROGRESS | 1 | T-001", readme)                          # ...but its summary still counts it
        self.assertIn("**Epics (done/total):** auth 0/1", readme)

    def test_get_points_dev_and_qa_at_the_epics_prd(self):
        tid = self.add("Sign up", epic="auth")
        out = run_board("dev", "get", tid)[1]
        self.assertIn("EPIC auth — PRD: .team/epics/auth/PRD.md", out)
        self.assertIn("### T-001 — Sign up", out)
        self.assertNotIn("EPIC", run_board("dev", "get", self.add("Plain"))[1])  # unfiled tasks: unchanged output

    def test_leader_can_move_a_task_between_epic_and_readme(self):
        tid = self.add("Sign up")
        self.assertEqual(run_board("leader", "set", tid, "epic=auth")[0], 0)
        self.assertIn("### T-001", read(self.epic_path("auth")))
        self.assertNotIn("### T-001", self.readme().split("<!-- summary:end -->")[1])
        self.assertEqual(run_board("leader", "set", tid, "epic=-")[0], 0)           # '-' = back to unfiled
        self.assertIn("### T-001", self.readme())
        self.assertNotIn("### T-001", read(self.epic_path("auth")))
        self.assertEqual(run_board("dev", "claim", tid)[0], 0)                       # dev owns it now, so only the key is at issue
        code, _, err = run_board("dev", "set", tid, "epic=auth")
        self.assertEqual(code, 2)
        self.assertIn("not settable by dev", err)                                    # only the leader files tasks

    def test_bad_epic_slug_is_rejected_and_writes_nothing(self):
        code, _, err = run_board("leader", "add-task", "--title", "x", "--epic", "../evil", "--body", "b")
        self.assertEqual(code, 2)
        self.assertIn("bad epic slug", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".team", "epics")))

    def test_epics_command_and_roundtrip_stability(self):
        self.add("Sign up", epic="auth")
        out = run_board("leader", "epics")[1]
        self.assertIn("EPIC auth tasks=1 done=0 prd=yes", out)
        text = read(self.epic_path("auth"))
        board = bd.Board(self.readme(), {"auth": text})
        self.assertEqual(board.render_epic("auth"), text)        # parse -> render is lossless


class GateTests(unittest.TestCase):
    cfg = tl.load_config("/nonexistent")

    def cache(self, five, seven, age=10, now=1_000_000):
        return {"written_at": now - age,
                "five_hour": {"used_percentage": five, "resets_at": now + 3600},
                "seven_day": {"used_percentage": seven, "resets_at": now + 86400}}

    def test_thresholds_are_strict(self):
        now = 1_000_000
        self.assertEqual(ug.evaluate(self.cfg, self.cache(59.9, 74.9), now)["decision"], "GO")
        self.assertEqual(ug.evaluate(self.cfg, self.cache(60, 10), now)["decision"], "SLEEP")
        self.assertEqual(ug.evaluate(self.cfg, self.cache(10, 75), now)["decision"], "SLEEP")
        v = ug.evaluate(self.cfg, self.cache(61, 80), now)
        self.assertIn("five_hour", v["reason"])
        self.assertIn("seven_day", v["reason"])

    def test_unknown_fails_closed(self):
        now = 1_000_000
        self.assertEqual(ug.evaluate(self.cfg, None, now)["decision"], "SLEEP")
        self.assertEqual(ug.evaluate(self.cfg, self.cache(1, 1, age=9999), now)["decision"], "SLEEP")
        c = self.cache(1, 1)
        c["five_hour"] = None
        self.assertEqual(ug.evaluate(self.cfg, c, now)["decision"], "SLEEP")
        relaxed = json.loads(json.dumps(self.cfg))
        relaxed["usage"]["on_unknown"] = "go"
        self.assertEqual(ug.evaluate(relaxed, None, now)["decision"], "GO")

    def test_expired_window_counts_as_reset(self):
        now = 1_000_000
        c = self.cache(99, 10)
        c["five_hour"]["resets_at"] = now - 5          # window already rolled over
        self.assertEqual(ug.evaluate(self.cfg, c, now)["decision"], "GO")

    def test_statusline_writes_cache_only_with_rate_limits(self):
        path = os.path.join(tempfile.mkdtemp(), "usage.json")
        self.assertFalse(statusline.update_cache({"model": {}}, path))
        self.assertFalse(os.path.exists(path))
        data = {"rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": 1},
                                "seven_day": {"used_percentage": 41.2, "resets_at": 2}},
                "cost": {"total_api_duration_ms": 77}}
        self.assertTrue(statusline.update_cache(data, path))
        rec = json.loads(read(path))
        self.assertEqual((rec["five_hour"]["used_percentage"], rec["api_ms"]), (23.5, 77))
        env = dict(os.environ, TEAM_USAGE_CACHE=path, TEAM_ROOT=tempfile.mkdtemp())
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "usage_gate.py")], env=env,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0 if "GO" in res.stdout else 10)
        self.assertTrue(res.stdout.startswith(("GO", "SLEEP")))

    def test_gate_cli_sleeps_on_high_usage(self):
        path = os.path.join(tempfile.mkdtemp(), "usage.json")
        write(path, json.dumps({"written_at": time.time(),
                                "five_hour": {"used_percentage": 65, "resets_at": time.time() + 7200},
                                "seven_day": {"used_percentage": 10, "resets_at": time.time() + 99999}}))
        env = dict(os.environ, TEAM_USAGE_CACHE=path, TEAM_ROOT=tempfile.mkdtemp())
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "usage_gate.py")], env=env,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 10)
        self.assertIn("SLEEP", res.stdout)
        self.assertIn("window_resets_in=", res.stdout)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="guard-")
        os.makedirs(os.path.join(self.root, ".team", "worktrees", "T-001"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def call(self, tool, tin, agent=None, env_role=None):
        payload = {"tool_name": tool, "tool_input": tin, "cwd": self.root}
        if agent:
            payload["agent_type"] = agent
        env = {k: v for k, v in os.environ.items() if k not in ("TEAM_ROLE", "TEAM_ROOT")}
        env["TEAM_ROOT"] = self.root
        if env_role:
            env["TEAM_ROLE"] = env_role
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=json.dumps(payload),
                             env=env, capture_output=True, text=True)
        return res.returncode

    def wt(self, rel):
        return os.path.join(self.root, ".team", "worktrees", "T-001", rel)

    def test_roleless_session_is_unrestricted(self):
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.root, "main.go")}), 0)
        self.assertEqual(self.call("Bash", {"command": "git push --force origin main"}), 0)

    def test_dev_write_scope(self):
        self.assertEqual(self.call("Write", {"file_path": self.wt("main.go")}, "dev"), 0)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.root, "main.go")}, "dev"), 2)
        self.assertEqual(self.call("Edit", {"file_path": os.path.join(self.root, ".team", "README.md")}, "dev"), 2)
        self.assertEqual(self.call("Write", {"file_path": self.wt("../../../../etc/passwd")}, "dev"), 0)  # outside repo: not ours

    def test_qa_may_only_write_tests(self):
        self.assertEqual(self.call("Write", {"file_path": self.wt("pkg/a_test.go")}, "qa"), 0)
        self.assertEqual(self.call("Write", {"file_path": self.wt("tests/x.py")}, "qa"), 0)
        self.assertEqual(self.call("Write", {"file_path": self.wt("pkg/a.go")}, "qa"), 2)

    def test_leader_write_scope_via_env_role(self):
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.root, ".team", "README.md")}, None, "leader"), 0)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.root, "docs", "a.md")}, None, "leader"), 0)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.root, "main.go")}, None, "leader"), 2)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.root, "CLAUDE.md")}, None, "leader"), 0)
        # agent_type wins over the inherited env role
        self.assertEqual(self.call("Write", {"file_path": self.wt("main.go")}, "dev", "leader"), 0)

    def test_team_role_human_overrides_agent_type(self):
        # TEAM_ROLE=human is the documented escape hatch for an unrestricted session; it must
        # win even when Claude Code reports agent_type (e.g. this plugin's default "leader"
        # agent), not just when agent_type is absent.
        for agent in ("leader", "dev", "qa"):
            self.assertEqual(
                self.call("Write", {"file_path": os.path.join(self.root, "main.go")}, agent, "human"), 0)
            self.assertEqual(
                self.call("Bash", {"command": "git push --force origin main"}, agent, "human"), 0)

    def test_board_calls_must_match_role(self):
        ok = "python3 scripts/board.py --as dev status T-001 READY_FOR_QA"
        self.assertEqual(self.call("Bash", {"command": ok}, "dev"), 0)
        self.assertEqual(self.call("Bash", {"command": ok.replace("--as dev", "--as leader")}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "python3 x/board.py get T-001"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": ok.replace("--as dev", "--as qa")}, "qa"), 0)

    def test_only_a_real_board_call_needs_as_not_a_mere_mention(self):
        # Reading or grepping the script is not invoking it; this used to be blocked for every role.
        self.assertEqual(self.call("Bash", {"command": "grep -n def scripts/board.py"}, "dev"), 0)
        self.assertEqual(self.call("Bash", {"command": "cat scripts/board.py | head"}, "qa"), 0)
        self.assertEqual(self.call("Bash", {"command": "wc -l scripts/board.py"}, None, "leader"), 0)
        # ...while genuine invocations (any spelling) are still policed.
        self.assertEqual(self.call("Bash", {"command": "python3 scripts/board.py get T-001"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "cd x && python3 -u \"/p/q/board.py\" get T-001"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "./scripts/board.py get T-001"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "./scripts/board.py --as dev get T-001"}, "dev"), 0)
        self.assertEqual(self.call("Bash", {"command": "python3 scripts/board.py --as leader get T-001"}, "dev"), 2)

    def test_epic_files_are_board_state_dev_and_qa_cannot_touch(self):
        self.assertEqual(self.call("Bash", {"command": "sed -i s/TODO/DONE/ .team/epics/auth/tasks.md"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "cat .team/epics/auth/PRD.md"}, "dev"), 0)   # reading is fine
        self.assertEqual(self.call("Write", {"file_path": self.wt(".team/epics/auth/tasks.md")}, "dev"), 2)
        # the leader writes PRDs and task bodies: .team/** is in its write_globs
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.root, ".team", "epics", "auth", "PRD.md")},
                                   None, "leader"), 0)

    def test_shell_edits_of_board_are_blocked(self):
        self.assertEqual(self.call("Bash", {"command": "sed -i s/TODO/DONE/ .team/README.md"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "echo hi >> .team/config.json"}, "qa"), 2)
        self.assertEqual(self.call("Bash", {"command": "cat .team/README.md"}, "dev"), 0)

    def test_git_rules(self):
        self.assertEqual(self.call("Bash", {"command": "git -C wt push -u origin task/t-001-x"}, "dev"), 0)
        self.assertEqual(self.call("Bash", {"command": "git push origin main"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "git push origin HEAD:main"}, "qa"), 2)
        self.assertEqual(self.call("Bash", {"command": "git push origin develop"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "git push origin develop"}, None, "leader"), 0)
        self.assertEqual(self.call("Bash", {"command": "git push --force origin task/t-001-x"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "git push --force-with-lease origin task/t-001-main-page"}, "dev"), 0)
        self.assertEqual(self.call("Bash", {"command": "git push origin main"}, None, "leader"), 0)
        self.assertEqual(self.call("Bash", {"command": "git push -f origin main"}, None, "leader"), 2)
        self.assertEqual(self.call("Bash", {"command": "gh pr merge 5 --squash"}, "dev"), 2)
        self.assertEqual(self.call("Bash", {"command": "gh pr merge 5 --squash"}, None, "leader"), 0)

    def test_merge_tools_leader_only(self):
        self.assertEqual(self.call("mcp__github__merge_pull_request", {}, "dev"), 2)
        self.assertEqual(self.call("mcp__github__create_pull_request", {}, "dev"), 0)
        self.assertEqual(self.call("mcp__github__merge_pull_request", {}, None, "leader"), 0)

    def test_fails_open_on_garbage(self):
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input="not json",
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)


class WorktreeTests(unittest.TestCase):
    def sh(self, *cmd, cwd=None):
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True,
                              env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")).stdout.strip()

    def setUp(self):
        base = tempfile.mkdtemp(prefix="wt-")
        self.addCleanup(shutil.rmtree, base, True)
        self.origin, self.root = os.path.join(base, "origin.git"), os.path.join(base, "work")
        self.sh("git", "init", "--bare", "-b", "main", self.origin)
        self.sh("git", "clone", self.origin, self.root)
        self.sh("git", "checkout", "-b", "main", cwd=self.root)
        os.makedirs(os.path.join(self.root, ".team"))
        shutil.copy(FIXTURE_BOARD, os.path.join(self.root, ".team", "README.md"))
        write(os.path.join(self.root, "a.txt"), "a")
        write(os.path.join(self.root, ".gitignore"), ".team/worktrees/\n.team/state/\n")
        self.sh("git", "add", "-A", cwd=self.root)
        self.sh("git", "commit", "-m", "init", cwd=self.root)
        self.sh("git", "push", "-u", "origin", "main", cwd=self.root)
        self.sh("git", "push", "origin", "main:develop", cwd=self.root)
        os.environ["TEAM_ROOT"] = self.root
        self.addCleanup(os.environ.pop, "TEAM_ROOT", None)
        run_board("leader", "add-task", "--title", "Add Lesson API!", "--body", "#### Description\nx")

    def worktree(self, *args):
        res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "worktree.py")] + list(args), cwd=self.root,
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout.strip()

    def test_ensure_creates_named_branch_and_is_idempotent(self):
        path = self.worktree("ensure", "T-001")
        self.assertTrue(path.endswith(".team/worktrees/T-001"))
        self.assertEqual(self.sh("git", "branch", "--show-current", cwd=path), "task/t-001-add-lesson-api")
        self.assertIn("task/t-001-add-lesson-api", run_board("dev", "get", "T-001")[1])
        self.assertEqual(self.worktree("ensure", "T-001"), path)

    def test_rework_reuses_remote_branch_and_board_found_from_worktree(self):
        path = self.worktree("ensure", "T-001")
        write(os.path.join(path, "b.txt"), "b")
        self.sh("git", "add", "-A", cwd=path)
        self.sh("git", "commit", "-m", "feat", cwd=path)
        self.sh("git", "push", "-u", "origin", "task/t-001-add-lesson-api", cwd=path)
        self.sh("git", "worktree", "remove", "--force", path, cwd=self.root)
        again = self.worktree("ensure", "T-001")
        self.assertTrue(os.path.exists(os.path.join(again, "b.txt")))
        self.assertEqual(tl.repo_root(again), os.path.realpath(self.root))        # board resolves from a worktree

    def test_prune_removes_only_finished_clean_worktrees(self):
        path = self.worktree("ensure", "T-001")
        self.assertIn("removed: none", self.worktree("prune"))
        run_board("leader", "status", "T-001", "CANCELLED")
        write(os.path.join(path, "dirty.txt"), "x")
        self.assertIn("dirty", self.worktree("prune"))
        os.remove(os.path.join(path, "dirty.txt"))
        self.assertIn("removed: T-001", self.worktree("prune"))
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
