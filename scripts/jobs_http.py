"""jobs_http.py - the job routes serve_builder.py adds in --jobs mode (/test-report only; port 8789).

Browser routes need the SESSION token (from /api/bootstrap) to submit, and the job's own
TOKEN for everything about that job. Worker routes need the WORKER token, which only exists
in <workspace>/.jti-builder/server.json (mode 0600). The browser can ask for predefined
actions only - there is no route that takes a command or a filesystem path.
"""
import json
import pathlib
import re
import time
import urllib.parse

import jobs as J

MAX_JSON = 1 * 1024 * 1024
JOB_PATH = re.compile(r"^/api/jobs/([0-9a-f]{16})(/[a-z]+)?(/[a-z0-9]+)?$")


class Refuse(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def body_json(h):
    n = h.headers.get("Content-Length")
    if n is None:
        raise Refuse(411, "Content-Length is required")
    try:
        n = int(n)
    except ValueError:
        raise Refuse(400, "bad Content-Length")
    if n < 0 or n > MAX_JSON:
        raise Refuse(413, f"request body over {MAX_JSON} bytes")
    try:
        d = json.loads(h.rfile.read(n) or b"{}")
    except ValueError:
        raise Refuse(400, "bad JSON")
    if not isinstance(d, dict):
        raise Refuse(400, "expected a JSON object")
    return d


def job_for(store, jid, token):
    j = store.get(jid)
    if not j:
        raise Refuse(404, "no such job")
    if not token or not J.same(J.digest(token), j["token_sha256"]):
        raise Refuse(403, "job token missing or wrong")
    return j


class Routes:
    def __init__(self, store, app):
        self.s = store
        self.app = app               # serve_builder module: destination checks, spec writing

    # ------------------------------------------------------------------ dispatch
    def handle(self, h, method):
        u = urllib.parse.urlparse(h.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path.startswith("/api/worker/"):
                if method != "POST":
                    raise Refuse(405, "POST only")
                if not J.same(h.headers.get("X-JTI-Worker"), self.s.worker_token):
                    raise Refuse(403, "worker token missing or wrong")
                return self.worker(h, u.path[len("/api/worker/"):], body_json(h))
            if u.path == "/api/jobs":
                if method != "POST":
                    raise Refuse(405, "POST only")
                self.need_session(h)
                return self.submit(h, body_json(h))
            m = JOB_PATH.match(u.path)
            if m:
                return self.job_route(h, method, m.group(1), (m.group(2) or "")[1:],
                                      (m.group(3) or "")[1:], q)
            return False
        except Refuse as e:
            h._send(e.code, json.dumps({"ok": False, "message": e.message}))
            return True

    def need_session(self, h):
        if not J.same(h.headers.get("X-JTI-Session"), self.s.session_token):
            raise Refuse(403, "session token missing or wrong - reload the page")

    # ------------------------------------------------------------------ browser
    def submit(self, h, payload):
        with self.s.lock:
            cur = self.s.active()
            if cur:
                raise Refuse(409, f"A build is already running ({cur['report']['name']}). "
                                  f"This first version runs one build at a time - wait for "
                                  f"it to finish, or cancel it.")
            folder, err = self.app.report_folder(payload)
            if err:
                raise Refuse(400, err)
            pre, err = self.preexisting(folder)
            if err:
                raise Refuse(409, err)
            ok, msg = self.app.write_spec(payload)
            if not ok:
                raise Refuse(400, msg)
            report = {"name": payload["name"].strip(),
                      "title": (payload.get("title") or "").strip()
                      or payload["name"].strip().replace("_", " "),
                      "folder": str(folder), "destination": str(folder.parent)}
            j, tok = self.s.create(report, "spec.json", pre)
        h._send(200, json.dumps({"ok": True, "job": j["id"], "token": tok,
                                 "folder": report["folder"]}))
        return True

    def preexisting(self, folder):
        """What is already in the report folder. Refuse to build over a real report; allow a
        folder that only holds what an earlier unfinished builder job left behind."""
        folder = pathlib.Path(folder)
        if folder.is_symlink():
            return None, f"{folder} is a symlink - pick a real folder"
        if not folder.exists():
            return [], None
        prior = J.Store._read(folder / ".jti-build" / "job.json")
        files = [str(p.relative_to(folder)) for p in folder.rglob("*")
                 if p.is_file() and not str(p.relative_to(folder)).startswith(".jti-build")]
        ours = prior and prior.get("status") in ("failed", "cancelled", "timed_out")
        real = [f for f in files if f.endswith((".jrxml", ".groovy")) or f.startswith("RULE-")]
        if real and not ours:
            return None, (f"{folder.name} already holds a report ({real[0]}). Pick another "
                          f"report name - an existing report is never overwritten.")
        return files, None

    def job_route(self, h, method, jid, action, arg, q):
        token = h.headers.get("X-JTI-Job") if method == "POST" else (q.get("t") or [""])[0]
        j = job_for(self.s, jid, token)
        if method == "GET" and action == "":
            h._send(200, json.dumps({"ok": True, "job": self.s.public(j)}))
            return True
        if method == "GET" and action == "events":
            return self.stream(h, jid)
        raise Refuse(404, "no such action")

    def stream(self, h, jid):
        """Server-sent events: one full snapshot whenever the job changes, a comment every
        15 s otherwise. A snapshot rather than a diff, so a page that reconnects (refresh,
        sleep, network blip) is correct from its first message; EventSource reconnects on
        its own. The stream ends once a finished job has been sent."""
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Content-Type-Options", "nosniff")
        h.end_headers()
        last, t_ping = None, time.monotonic()
        try:
            h.wfile.write(b"retry: 2000\n\n")
            while True:
                with self.s.lock:
                    j = self.s.get(jid)
                    key = (len(j["events"]), j["updated"])
                    if key == last:
                        self.s.changed.wait(timeout=1.0)
                        j = self.s.get(jid)
                        key = (len(j["events"]), j["updated"])
                    snap = self.s.public(j) if key != last else None
                if snap is not None:
                    last = key
                    seq = snap["events"][-1]["seq"] if snap["events"] else 0
                    h.wfile.write(f"id: {seq}\nevent: snapshot\ndata: {json.dumps(snap)}\n\n"
                                  .encode())
                    h.wfile.flush()
                    if snap["status"] in J.TERMINAL:
                        return True
                elif time.monotonic() - t_ping > 15:
                    h.wfile.write(b": ping\n\n"); h.wfile.flush()
                    t_ping = time.monotonic()
                if h._peer_gone():
                    return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return True

    # ------------------------------------------------------------------ worker
    def worker(self, h, action, b):
        s = self.s
        if action == "claim":
            j = s.claim(min(max(int(b.get("secs") or 50), 1), 55))
            h._send(200, json.dumps({"ok": True, "job": self.claimed(j) if j else None}))
            return True
        with s.lock:
            j = s.worker_job()
            if not j:
                raise Refuse(409, "no claimed job - run `jobs.py wait` first")
            j["worker_seen"] = time.time()
            if j["cancel_requested"] and j["status"] not in J.TERMINAL:
                self.finish_cancel(j)
            if j["status"] == "cancelled":
                s.save(j)
                h._send(200, json.dumps({"ok": True, "cancel": True}))
                return True
            reply = self.worker_action(j, action, b)
            s.save(j)
        h._send(200, json.dumps({"ok": True, "cancel": False, **(reply or {})}))
        return True

    def worker_action(self, j, action, b):
        s = self.s
        stage = b.get("stage")
        if action in ("start", "done"):
            if stage not in J.PERCENT:
                raise Refuse(400, f"unknown stage {stage!r}")
            (s.start if action == "start" else s.done)(j, stage, b.get("status") or "")
            return None
        if action == "log":
            s.log(j, b.get("message", ""))
            lvl = b.get("level") if b.get("level") in J.LEVELS else "info"
            if lvl != "info":
                s.event(j, "log", None, J.clip(b.get("message", "")), lvl)
            return None
        if action == "fail":
            s.fail(j, stage if stage in J.PERCENT else j["stage"], b.get("message", ""),
                   excerpt="\n".join(s.log_tail(j, 40)), retryable=b.get("retryable"),
                   attempts=b.get("attempts"))
            return None
        if action == "gate":
            if b.get("kind") not in ("started", "passed", "failed", "warn"):
                raise Refuse(400, "bad gate event")
            s.gate(j, b["kind"], str(b.get("gate") or ""), b.get("message") or "")
            return None
        if action == "child":
            pid = b.get("pid")
            j["child"] = {"pid": int(pid), "stage": stage, "since": time.time()} \
                if isinstance(pid, int) else None
            return None
        if action == "gates":
            return self.record_gates(j, b)
        if action == "complete":
            return self.complete(j)
        if action == "status":
            return {"job": s.public(j)}
        raise Refuse(404, f"no worker action {action!r}")

    def claimed(self, j):
        folder = pathlib.Path(j["report"]["folder"])
        spec = J.Store._read(folder / j["spec"]) or {}
        return {"id": j["id"], "folder": str(folder), "spec_path": str(folder / j["spec"]),
                "spec": spec, "destination": j["report"]["destination"],
                "helper": str(pathlib.Path(J.HERE) / "jobs.py")}

    def record_gates(self, j, b):
        """Every gate passed. The SERVER hashes what was verified - the rule, the .jrxml and
        the zip, by bare file name inside the job's own folder - so completion can later
        prove the delivered files are the verified ones."""
        folder = pathlib.Path(j["report"]["folder"]).resolve()
        if pathlib.Path(str(b.get("cwd") or "")).resolve() != folder:
            raise Refuse(400, "the gates did not run in this job's report folder")
        files = {}
        for name in b.get("files") or {}:
            if not isinstance(name, str) or "/" in name or name.startswith("."):
                raise Refuse(400, f"bad file name {name!r}")
            p = folder / name
            if p.is_symlink() or not p.is_file():
                raise Refuse(400, f"{name} is not a regular file in the report folder")
            files[name] = J.sha(str(p))
        j["gates"] = {"ok": True, "files": files, "at": time.time()}
        self.s.event(j, "gates_passed", "package", "Every gate passed")
        return None

    def complete(self, j):
        s = self.s
        s.done(j, "complete", "Complete")
        j["status"], j["running"] = "complete", False
        return {"artifacts": j["artifacts"]}

    def finish_cancel(self, j):
        j["status"], j["running"] = "cancelled", False
        j["partial"] = self.s.created_files(j)
        j["status_text"] = "Cancelled"
        self.s.event(j, "cancelled", j["stage"], "Cancelled - nothing was deleted", "warn")
