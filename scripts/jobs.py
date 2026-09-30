#!/usr/bin/env python3
"""jobs.py - the build-job coordinator for /test-report, and the helper Claude calls.

THE SHAPE. The browser is the user interface, the local builder server (serve_builder.py
--jobs) is the job coordinator, and the running /test-report command is the worker. Nothing
here launches Claude: the command that is already running claims a job and does the build,
and reports each step through this helper.

    browser  --submit-->  server  <--claim / progress / ask / complete--  jobs.py (Claude)

HELPER (what the /test-report command runs; it talks to the server over 127.0.0.1):

    jobs.py wait [--secs 540]            block until the browser submits; claim it; print JSON
                                         exit 7 = nothing submitted yet, run it again
    jobs.py start <stage> "<status>"     a stage has begun (spinner; percent unchanged)
    jobs.py done  <stage> "<status>"     a stage is complete (percent from the stage table)
    jobs.py log [--level info|warn|error] "<message>"
    jobs.py run --stage <stage> [--gates] -- <command...>
                                         run one child process for the job: its output goes
                                         to the job log; with --gates, finish.sh's structured
                                         JTI-GATE lines drive the stages, and a pass is
                                         recorded with the hashes of what was verified
    jobs.py ask --id ID --title T --prompt P --type choice|text|longtext|file
                [--option VALUE[=LABEL]]... [--allow-text] [--optional] [--timeout SECS]
                                         put a question in the browser and BLOCK until it is
                                         answered: prints the answer JSON (exit 0); exit 5 =
                                         nobody answered in time (the job is now timed out)
    jobs.py fail --stage <stage> --message "<why>" [--retryable]
    jobs.py complete                     verify and register the deliverables; finish
    jobs.py status                       print the job as the browser sees it

Every helper call reports the cancel flag: exit 6 means the user cancelled - stop at once.

STATE. One job at a time. A job lives on disk, written atomically, in a hidden folder inside
the report folder it builds (`<report>/.jti-build/job.json`), so a browser refresh or a
server restart loses nothing. The server's own state - the worker token and an index of job
folders - is in `<workspace root>/.jti-builder/` (mode 0700). Nothing goes in ~/Downloads.

PERCENT is never timed. It is the table value of the highest stage reported DONE, so it only
moves when work finishes, and it never goes down.
"""
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# key, percent when DONE, label once done (checklist), label while it runs
STAGES = [
    ("submitted", 0, "Submitted", "Waiting for Claude"),
    ("validated", 5, "Specification validated", "Validating the specification"),
    ("destination", 12, "Destination and SDK checked", "Checking the destination and SDK"),
    ("requirements", 22, "Requirements and field sources resolved", "Resolving requirements and field sources"),
    ("plan", 35, "Rule and build plan prepared", "Preparing the rule"),
    ("scaffold", 45, "Report scaffolded", "Scaffolding the report"),
    ("fixtures", 55, "Fixtures prepared", "Preparing fixture rows"),
    ("contract", 62, "Contract check passed", "Checking the rule/layout contract"),
    ("rule", 72, "Rule execution passed", "Running the rule"),
    ("render", 84, "Rendered", "Rendering the pages"),
    ("truncation", 90, "Truncation check passed", "Checking for cut-off values"),
    ("package", 93, "Rule package written", "Writing the rule package"),
    ("review", 96, "Every rendered page looked at", "Looking at every rendered page"),
    ("documentation", 98, "Documentation written", "Writing the documentation"),
    ("complete", 100, "Complete", "Completing"),
]
PERCENT = {k: p for k, p, _, _ in STAGES}
LABEL = {k: l for k, _, l, _ in STAGES}
DOING = {k: d for k, _, _, d in STAGES}
# The neutral name, for a stage that FAILED - "Failed at: Contract check passed" contradicts itself.
NAME = {'submitted': 'Submission', 'validated': 'Specification', 'destination': 'Destination and SDK', 'requirements': 'Requirements and fields', 'plan': 'Rule', 'scaffold': 'Scaffold', 'fixtures': 'Fixtures', 'contract': 'Contract check', 'rule': 'Rule execution', 'render': 'Render', 'truncation': 'Truncation check', 'package': 'Rule package', 'review': 'Page review', 'documentation': 'Documentation', 'complete': 'Completion'}
TERMINAL = ("complete", "failed", "cancelled", "timed_out")
QTYPES = ("choice", "text", "longtext", "file")
MAX_ANSWER = {"text": 400, "longtext": 20000, "choice": 400}
MAX_UPLOAD = 200 * 1024 * 1024               # an SDK jar is tens of MB
LEVELS = ("info", "warn", "error")
MAX_STATUS = 300            # characters of a status line or log message kept
MAX_EVENTS = 2000

EXIT_CANCELLED, EXIT_TIMEOUT, EXIT_NOJOB = 6, 5, 7
EXIT_DONE = 8          # the user clicked "Done" on the page: stop waiting, end the session
DONE_TTL = 6 * 3600    # a Done nobody collected is forgotten, so it cannot end a LATER session
# The page checks in every 3 s. A hidden tab's timers are throttled to about once a minute,
# so only a long silence means it is gone; a close/reload sends a beacon, and a reload
# checks back in within a second or two - so a beacon with no return within the grace
# period is a closed tab.
PAGE_TTL = int(os.environ.get("JTI_PAGE_TTL") or 180)          # env: tests only
# 5 s: a reload checks back in within about a second on localhost, and a longer wait made
# a real close look like it had not worked (the user gave up on it before 20 s).
CLOSE_GRACE = int(os.environ.get("JTI_CLOSE_GRACE") or 5)

# finish.sh / verify_fast.py gate name -> stage in the table. `regenerate` rebuilds the
# layout for the contract check, so it runs inside the contract stage.
GATE_STAGE = {"regenerate": "contract", "contract": "contract", "rule": "rule",
              "render": "render", "truncation": "truncation", "package": "package"}


# ── files ─────────────────────────────────────────────────────────────────────────────
def atomic_write(path, data, mode=0o600):
    """Write whole-or-nothing: a reader never sees half a job, even mid-crash."""
    path = pathlib.Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def state_dir(root=None):
    import project as P
    d = pathlib.Path(root or P.ROOT) / ".jti-builder"
    d.mkdir(mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def digest(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def same(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))


def clip(s, n=MAX_STATUS):
    s = str(s if s is not None else "")
    return s if len(s) <= n else s[:n - 1] + "…"


# ── the store (server side) ──────────────────────────────────────────────────────────
class Store:
    """All job state. Every mutation happens under one lock, is written to disk before the
    lock is released, and wakes every waiter (worker long-polls, browser streams)."""

    def __init__(self, root=None):
        self.dir = state_dir(root)
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.jobs = {}                               # id -> job (cache of what is on disk)
        srv = self._read(self.dir / "server.json") or {}
        self.worker_token = srv.get("worker_token") or secrets.token_urlsafe(32)
        self.session_token = secrets.token_urlsafe(32)   # new every start; the page fetches it
        self.index = self._read(self.dir / "index.json") or {}
        self.claim_waiters = 0
        self.last_claim = 0.0        # when a worker last long-polled (the gaps between polls)
        self.done_at = None          # the user said "Done": the next claim ends the worker
        self.page_seen = None        # the builder page's last check-in (None: never opened)
        self.page_closing = None     # the page sent its close beacon at this time
        self.stopped = False         # the worker collected Done / Closed and has exited

    @staticmethod
    def _read(p):
        try:
            return json.loads(pathlib.Path(p).read_text())
        except (OSError, ValueError):
            return None

    def publish(self, port):
        atomic_write(self.dir / "server.json", json.dumps(
            {"port": port, "pid": os.getpid(), "worker_token": self.worker_token,
             "started": time.time()}, indent=2))
        # Where THIS server keeps its state, for a helper started from another folder: a job
        # server reused from a different workspace was unreachable (found 09-30). The
        # pointer holds a path only - the worker token stays in the 0600 server.json.
        try:
            home = pathlib.Path.home() / ".jti-builder"
            home.mkdir(mode=0o700, exist_ok=True)
            for old in home.glob("server-*.json"):          # prune servers that have exited
                if not _alive(Store._read(old) or {}):
                    old.unlink()
            atomic_write(home / f"server-{port}.json", json.dumps(
                {"state_dir": str(self.dir), "port": port, "pid": os.getpid()}))
        except OSError:
            pass

    # -- load / save
    def job_file(self, folder):
        return pathlib.Path(folder) / ".jti-build" / "job.json"

    def get(self, jid):
        with self.lock:
            if jid in self.jobs:
                return self.jobs[jid]
            folder = self.index.get(jid)
            if not folder:
                return None
            j = self._read(self.job_file(folder))
            if j and j.get("id") == jid:
                self.jobs[jid] = j
            return j

    def save(self, j):
        with self.lock:
            j["updated"] = time.time()
            bd = pathlib.Path(j["report"]["folder"]) / ".jti-build"
            if bd.is_symlink():
                raise OSError(f"{bd} is a symlink - refusing to write through it")
            bd.mkdir(mode=0o700, exist_ok=True)
            atomic_write(bd / "job.json", json.dumps(j, indent=1))
            self.jobs[j["id"]] = j
            self.changed.notify_all()

    def active(self):
        """The one job that is not finished, if any."""
        with self.lock:
            for jid in list(self.index):
                j = self.get(jid)
                if j and j["status"] not in TERMINAL:
                    return j
        return None

    # -- events
    def event(self, j, kind, stage=None, status=None, level="info", **extra):
        ev = {"seq": len(j["events"]) + 1, "ts": round(time.time(), 3), "kind": kind,
              "stage": stage or j.get("stage"), "percent": j["percent"],
              "status": clip(status if status is not None else j.get("status_text", "")),
              "level": level if level in LEVELS else "info"}
        ev.update(extra)
        j["events"].append(ev)
        if len(j["events"]) > MAX_EVENTS:                    # keep numbering, drop the middle
            j["events"] = j["events"][:50] + j["events"][-(MAX_EVENTS - 50):]
        return ev

    @staticmethod
    def log_path(j):
        # One log per JOB: a rebuild in the same folder must not show the last build's lines.
        return pathlib.Path(j["report"]["folder"]) / ".jti-build" / f"log-{j['id']}.txt"

    def log(self, j, text):
        p = self.log_path(j)
        with open(p, "a", encoding="utf8") as f:
            for line in str(text).splitlines() or [""]:
                f.write(time.strftime("%H:%M:%S ") + line + "\n")

    def log_tail(self, j, n=200):
        p = self.log_path(j)
        try:
            return p.read_text(encoding="utf8", errors="replace").splitlines()[-n:]
        except OSError:
            return []

    # -- lifecycle
    def create(self, report, spec_rel, pre_existing):
        tok = secrets.token_urlsafe(24)
        jid = secrets.token_hex(8)
        now = time.time()
        j = {"id": jid, "token_sha256": digest(tok), "created": now, "updated": now,
             "status": "submitted", "stage": "submitted", "running": False,
             "status_text": "Waiting for Claude to pick this up", "percent": 0,
             "done": ["submitted"], "events": [], "report": report, "spec": spec_rel,
             "pre_existing": pre_existing, "question": None, "answers": {},
             "cancel_requested": False, "child": None, "failure": None, "gates": None,
             "artifacts": [], "partial": [], "worker_seen": None, "claimed": None}
        with self.lock:
            self.event(j, "submitted", "submitted", j["status_text"])
            self.index[jid] = report["folder"]
            atomic_write(self.dir / "index.json", json.dumps(self.index, indent=1))
            self.save(j)
        return j, tok

    def worker_connected(self):
        """A worker parked on claim - or between two of its 50 s polls - or mid-build."""
        a = self.active()
        if self.stopped:                 # it exited on Done: only a NEW wait reconnects it
            return self.claim_waiters > 0
        return (self.claim_waiters > 0 or time.time() - self.last_claim < 75
                or bool(a and a["status"] != "submitted"))

    def request_done(self):
        """The page's Done button. Returns (stopping, message). Only recorded when a worker is
        there to collect it: a flag left for nobody would end the NEXT session on its first wait."""
        with self.lock:
            if not self.worker_connected():
                return False, "Claude is not connected - there is nothing to stop."
            self.done_at = time.time()
            self.changed.notify_all()
            a = self.active()
            if a and a["status"] != "submitted":
                return True, "Claude will stop as soon as this build ends."
            return True, "Claude is stopping."

    def touch_page(self):
        with self.lock:
            self.page_seen, self.page_closing = time.time(), None

    def page_closed(self):
        with self.lock:
            if self.page_seen:
                self.page_closing = time.time()
                self.changed.notify_all()

    def page_gone(self):
        """The page was open and is not any more. Never true for a page nobody opened -
        the four-empty-waits rule covers a worker whose page was never looked at."""
        if not self.page_seen:
            return False
        now = time.time()
        if self.page_closing and now - self.page_closing > CLOSE_GRACE and self.page_seen <= self.page_closing:
            return True
        return now - self.page_seen > PAGE_TTL

    def claim(self, secs):
        """Long-poll for a submitted job; claim the oldest one. Returns DONE instead when the
        user has said they are finished (a job already submitted is still claimed first)."""
        deadline = time.monotonic() + secs
        with self.lock:
            self.claim_waiters += 1
            self.stopped = False
            try:
                while True:
                    self.last_claim = time.time()
                    j = self.active()
                    if self.done_at and not (j and j["status"] == "submitted"):
                        fresh = time.time() - self.done_at < DONE_TTL
                        self.done_at = None
                        if fresh:
                            self.stopped = True
                            return "DONE"
                    if self.page_gone() and not (j and j["status"] == "submitted"):
                        # used up here, so the next /test-report is not ended by an old tab
                        self.page_seen = self.page_closing = None
                        self.stopped = True
                        return "CLOSED"
                    if j and j["status"] == "submitted":
                        j["status"], j["claimed"] = "running", time.time()
                        j["worker_seen"] = time.time()
                        j["status_text"] = "Claude has picked this up"
                        self.event(j, "claimed", "submitted", j["status_text"])
                        self.save(j)
                        return j
                    left = deadline - time.monotonic()
                    if left <= 0:
                        return None
                    self.changed.wait(timeout=min(left, 1.0))
            finally:
                self.claim_waiters -= 1
                self.last_claim = time.time()

    def last_claimed(self):
        """The job the worker most recently claimed, whatever state it is in now."""
        best = None
        for jid in list(self.index):
            j = self.get(jid)
            if j and j.get("claimed") and (not best or j["claimed"] > best["claimed"]):
                best = j
        return best

    def worker_job(self):
        """The job the worker is on: the active, claimed one."""
        j = self.active()
        return j if j and j["status"] != "submitted" else None

    def start(self, j, stage, status):
        j["stage"], j["running"] = stage, True
        j["status_text"] = clip(status or DOING.get(stage, stage))
        self.event(j, "start", stage, j["status_text"])

    def done(self, j, stage, status, level="info"):
        if stage in PERCENT:
            j["percent"] = max(j["percent"], PERCENT[stage])     # monotonic, never timed
            if stage not in j["done"]:
                j["done"].append(stage)
        j["stage"], j["running"] = stage, False
        j["status_text"] = clip(status or LABEL.get(stage, stage))
        self.event(j, "done", stage, j["status_text"], level)

    def gate(self, j, kind, gate, message=""):
        """One structured JTI-GATE line from finish.sh / verify_fast.py."""
        stage = GATE_STAGE.get(gate)
        if kind == "started" and stage:
            if gate == "regenerate":
                self.start(j, stage, "Regenerating the layout")
            else:
                self.start(j, stage, message or DOING[stage])
        elif kind == "passed" and stage and gate != "regenerate":
            self.done(j, stage, LABEL[stage])
        elif kind == "warn":
            self.event(j, "warn", stage, clip(message), "warn")
        elif kind == "failed":
            j["running"] = False
            j["status_text"] = clip(f"{NAME.get(stage, gate)} FAILED - {message}")
            j.setdefault("gate_failures", []).append(
                {"stage": stage or gate, "message": clip(message), "ts": time.time()})
            j["gates"] = None                          # an earlier pass no longer stands
            self.event(j, "gate_failed", stage or gate, j["status_text"], "error")

    # -- questions
    @staticmethod
    def check_question(q):
        """The structured question the worker may ask. Anything else is refused."""
        if not isinstance(q, dict):
            return "question must be an object"
        if not (isinstance(q.get("id"), str) and 0 < len(q["id"]) <= 64
                and all(c.isalnum() or c in "-_" for c in q["id"])):
            return "question id: 1-64 letters, digits, - or _"
        if q.get("type") not in QTYPES:
            return f"question type must be one of {', '.join(QTYPES)}"
        for k in ("title", "prompt"):
            if not (isinstance(q.get(k), str) and q[k].strip()):
                return f"question {k} is required"
        opts = q.get("options") or []
        if q["type"] == "choice":
            if not opts:
                return "a choice question needs options"
            if not all(isinstance(o, dict) and isinstance(o.get("value"), str) and o["value"]
                       for o in opts):
                return "each option needs a value"
        return None

    def ask(self, j, q, timeout):
        q = {"id": q["id"], "title": clip(q["title"], 200), "prompt": clip(q["prompt"], 4000),
             "type": q["type"], "options": [{"value": clip(o["value"], 200),
                                             "label": clip(o.get("label") or o["value"], 200),
                                             "detail": clip(o.get("detail") or "", 400)}
                                            for o in (q.get("options") or [])],
             "allowText": bool(q.get("allowText")), "required": q.get("required", True) is not False,
             "asked": time.time(), "deadline": time.time() + max(1, min(int(timeout), 24 * 3600)),
             "stage": j["stage"]}
        j["question"], j["status"], j["running"] = q, "waiting", False
        j["answers"].pop(q["id"], None)
        j["status_text"] = clip("Question: " + q["title"])
        self.event(j, "question", None, j["status_text"], "warn", question=q["id"])

    def answer(self, j, qid, ans):
        j["answers"][qid] = dict(ans, at=time.time())
        j["question"], j["status"], j["running"] = None, "running", True
        j["status_text"] = "Answer received - continuing"
        self.event(j, "answered", None, j["status_text"], question=qid)

    def time_out(self, j):
        q = j["question"] or {}
        j["status"], j["running"] = "timed_out", False
        j["timed_out"] = {"question": q.get("id"), "title": q.get("title"), "at": time.time()}
        j["question"] = None
        j["status_text"] = "Timed out waiting for an answer"
        j["partial"] = self.created_files(j)
        self.event(j, "timed_out", None, j["status_text"], "error", question=q.get("id"))

    def fail(self, j, stage, message, excerpt="", retryable=False, attempts=0):
        j["status"], j["running"] = "failed", False
        j["failure"] = {"stage": stage, "label": NAME.get(stage, stage),
                        "message": clip(message, 1000), "excerpt": clip(excerpt, 6000),
                        "retryable": bool(retryable), "auto_attempts": int(attempts or 0)}
        j["status_text"] = f"Failed at: {NAME.get(stage, stage)}"
        j["partial"] = self.created_files(j)
        self.event(j, "failed", stage, clip(message), "error")

    def created_files(self, j):
        """Files in the report folder that were not there when the job was submitted."""
        folder = pathlib.Path(j["report"]["folder"])
        pre = set(j.get("pre_existing") or [])
        out = []
        try:
            for p in sorted(folder.rglob("*")):
                rel = str(p.relative_to(folder))
                if rel.startswith(".jti-build") or not p.is_file() or rel in pre:
                    continue
                out.append(rel)
        except OSError:
            pass
        return out[:500]

    def public(self, j):
        """The job as the browser may see it: no token hash, plus the live facts."""
        d = {k: v for k, v in j.items() if k != "token_sha256"}
        d["worker_waiting"] = self.claim_waiters > 0
        d["worker_seen_ago"] = (round(time.time() - j["worker_seen"])
                                if j.get("worker_seen") else None)
        d["log_tail"] = self.log_tail(j)
        return d


# ── the helper (worker side) ─────────────────────────────────────────────────────────
def _alive(s):
    try:
        os.kill(int(s.get("pid")), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _server():
    s = Store._read(state_dir() / "server.json")
    if s and not _alive(s):
        s = None                                     # a leftover from a server that has exited
    if not s:
        # The running job server may belong to another workspace: follow the pointer of a
        # LIVE one, the standard port first (test servers on random ports never win).
        ptrs = [Store._read(f) or {} for f in (pathlib.Path.home() / ".jti-builder").glob("server-*.json")]
        live = sorted((x for x in ptrs if x.get("state_dir") and _alive(x)),
                      key=lambda x: (x.get("port") != 8789, -int(x.get("pid") or 0)))
        for x in live:
            s = Store._read(pathlib.Path(x["state_dir"]) / "server.json")
            if s and _alive(s):
                break
            s = None
    if not s:
        sys.exit("  no builder server state - start it: serve_builder.py --jobs")
    return s


RECONNECT_SECS = 60           # how long a restarting server is waited for


def call(path, body=None, timeout=60):
    """POST to the server as the worker. A server that is restarting (or dropped a long
    poll) is retried for up to a minute - the job is on disk, so nothing is lost by waiting
    - and server.json is re-read each time in case the port changed."""
    import urllib.request
    import urllib.error
    give_up = time.monotonic() + RECONNECT_SECS
    while True:
        s = _server()
        req = urllib.request.Request(
            f"http://127.0.0.1:{s['port']}{path}", data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json", "X-JTI-Worker": s["worker_token"]},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return {"ok": False, "code": e.code, **json.loads(e.read() or b"{}")}
            except ValueError:
                return {"ok": False, "code": e.code, "message": str(e)}
        except (urllib.error.URLError, OSError) as e:
            if time.monotonic() > give_up:
                sys.exit(f"  the builder server is not reachable on port {s['port']}: {e}")
            time.sleep(1)


def _checked(r):
    """Every reply says whether the user cancelled. Exit 6 at once if so."""
    if r.get("cancel"):
        print("CANCELLED - the user cancelled this build in the browser. Stop now; do not "
              "start another step.")
        sys.exit(EXIT_CANCELLED)
    if r.get("ended") == "timed_out":
        print("TIMED OUT - this build already timed out waiting for an answer. Stop now.")
        sys.exit(EXIT_TIMEOUT)
    if r.get("ended"):
        print(f"  this build already ended ({r['ended']}) - nothing more to report for it")
        sys.exit(1)
    if not r.get("ok", True):
        print(f"  refused: {r.get('message') or r}")
        sys.exit(1)
    return r


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def run_child(a):
    """Run one child for the job. Its output streams to the job log in small batches; with
    --gates, the structured JTI-GATE lines become stage events and nothing is read from
    prose. Returns the child's exit code."""
    import signal
    import subprocess
    argv = a.argv[1:] if a.argv[:1] == ["--"] else a.argv
    if not argv:
        print("  run: nothing to run (give the command after --)")
        return 2
    if a.stage not in PERCENT:
        print(f"  unknown stage {a.stage!r}")
        return 2
    _checked(call("/api/worker/start", {"stage": a.stage,
                                         "status": f"Running {os.path.basename(argv[0])}"}))
    env = dict(os.environ, JTI_JOB_STAGES="1") if a.gates else dict(os.environ)
    # The gates use THIS checkout's templates. Without it, a harness looks for them by walking
    # up from the report folder and then in ~/.claude/plugins/cache - which is the INSTALLED
    # plugin, silently a different version than the one under test (found by --core-only).
    env.setdefault("JTI_PLUGIN", os.path.dirname(HERE))
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         bufsize=1, env=env, start_new_session=True)
    cancelled = threading.Event()

    def stop_child():
        """The child runs in its own process group: stop the whole group, politely first."""
        cancelled.set()
        for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            try:
                p.wait(wait)
                return
            except subprocess.TimeoutExpired:
                continue

    def ck(r):
        if r.get("cancel"):
            stop_child()
        return _checked(r)                     # exits 6 on cancel - the child is gone first

    def watch():
        while p.poll() is None and not cancelled.is_set():
            if call("/api/worker/ping").get("cancel"):
                stop_child()
                return
            time.sleep(0.5)
    ck(call("/api/worker/child", {"pid": p.pid, "stage": a.stage}))
    threading.Thread(target=watch, daemon=True).start()
    buf, last = [], time.monotonic()

    def flush():
        nonlocal buf, last
        if buf:
            ck(call("/api/worker/log", {"message": "\n".join(buf)}))
        buf, last = [], time.monotonic()

    for line in p.stdout:
        line = line.rstrip("\n")
        print(line, flush=True)
        if a.gates and line.startswith("JTI-GATE "):
            flush()
            parts = line.split(" ", 3)
            kind, gate = parts[1], (parts[2] if len(parts) > 2 else "")
            ck(call("/api/worker/gate", {"kind": kind, "gate": gate,
                                          "message": parts[3] if len(parts) > 3 else ""}))
            continue
        buf.append(line)
        if len(buf) >= 40 or time.monotonic() - last > 0.5:
            flush()
    rc = p.wait()
    if cancelled.is_set():
        print(f"CANCELLED - the user cancelled this build; {os.path.basename(argv[0])} was "
              f"stopped. Stop now; do not start another step.")
        return EXIT_CANCELLED
    flush()
    ck(call("/api/worker/child", {"pid": None, "stage": a.stage, "rc": rc}))
    if not a.gates and rc == 0:
        # A step that succeeded is DONE - reported here, not left to a separate `done` call
        # a worker can forget (the Defendant_Test build left "Report scaffolded" unticked).
        # The gates report their own stages from JTI-GATE lines.
        _checked(call("/api/worker/done", {"stage": a.stage,
                                            "status": "Finished"}))
    if a.gates and rc == 0:
        rule, jrxml = argv[1], argv[2]
        files = {f: sha(f) for f in [rule, jrxml] + sorted(
            n for n in os.listdir(".") if n.startswith("RULE-") and n.endswith(".zip"))
            if os.path.isfile(f)}
        _checked(call("/api/worker/gates", {"ok": True, "cwd": os.getcwd(), "files": files}))
    return rc


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="jobs.py", add_help=True)
    sub = ap.add_subparsers(dest="cmd")
    w = sub.add_parser("wait"); w.add_argument("--secs", type=int, default=540)
    for name in ("start", "done"):
        x = sub.add_parser(name); x.add_argument("stage"); x.add_argument("status", nargs="?", default="")
    lg = sub.add_parser("log"); lg.add_argument("message")
    lg.add_argument("--level", default="info", choices=LEVELS)
    f = sub.add_parser("fail"); f.add_argument("--stage", required=True)
    f.add_argument("--message", required=True); f.add_argument("--retryable", action="store_true")
    f.add_argument("--attempts", type=int, default=0)
    sub.add_parser("complete"); sub.add_parser("status")
    q = sub.add_parser("ask")
    q.add_argument("--id", required=True); q.add_argument("--title", required=True)
    q.add_argument("--prompt", required=True); q.add_argument("--type", required=True, choices=QTYPES)
    q.add_argument("--option", action="append", default=[])
    q.add_argument("--allow-text", action="store_true"); q.add_argument("--optional", action="store_true")
    q.add_argument("--timeout", type=int, default=3600)
    rn = sub.add_parser("run"); rn.add_argument("--stage", required=True)
    rn.add_argument("--gates", action="store_true"); rn.add_argument("argv", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)

    if a.cmd == "wait":
        deadline = time.monotonic() + a.secs
        while True:
            left = int(deadline - time.monotonic())
            if left <= 0:
                print("NO JOB YET - nothing was submitted. Run `jobs.py wait` again.")
                return EXIT_NOJOB
            r = call("/api/worker/claim", {"secs": min(left, 50)}, timeout=70)
            if r.get("finished"):
                why = ("the builder page was closed" if r.get("reason") == "closed"
                       else "they clicked Done on the builder page")
                print(f"USER IS DONE - {why}. Stop waiting: say the one closing line in the "
                      "chat and end. Do not run `wait` again.")
                return EXIT_DONE
            if r.get("job"):
                print(json.dumps(r["job"], indent=2))
                return 0
    if a.cmd in ("start", "done"):
        if a.stage not in PERCENT:
            print(f"  unknown stage {a.stage!r}; stages: {', '.join(PERCENT)}")
            return 2
        _checked(call(f"/api/worker/{a.cmd}", {"stage": a.stage, "status": a.status}))
        return 0
    if a.cmd == "log":
        _checked(call("/api/worker/log", {"message": a.message, "level": a.level}))
        return 0
    if a.cmd == "fail":
        _checked(call("/api/worker/fail", {"stage": a.stage, "message": a.message,
                                           "retryable": a.retryable, "attempts": a.attempts}))
        print(f"  job marked FAILED at {a.stage}")
        return 0
    if a.cmd == "complete":
        r = _checked(call("/api/worker/complete"))
        print(f"  job COMPLETE - {len(r.get('artifacts') or [])} deliverable(s) registered")
        return 0
    if a.cmd == "run":
        return run_child(a)
    if a.cmd == "ask":
        opts = []
        for o in a.option:
            v, _, lab = o.partition("=")
            opts.append({"value": v, "label": lab or v})
        _checked(call("/api/worker/ask", {"timeout": a.timeout, "question": {
            "id": a.id, "title": a.title, "prompt": a.prompt, "type": a.type, "options": opts,
            "allowText": a.allow_text, "required": not a.optional}}))
        print(f"  asked in the browser: {a.title} - waiting for the answer "
              f"(up to {a.timeout // 60} min)", flush=True)
        while True:
            r = _checked(call("/api/worker/answer", {"id": a.id, "secs": 50}, timeout=70))
            if r.get("timeout"):
                print("TIMED OUT - nobody answered in the browser. The job is now marked timed "
                      "out; stop the build.")
                return EXIT_TIMEOUT
            if r.get("answer") is not None:
                print(json.dumps(r["answer"], indent=2))
                return 0
    if a.cmd == "status":
        print(json.dumps(_checked(call("/api/worker/status")).get("job"), indent=2))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
