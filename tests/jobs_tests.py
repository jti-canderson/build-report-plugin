"""The /test-report job coordinator: browser <-> server <-> jobs.py (the worker's helper).

Called from tests/run.py (core tier). Every test runs a real serve_builder.py --jobs on a
free port against a temp workspace, drives the browser side over HTTP and the worker side
through the real jobs.py CLI. Nothing here needs a browser or a Claude session.
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


class Server:
    def __init__(self, plugin, ws, jobs=True):
        self.plugin, self.ws, self.jobs = plugin, ws, jobs
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        self.base = f"http://127.0.0.1:{self.port}"
        self.p = None

    def start(self):
        cmd = [sys.executable, os.path.join(self.plugin, "scripts", "serve_builder.py"),
               "--port", str(self.port), "--no-open"] + (["--jobs"] if self.jobs else [])
        self.p = subprocess.Popen(cmd, env=dict(os.environ, JTI_PROJECT_ROOT=self.ws),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                self.boot = json.loads(self.get("/api/bootstrap")[2])
                self.session = (self.boot.get("jobs") or {}).get("session")
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    def stop(self):
        if self.p:
            self.p.terminate(); self.p.wait(10); self.p = None

    def req(self, method, path, body=None, headers=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = {"Content-Type": "application/json"} if data is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def get(self, path, headers=None):
        return self.req("GET", path, headers=headers)

    def js(self, method, path, body=None, headers=None):
        code, _, b = self.req(method, path, body, headers)
        try:
            return code, json.loads(b or b"{}")
        except ValueError:
            return code, {"raw": b[:200]}

    def submit(self, spec):
        return self.js("POST", "/api/jobs", spec, {"X-JTI-Session": self.session})

    def snap(self, jid, tok):
        code, d = self.js("GET", f"/api/jobs/{jid}?t={tok}")
        return d.get("job") if code == 200 else None


def helper(plugin, ws, *args, timeout=120, background=False):
    cmd = [sys.executable, os.path.join(plugin, "scripts", "jobs.py"), *args]
    env = dict(os.environ, JTI_PROJECT_ROOT=ws)
    if background:
        return subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def spec_for(name, project="Proj"):
    return {"project": project, "name": name, "title": name.replace("_", " "),
            "template": "tabular_list", "intent": "", "look": "", "meta": [], "tiles": [],
            "variants": ["full", "none"], "root": "Case", "id": "19",
            "sections": [{"key": "ROWS", "title": "Rows",
                          "cols": [["Case Number", 40, "Left", "caseNumber"],
                                   ["Case Type", 60, "Left", "caseType"]]}],
            "params": [["CaseType", "java.lang.String"]]}


def fresh_ws(root, tag):
    ws = os.path.join(os.path.realpath(root), "jobs_" + tag)
    os.makedirs(os.path.join(ws, "Proj"))
    open(os.path.join(ws, ".jti-root"), "w").close()
    return ws


def run(check, skip, ctx):
    plugin, root = ctx["plugin"], ctx["ws"]

    # ---- submit -> claim -> progress -> complete, with honest, ordered progress -------
    ws = fresh_ws(root, "flow")
    srv = Server(plugin, ws).start()
    try:
        code, d = srv.submit(spec_for("Flow_Probe"))
        jid, tok = d.get("job"), d.get("token")
        folder = os.path.join(ws, "Proj", "Flow_Probe")
        c = helper(plugin, ws, "wait", "--secs", "10")
        claimed = json.loads(c.stdout) if c.returncode == 0 else {}
        steps = [("done", "validated", "Spec read"), ("start", "destination", "Checking"),
                 ("done", "destination", "SDK current"), ("done", "fixtures", "Rows written"),
                 ("done", "validated", "late duplicate - must not lower percent")]
        rcs = [helper(plugin, ws, *s).returncode for s in steps]
        j = srv.snap(jid, tok)
        ev = j["events"] if j else []
        pct = [e["percent"] for e in ev]
        check("jobs: submit returns a random id + token; the worker claims it with the spec",
              code == 200 and len(jid or "") == 16 and len(tok or "") >= 24
              and claimed.get("id") == jid and claimed.get("folder") == folder
              and claimed.get("spec", {}).get("name") == "Flow_Probe"
              and os.path.isfile(os.path.join(folder, "spec.json")), f"{code} {d} {c.stdout[:200]}")
        check("jobs: progress events are ordered (seq 1..n) and percent never goes down",
              all(r == 0 for r in rcs) and [e["seq"] for e in ev] == list(range(1, len(ev) + 1))
              and pct == sorted(pct) and j["percent"] == 55
              and [e["kind"] for e in ev][:3] == ["submitted", "claimed", "done"], ev)
        check("jobs: percent is the stage table value of work DONE, not a timer",
              [e["percent"] for e in ev if e["kind"] == "done"] == [5, 12, 55, 55]
              and next(e for e in ev if e["kind"] == "start")["percent"] == 5, pct)
        bad = helper(plugin, ws, "done", "nonsense")
        check("jobs: an unknown stage is refused (exit 2) and changes nothing",
              bad.returncode == 2 and len(srv.snap(jid, tok)["events"]) == len(ev), bad.stdout)

        # refresh: the same snapshot again, and a server RESTART loses nothing
        before = srv.snap(jid, tok)
        srv.stop(); srv.start()
        after = srv.snap(jid, tok)
        check("jobs: state is on disk - a refresh and a server restart both return the same job",
              after and after["events"] == before["events"] and after["percent"] == 55
              and after["status"] == "running"
              and os.path.isfile(os.path.join(folder, ".jti-build", "job.json")), after)
        # the worker is unaffected by the restart (its token persists)
        check("jobs: the worker keeps working across a server restart",
              helper(plugin, ws, "log", "after restart").returncode == 0, "")

        # tokens
        c1, _ = srv.js("GET", f"/api/jobs/{jid}")
        c2, _ = srv.js("GET", f"/api/jobs/{jid}?t=wrong-token-wrong-token")
        c3, _ = srv.js("POST", "/api/jobs", spec_for("No_Session"))
        c4, _ = srv.js("POST", "/api/jobs", spec_for("Bad_Session"), {"X-JTI-Session": "nope"})
        c5, _ = srv.js("POST", "/api/worker/done", {"stage": "render"})
        c6, _ = srv.js("POST", "/api/worker/done", {"stage": "render"}, {"X-JTI-Worker": "nope"})
        check("jobs: a missing or wrong job / session / worker token is refused (403)",
              [c1, c2, c3, c4, c5, c6] == [403] * 6, [c1, c2, c3, c4, c5, c6])

        # one build at a time
        c, d2 = srv.submit(spec_for("Second_Build"))
        check("jobs: a second submission while one runs is refused clearly (409), not queued",
              c == 409 and "already running" in d2.get("message", "")
              and not os.path.exists(os.path.join(ws, "Proj", "Second_Build")), d2)

        c = helper(plugin, ws, "complete")
        j = srv.snap(jid, tok)
        check("jobs: complete ends the job at 100%", c.returncode == 0 and j["status"] == "complete"
              and j["percent"] == 100, c.stdout)
        open(os.path.join(folder, "Flow_Probe.jrxml"), "w").write("<jasperReport/>")
        c, d3 = srv.submit(spec_for("Flow_Probe"))
        check("jobs: a folder that already holds a report is never built over (409)",
              c == 409 and "never overwritten" in d3.get("message", ""), d3)
    finally:
        srv.stop()

    # ---- /build-report is unchanged -------------------------------------------------
    ws = fresh_ws(root, "default")
    srv = Server(plugin, ws, jobs=False).start()
    try:
        c1, _ = srv.js("POST", "/api/jobs", spec_for("X"))
        c2, d = srv.js("POST", "/api/spec", spec_for("Old_Path"))
        check("default builder (the /build-report one): no job API, no session token, and "
              "/api/spec still writes a spec with no token",
              "jobs" not in srv.boot and c1 == 404 and c2 == 200 and d.get("ok")
              and os.path.isfile(os.path.join(ws, "Proj", "Old_Path", "spec.json")), (c1, c2, d))
    finally:
        srv.stop()
    md = os.path.join(plugin, "commands", "build-report.md")
    g = subprocess.run(["git", "-C", plugin, "show", "9bcbe03:commands/build-report.md"],
                       capture_output=True)
    if g.returncode == 0:
        check("commands/build-report.md is byte-identical to the pre-/test-report commit",
              hashlib.sha256(open(md, "rb").read()).hexdigest()
              == hashlib.sha256(g.stdout).hexdigest(), "build-report.md changed")
    else:
        skip("commands/build-report.md is unchanged", "no git history for commit 9bcbe03")
