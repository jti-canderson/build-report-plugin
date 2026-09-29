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
    run_phase1(check, skip, ctx)
    run_phase2(check, skip, ctx)
    run_phase3(check, skip, ctx)


def run_phase1(check, skip, ctx):
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


# ── phase 2: event transport and gate-driven stages ──────────────────────────────────
def probe_job(plugin, ctx, srv, ws, name="Probe_Report"):
    """Submit the known-good probe report as a job, claim it, and do what the worker does
    before the gates: scaffold, write the rule, give the fixture real rows."""
    import re
    good = json.load(open(os.path.join(ctx["fix"], "good_spec.json")))
    spec = spec_for(name)
    spec.update({k: good[k] for k in ("sections", "params", "template", "root", "id")})
    code, d = srv.submit(spec)
    assert code == 200, d
    c = helper(plugin, ws, "wait", "--secs", "10")
    folder = json.loads(c.stdout)["folder"]
    subprocess.run([sys.executable, os.path.join(plugin, "scripts", "scaffold.py"),
                    os.path.join(folder, "spec.json"), "--out", folder],
                   capture_output=True, check=True)
    shutil.copy(os.path.join(ctx["fix"], "good_rule.groovy"), os.path.join(folder, f"{name}_V1.groovy"))
    fx = os.path.join(folder, "verification", "fixture.py")
    t = open(fx).read()
    t = re.sub(r'ROWS = \[\n.*?\n\]', 'ROWS = [\n    ("CF-2026-00184", "Felony"),\n'
               '    ("CM-2026-01920", "Misdemeanor"),\n]', t, flags=re.S)
    t = re.sub(r'"(rptSubtitle|rptSlug)": "TODO [^"]*"', lambda m: f'"{m.group(1)}": "probe"', t)
    open(fx, "w").write(t)
    return d["job"], d["token"], folder


def gates_cmd(plugin, name="Probe_Report"):
    return [os.path.join(plugin, "scripts", "finish.sh"), f"{name}_V1.groovy", f"{name}.jrxml",
            "--code", name, "--name", name.replace("_", " ")]


def run_gates(plugin, ws, folder, name="Probe_Report", stage="contract"):
    return subprocess.run([sys.executable, os.path.join(plugin, "scripts", "jobs.py"), "run",
                           "--stage", stage, "--gates", "--", *gates_cmd(plugin, name)],
                          cwd=folder, env=dict(os.environ, JTI_PROJECT_ROOT=ws),
                          capture_output=True, text=True, timeout=300)


def sse_first(srv, jid, tok, timeout=10):
    """Open the event stream, return the first snapshot, hang up."""
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=timeout)
    c.request("GET", f"/api/jobs/{jid}/events?t={tok}")
    r = c.getresponse()
    data, ctype = None, r.getheader("Content-Type")
    while True:
        line = r.fp.readline().decode()
        if line.startswith("data: "):
            data = json.loads(line[6:])
            break
        if not line:
            break
    c.close()
    return ctype, data


def run_phase2(check, skip, ctx):
    plugin, root = ctx["plugin"], ctx["ws"]
    if not ctx["jrs"]:
        return skip("jobs: gate-driven stages", "no JasperReports install")
    ws = fresh_ws(root, "gates")
    srv = Server(plugin, ws).start()
    try:
        jid, tok, folder = probe_job(plugin, ctx, srv, ws)
        ctype, first = sse_first(srv, jid, tok)
        check("jobs: the event stream is text/event-stream and opens with a full snapshot",
              ctype == "text/event-stream" and first and first["id"] == jid
              and first["status"] == "running", ctype)
        r = run_gates(plugin, ws, folder)
        j = srv.snap(jid, tok)
        kinds = [(e["kind"], e["stage"]) for e in j["events"]]
        done = [e["stage"] for e in j["events"] if e["kind"] == "done"]
        check("jobs: finish.sh's structured JTI-GATE lines drive the stages, in order, to 93%",
              r.returncode == 0 and done == ["contract", "rule", "render", "truncation", "package"]
              and j["percent"] == 93 and ("gates_passed", "package") in kinds
              and set((j["gates"] or {}).get("files", {})) >= {"Probe_Report_V1.groovy",
                                                                "Probe_Report.jrxml"},
              r.stdout[-600:] + json.dumps(kinds))
        check("jobs: the gates' output reaches the job log, not the event list",
              any("All gates passed" in ln for ln in j["log_tail"])
              and not any("All gates passed" in e["status"] for e in j["events"]), j["log_tail"][-5:])
        # reconnect: a new stream starts from the CURRENT state, not from zero
        _, again = sse_first(srv, jid, tok)
        check("jobs: reconnecting to the stream returns the current state (a refresh)",
              again and again["percent"] == 93 and again["events"] == j["events"], "")

        # a failing gate: reported as a failure of THAT stage, never as progress past it
        ctx["edit"](os.path.join(folder, "Probe_Report_V1.groovy"), "_data = rows", "data = rows")
        r = run_gates(plugin, ws, folder)
        j = srv.snap(jid, tok)
        gf = [e for e in j["events"] if e["kind"] == "gate_failed"]
        check("jobs: a failed gate is an error event naming the stage; the earlier pass is void",
              r.returncode == 1 and gf and gf[-1]["stage"] == "contract" and gf[-1]["level"] == "error"
              and j["gates"] is None and j["status"] == "running", json.dumps(gf))
        f = helper(plugin, ws, "fail", "--stage", "contract", "--message",
                   "the rule and the layout disagree", "--attempts", "1")
        j = srv.snap(jid, tok)
        check("jobs: `fail` ends the job as FAILED with the stage, message and a log excerpt",
              f.returncode == 0 and j["status"] == "failed" and j["failure"]["stage"] == "contract"
              and "GATE 1 FAILED" in j["failure"]["excerpt"] and j["failure"]["auto_attempts"] == 1,
              j.get("failure"))
        ctype, last = sse_first(srv, jid, tok)
        check("jobs: a finished job's stream sends its final state (and then ends)",
              last and last["status"] == "failed", "")
    finally:
        srv.stop()
    # without the wrapper the gates print exactly what they always did
    out = subprocess.run(gates_cmd(plugin), cwd=folder, capture_output=True, text=True).stdout
    check("jobs: finish.sh prints no JTI-GATE lines unless a job wrapper asks for them",
          "JTI-GATE" not in out and "GATE 1 FAILED" in out, out[-300:])


# ── phase 3: questions asked in the browser ──────────────────────────────────────────
def wait_for(fn, secs=10):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return None


def run_phase3(check, skip, ctx):
    plugin, root = ctx["plugin"], ctx["ws"]
    ws = fresh_ws(root, "ask")
    srv = Server(plugin, ws).start()
    try:
        code, d = srv.submit(spec_for("Ask_Probe"))
        jid, tok = d["job"], d["token"]
        helper(plugin, ws, "wait", "--secs", "10")
        H = {"X-JTI-Job": tok}
        # 1. a single-choice question, answered in the browser
        p = helper(plugin, ws, "ask", "--id", "sdk-required", "--title", "Field list needed",
                   "--prompt", "Which SDK should this report use?", "--type", "choice",
                   "--option", "current=Still current", "--option", "newer=I'll upload a newer one",
                   background=True)
        q = wait_for(lambda: (srv.snap(jid, tok) or {}).get("question"))
        s1 = srv.snap(jid, tok)
        c_bad, _ = srv.js("POST", f"/api/jobs/{jid}/answer", {"id": "sdk-required", "value": "zzz"}, H)
        c_tok, _ = srv.js("POST", f"/api/jobs/{jid}/answer", {"id": "sdk-required", "value": "current"})
        c_ok, _ = srv.js("POST", f"/api/jobs/{jid}/answer", {"id": "sdk-required", "value": "current"}, H)
        out, _ = p.communicate(timeout=30)
        ans = json.loads(out[out.index("{"):]) if "{" in out else {}
        check("jobs: a question blocks the worker until the browser answers it",
              q and q["type"] == "choice" and [o["value"] for o in q["options"]] == ["current", "newer"]
              and s1["status"] == "waiting" and c_ok == 200 and p.returncode == 0
              and ans.get("value") == "current", out)
        check("jobs: an answer that is not an option (400), or has no job token (403), is refused",
              c_bad == 400 and c_tok == 403, (c_bad, c_tok))
        s2 = srv.snap(jid, tok)
        check("jobs: after the answer the job is running again and the question is gone",
              s2["status"] == "running" and s2["question"] is None
              and [e["kind"] for e in s2["events"]][-2:] == ["question", "answered"], s2["status"])

        # 2. two questions in sequence - text, then longer text - and a refresh in between
        p = helper(plugin, ws, "ask", "--id", "title", "--title", "Report heading",
                   "--prompt", "What should the page heading say?", "--type", "text",
                   background=True)
        wait_for(lambda: (srv.snap(jid, tok) or {}).get("question"))
        srv.stop(); srv.start()                         # the page and the server both "refresh"
        H = {"X-JTI-Job": tok}
        reread = srv.snap(jid, tok)
        # the worker's long-poll lost its connection with the restart; it retries by design
        c1, _ = srv.js("POST", f"/api/jobs/{jid}/answer", {"id": "title", "text": "Open Cases"}, H)
        out1, _ = p.communicate(timeout=90)
        p = helper(plugin, ws, "ask", "--id", "notes", "--title", "Anything else?",
                   "--prompt", "Describe any special handling.", "--type", "longtext",
                   "--optional", background=True)
        wait_for(lambda: ((srv.snap(jid, tok) or {}).get("question") or {}).get("id") == "notes")
        c2, _ = srv.js("POST", f"/api/jobs/{jid}/answer", {"id": "notes", "text": "Line one\nLine two"}, H)
        out2, _ = p.communicate(timeout=30)
        check("jobs: two questions in sequence, answered after a server restart and a reload",
              reread and (reread.get("question") or {}).get("id") == "title" and c1 == 200 and c2 == 200
              and '"Open Cases"' in out1 and "Line two" in out2, out1[-200:] + out2[-200:])

        # 3. a file question - the SDK the build genuinely needs
        p = helper(plugin, ws, "ask", "--id", "sdk-file", "--title", "Upload the SDK",
                   "--prompt", "Send the ecourt-sdk jar.", "--type", "file", background=True)
        wait_for(lambda: ((srv.snap(jid, tok) or {}).get("question") or {}).get("id") == "sdk-file")
        code, _, body = srv.req("POST", f"/api/jobs/{jid}/upload?q=sdk-file", raw=b"PK\x03\x04jar",
                                headers={"X-JTI-Job": tok, "X-JTI-Filename": "../../evil%2F..%2Fsdk.jar",
                                         "Content-Type": "application/octet-stream"})
        out3, _ = p.communicate(timeout=30)
        a3 = json.loads(out3[out3.index("{"):]) if "{" in out3 else {}
        up = os.path.join(ws, "Proj", "Ask_Probe", ".jti-build", "uploads")
        check("jobs: a file answer is saved under the job's own upload folder with a safe name",
              code == 200 and a3.get("file", "").startswith(os.path.realpath(up) + os.sep)
              and os.path.basename(a3["file"]) == "sdk.jar" and open(a3["file"], "rb").read() == b"PK\x03\x04jar",
              out3)

        # 4. nobody answers: the job TIMES OUT, visibly, and a late answer is refused
        r = helper(plugin, ws, "ask", "--id", "late", "--title", "Quick one", "--prompt", "?",
                   "--type", "text", "--timeout", "2", timeout=30)
        s4 = srv.snap(jid, tok)
        c_late, _ = srv.js("POST", f"/api/jobs/{jid}/answer", {"id": "late", "text": "too late"}, H)
        check("jobs: an unanswered question times out: exit 5, job TIMED_OUT, late answer refused",
              r.returncode == 5 and s4["status"] == "timed_out" and s4["question"] is None
              and s4["timed_out"]["question"] == "late" and c_late == 409, r.stdout)
    finally:
        srv.stop()
