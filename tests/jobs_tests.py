"""The /build-report job coordinator: browser <-> server <-> jobs.py (the worker's helper).

Called from tests/run.py (core tier). Every test runs a real serve_builder.py --jobs on a
free port against a temp workspace, drives the browser side over HTTP and the worker side
through the real jobs.py CLI. Nothing here needs a browser or a Claude session.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request


class Server:
    def __init__(self, plugin, ws, jobs=True, env=None):
        self.plugin, self.ws, self.jobs, self.env = plugin, ws, jobs, env or {}
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        self.base = f"http://127.0.0.1:{self.port}"
        self.p = None

    def start(self):
        cmd = [sys.executable, os.path.join(self.plugin, "scripts", "serve_builder.py"),
               "--port", str(self.port), "--no-open"] + (["--jobs"] if self.jobs else [])
        self.p = subprocess.Popen(cmd, env=dict(os.environ, JTI_PROJECT_ROOT=self.ws, **self.env),
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
    run_phase4(check, skip, ctx)
    run_revise(check, skip, ctx)
    run_phase5(check, skip, ctx)
    run_fields(check, skip, ctx)
    run_dd(check, skip, ctx)
    run_done(check, skip, ctx)
    run_closed(check, skip, ctx)
    run_marks_done(check, skip, ctx)
    run_replace(check, skip, ctx)


def run_replace(check, skip, ctx):
    """An update leaves the OLD copy's builder running: starting /build-report from the new
    copy replaces it when idle, and never while it holds a job."""
    plugin, root = ctx["plugin"], ctx["ws"]
    ws = fresh_ws(root, "replace")
    old = os.path.join(ws, "old-plugin")
    for d in ("scripts", "templates", "skills", ".claude-plugin"):
        shutil.copytree(os.path.join(plugin, d), os.path.join(old, d),
                        ignore=shutil.ignore_patterns("__pycache__", "examples"))
    a = Server(old, ws).start()
    b = Server(plugin, ws); b.port, b.base = a.port, a.base
    try:
        b.start()      # returns on the first bootstrap, which may still be the old server's
        mine = os.path.realpath(plugin)
        for _ in range(100):
            try:
                b.boot = json.loads(b.get("/api/bootstrap")[2])
                if b.boot.get("plugin") == mine:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        check("replace: an idle builder from another plugin copy is stopped and this copy serves",
              b.boot.get("plugin") == mine and a.p.wait(10) is not None, b.boot.get("plugin"))
        b.stop()
        a = Server(old, ws); a.port, a.base = b.port, b.base
        a.start()
        c, _ = a.submit(spec_for("Busy_Job"))
        again = subprocess.run([sys.executable, os.path.join(plugin, "scripts", "serve_builder.py"),
                                "--jobs", "--port", str(a.port), "--no-open"],
                               env=dict(os.environ, JTI_PROJECT_ROOT=ws),
                               capture_output=True, text=True, timeout=30)
        boot = json.loads(a.get("/api/bootstrap")[2])
        check("replace: a builder holding a job is kept, and the new copy says so and exits",
              c == 200 and again.returncode == 0 and "job in progress" in again.stdout
              and a.p.poll() is None and boot.get("plugin") == os.path.realpath(old),
              (c, again.returncode, again.stdout[-300:]))
    finally:
        a.stop(); b.stop()


def run_done(check, skip, ctx):
    """The page's Done button ends the /build-report worker - and ONLY a worker that is there."""
    plugin, root = ctx["plugin"], ctx["ws"]
    ws = fresh_ws(root, "done")
    srv = Server(plugin, ws).start()
    try:
        done = lambda h=None: srv.js("POST", "/api/session/done", {}, h or {"X-JTI-Session": srv.session})
        c, d = done()
        w = helper(plugin, ws, "wait", "--secs", "3")
        check("done: with no Claude connected it stops nothing, and a later wait is NOT ended by it",
              c == 200 and d.get("stopping") is False and w.returncode == 7, (c, d, w.returncode))
        c, _ = done({"X-JTI-Session": "nope"})
        check("done: refused without the page's session token", c == 403, c)

        bg = helper(plugin, ws, "wait", "--secs", "40", background=True)
        time.sleep(1.5)
        c, d = done()
        _, watch = srv.js("GET", "/api/watching")
        try:
            out, _ = bg.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            bg.kill(); out = "(still waiting)"
        check("done: a waiting worker exits 8 at once and is told to stop",
              d.get("stopping") is True and bg.returncode == 8 and "USER IS DONE" in out,
              (d, bg.returncode, out[-200:], watch))
        w = helper(plugin, ws, "wait", "--secs", "3")
        check("done: it is used up once collected - the next session's wait is not ended by it",
              w.returncode == 7, w.returncode)

        code, sub = srv.submit(spec_for("Done_Probe"))
        c, d = done()
        first = helper(plugin, ws, "wait", "--secs", "5")
        helper(plugin, ws, "fail", "--stage", "validated", "--message", "test stops here")
        second = helper(plugin, ws, "wait", "--secs", "10")
        check("done: a build already submitted is still picked up first; the wait after it ends the worker",
              d.get("stopping") is True and first.returncode == 0 and '"Done_Probe"' in first.stdout
              and second.returncode == 8, (d, first.returncode, second.returncode))
    finally:
        srv.stop()


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
              and os.path.isfile(os.path.join(folder, "verification", "spec.json")), f"{code} {d} {c.stdout[:200]}")
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
        check("jobs: `complete` is refused until the gates have passed - it cannot claim success",
              c.returncode == 1 and "gates have not passed" in c.stdout and j["status"] == "running"
              and j["artifacts"] == [], c.stdout)
        helper(plugin, ws, "fail", "--stage", "fixtures", "--message", "test stops here")
        open(os.path.join(folder, "Flow_Probe.jrxml"), "w").write("<jasperReport/>")
        c, d3 = srv.submit(spec_for("Flow_Probe"))
        check("jobs: a folder that already holds a report is never built over (409)",
              c == 409 and "never overwritten" in d3.get("message", ""), d3)
        bare = {"project": "Proj", "name": "Bare_Spec", "template": "tabular_list", "intent": "x"}
        c, d4 = srv.submit(bare)
        spec = json.load(open(os.path.join(ws, "Proj", "Bare_Spec", "verification", "spec.json"))) if c == 200 else {}
        check("jobs: a spec posted without the list fields gets empty lists, never null",
              c == 200 and spec.get("meta") == [] and spec.get("tiles") == []
              and spec.get("variants") == ["full", "none"], spec)
        helper(plugin, ws, "wait", "--secs", "5")
        helper(plugin, ws, "fail", "--stage", "validated", "--message", "test stops here")
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
              and os.path.isfile(os.path.join(ws, "Proj", "Old_Path", "verification", "spec.json")), (c1, c2, d))
    finally:
        srv.stop()
    md = open(os.path.join(plugin, "commands", "build-report.md"), encoding="utf8").read()
    alias = open(os.path.join(plugin, "commands", "test-report.md"), encoding="utf8").read()
    check("/build-report is the browser builder (job server), and /test-report is only an "
          "alias that follows it - one implementation",
          "--jobs" in md and '"$J" wait' in md and "${CLAUDE_PLUGIN_ROOT}" in md
          and "build-report.md" in alias and '"$J"' not in alias and "jobs.py" not in alias
          and len(alias.splitlines()) < 30, len(alias.splitlines()))
    stale = [f for f in ("scripts/app.js", "scripts/build_ui.js", "scripts/builder.html",
                         "scripts/jobs.py", "scripts/jobs_http.py", "scripts/serve_builder.py",
                         "commands/build-report.md", ".claude-plugin/plugin.json", "README.md")
             if re.search(r"/test-report(?!` is the old name)|unreleased|Test build|TEST BUILD",
                          open(os.path.join(plugin, f), encoding="utf8").read())]
    check("no test / unreleased labels left in the shipped builder, command or README", not stale, stale)
    app = open(os.path.join(plugin, "scripts", "app.js"), encoding="utf8").read()
    ok_branch = app[app.index("if (jobsMode && d.ok)"):][:600]
    check("a submitted build clears the form draft, so the next session opens on a clean form",
          "localStorage.removeItem(DRAFT)" in ok_branch, ok_branch[:200])


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
                    os.path.join(folder, "verification", "spec.json"), "--out", folder],
                   capture_output=True, check=True)
    shutil.copy(os.path.join(ctx["fix"], "good_rule.groovy"), os.path.join(folder, f"{name}_V1.groovy"))
    fx = os.path.join(folder, "verification", "fixture.py")
    t = open(fx).read()
    t = re.sub(r'ROWS = \[\n.*?\n\]', 'ROWS = [\n    ("CF-2026-00184", "Felony"),\n'
               '    ("CM-2026-01920", "Misdemeanor"),\n]', t, flags=re.S)
    t = re.sub(r'"(rptSubtitle|rptSlug)": "TODO [^"]*"', lambda m: f'"{m.group(1)}": "probe"', t)
    open(fx, "w").write(t)
    return d["job"], d["token"], folder


def fill_notes(plugin, folder):
    """What the worker does in the documentation stage: replace each untouched seed."""
    import re
    sys.path.insert(0, os.path.join(plugin, "scripts"))
    import contract_docs as CD
    for fn in ("JRXML_CONTRACT.txt", "RULE_REGISTRATION.txt"):
        p = os.path.join(folder, "verification", fn)
        t = open(p).read()
        m = re.search(re.escape(CD.BEGIN) + r"\n(.*?)\n" + re.escape(CD.END), t, re.S)
        if m and m.group(1).startswith("TODO before this ships"):
            open(p, "w").write(t[:m.start(1)] + "Filled by the test worker." + t[m.end(1):])


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
        check("jobs: finish.sh's structured JTI-GATE lines drive the stages, in order, to 93% - "
              "and tick the unreported rule stage first (the gates run on the rule)",
              r.returncode == 0 and done == ["plan", "contract", "rule", "render", "truncation", "package"]
              and j["percent"] == 93 and ("gates_passed", "package") in kinds
              and set((j["gates"] or {}).get("files", {})) >= {"Probe_Report_V1.groovy",
                                                                "Probe_Report.jrxml"},
              r.stdout[-600:] + json.dumps(kinds))
        sys.path.insert(0, os.path.join(plugin, "scripts"))
        import jobs as JM
        order = [k for k, *_ in JM.STAGES]
        check("jobs: scaffold comes before the rule stage (scaffold writes launch_inputs.groovy, "
              "which the rule starts with)",
              order.index("scaffold") < order.index("plan") < order.index("fixtures")
              and JM.PERCENT["scaffold"] < JM.PERCENT["plan"], order)
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
              and j["failure"]["label"] == "Contract check" and j["status_text"] == "Failed at: Contract check"
              and "GATE 1 FAILED" in j["failure"]["excerpt"] and j["failure"]["auto_attempts"] == 1,
              j.get("failure"))
        # a rebuild in the same folder (allowed: this job created the report files) starts clean
        code, d = srv.submit(json.load(open(os.path.join(folder, "verification", "spec.json"))) | {"project": "Proj"})
        again = srv.snap(d.get("job"), d.get("token")) if code == 200 else None
        check("jobs: a rebuild over an unfinished build's own files is allowed, with its own log",
              code == 200 and again and not any("GATE 1 FAILED" in ln for ln in again["log_tail"]),
              (code, d))
        if code == 200:
            helper(plugin, ws, "wait", "--secs", "5")
            helper(plugin, ws, "fail", "--stage", "validated", "--message", "test stops here")
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

        # 2b. the worker's shell call dies mid-wait; asking the SAME question resumes it
        p = helper(plugin, ws, "ask", "--id", "resume", "--title", "Resume", "--prompt", "?",
                   "--type", "text", background=True)
        first = wait_for(lambda: ((srv.snap(jid, tok) or {}).get("question") or {}).get("asked"))
        p.kill(); p.wait()
        p = helper(plugin, ws, "ask", "--id", "resume", "--title", "Resume", "--prompt", "?",
                   "--type", "text", background=True)
        time.sleep(1)
        again = (srv.snap(jid, tok) or {}).get("question") or {}
        srv.js("POST", f"/api/jobs/{jid}/answer", {"id": "resume", "text": "still here"}, H)
        outr, _ = p.communicate(timeout=30)
        check("jobs: re-running the same `ask` after a cut-off resumes it - not asked twice",
              again.get("asked") == first and p.returncode == 0 and "still here" in outr, outr)

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


# ── phase 4: artifacts, previews and downloads ───────────────────────────────────────
def raw_get(srv, path):
    """GET a path exactly as written (no client-side normalisation of .. or %2e)."""
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    c.putrequest("GET", path, skip_host=True)
    c.putheader("Host", f"127.0.0.1:{srv.port}")
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, dict(r.getheaders()), body


def run_phase4(check, skip, ctx):
    import io
    import zipfile
    plugin, root = ctx["plugin"], ctx["ws"]
    if not ctx["jrs"]:
        return skip("jobs: artifacts and downloads", "no JasperReports install")
    ws = fresh_ws(root, "arts")
    srv = Server(plugin, ws).start()
    try:
        jid, tok, folder = probe_job(plugin, ctx, srv, ws)
        t = "?t=" + tok
        r = run_gates(plugin, ws, folder)
        rule = os.path.join(folder, "Probe_Report_V1.groovy")
        orig = open(rule).read()
        open(rule, "a").write("\n// edited after the gates\n")
        c1 = helper(plugin, ws, "complete")
        open(rule, "w").write(orig)                        # back to exactly what was verified
        helper(plugin, ws, "done", "review", "Looked at every page")
        c_notes = helper(plugin, ws, "complete")           # NOTES still hold the TODO seed
        fill_notes(plugin, folder)
        helper(plugin, ws, "done", "documentation", "NOTES filled")
        c2 = helper(plugin, ws, "complete")
        check("jobs: completion is refused while a NOTES block still holds its TODO seed",
              c_notes.returncode == 1 and "unfilled NOTES seed" in c_notes.stdout, c_notes.stdout)
        j = srv.snap(jid, tok)
        kinds = sorted({a["kind"] for a in j["artifacts"]})
        check("jobs: a file edited after the gates passed blocks completion",
              r.returncode == 0 and c1.returncode == 1 and "changed after the gates passed" in c1.stdout,
              c1.stdout)
        check("jobs: a verified build completes at 100% with its deliverables registered",
              c2.returncode == 0 and j["status"] == "complete" and j["percent"] == 100
              and kinds == ["doc", "jrxml", "page", "pdf", "rule", "rule-zip"], (c2.stdout, kinds))
        check("jobs: the selected report folder stays the canonical output",
              all(os.path.isfile(os.path.join(folder, a["rel"])) for a in j["artifacts"])
              and not [f for f in os.listdir(os.path.join(ws, ".jti-builder"))
                       if f.endswith((".pdf", ".zip", ".jrxml", ".groovy"))], j["artifacts"])

        page = next(a for a in j["artifacts"] if a["kind"] == "page")
        code, hd, body = srv.get(f"/api/jobs/{jid}/preview/{page['id']}{t}")
        check("jobs: a page preview is served inline as a PNG",
              code == 200 and hd.get("Content-Type") == "image/png" and body[:4] == b"\x89PNG"
              and hd.get("Content-Disposition", "").startswith("inline"), (code, hd))
        zipa = next(a for a in j["artifacts"] if a["kind"] == "rule-zip")
        code, hd, body = srv.get(f"/api/jobs/{jid}/file/{zipa['id']}{t}")
        check("jobs: a file downloads as an attachment with a safe name, byte-identical",
              code == 200 and hd.get("Content-Disposition") == f'attachment; filename="{zipa["name"]}"'
              and body == open(os.path.join(folder, zipa["rel"]), "rb").read(), hd)
        code, hd, body = srv.get(f"/api/jobs/{jid}/package{t}")
        names = sorted(zipfile.ZipFile(io.BytesIO(body)).namelist()) if code == 200 else []
        check("jobs: the report package holds the rule, layout, zip, documents and PDFs (no PNGs)",
              code == 200 and hd.get("Content-Disposition") == 'attachment; filename="Probe_Report-package.zip"'
              and "Probe_Report_V1.groovy" in names and "Probe_Report.jrxml" in names
              and "verification/JRXML_CONTRACT.txt" in names and "verification/RULE_REGISTRATION.txt" in names
              and any(n.startswith("RULE-") for n in names)
              and any(n.endswith(".pdf") for n in names) and not any(n.endswith(".png") for n in names),
              names)

        # the allowlist: ids the server issued, for this job, with its token - nothing else
        probes = [f"/api/jobs/{jid}/file/a999{t}", f"/api/jobs/{jid}/file/../../../../etc/passwd{t}",
                  f"/api/jobs/{jid}/file/%2e%2e%2f%2e%2e%2fetc%2fpasswd{t}",
                  f"/api/jobs/{jid}/file/{zipa['rel']}{t}", f"/api/jobs/{jid}/preview/{zipa['id']}{t}",
                  f"/api/jobs/{jid}/file/{zipa['id']}?t=wrong", f"/api/jobs/{jid}/package",
                  f"/api/jobs/../../etc/passwd"]
        codes = [raw_get(srv, pth)[0] for pth in probes]
        check("jobs: unregistered ids, traversal, raw paths, a non-page preview and bad tokens are refused",
              codes[:5] == [404] * 5 and codes[5] == 403 and codes[6] == 403 and codes[7] == 404, codes)
        doc = next(a for a in j["artifacts"] if a["name"] == "JRXML_CONTRACT.txt")
        open(os.path.join(folder, doc["rel"]), "a").write("tampered\n")
        c_t = srv.get(f"/api/jobs/{jid}/file/{doc['id']}{t}")[0]
        pdf = next(a for a in j["artifacts"] if a["kind"] == "pdf")
        p = os.path.join(folder, pdf["rel"])
        os.replace(p, p + ".bak"); os.symlink("/etc/hosts", p)
        c_s = srv.get(f"/api/jobs/{jid}/file/{pdf['id']}{t}")[0]
        c_p = srv.get(f"/api/jobs/{jid}/package{t}")[0]
        check("jobs: a file changed, or swapped for a symlink, after completion is not served",
              c_t == 409 and c_s == 409 and c_p == 409, (c_t, c_s, c_p))
    finally:
        srv.stop()


# ── after a build: ask a question (answered in words) or request changes (rebuilt) ────
def run_revise(check, skip, ctx):
    plugin, root = ctx["plugin"], ctx["ws"]
    if not ctx["jrs"]:
        return skip("jobs: requesting changes after a build", "no JasperReports install")
    ws = fresh_ws(root, "revise")
    srv = Server(plugin, ws).start()
    try:
        jid, tok, folder = probe_job(plugin, ctx, srv, ws)
        hdr = {"X-JTI-Job": tok}
        early = srv.js("POST", f"/api/jobs/{jid}/revise", {"text": "too soon"}, hdr)
        run_gates(plugin, ws, folder)
        fill_notes(plugin, folder)
        c1 = helper(plugin, ws, "complete")
        # -- a question: answered on the page, the job and its downloads untouched
        before = srv.snap(jid, tok)
        q_bad = srv.js("POST", f"/api/jobs/{jid}/inquire", {"text": "x"}, {"X-JTI-Job": "nope"})[0]
        q_empty = srv.js("POST", f"/api/jobs/{jid}/inquire", {"text": " "}, hdr)[0]
        q_code, q_d = srv.js("POST", f"/api/jobs/{jid}/inquire", {"text": "Where does Type come from?"}, hdr)
        q_twice = srv.js("POST", f"/api/jobs/{jid}/inquire", {"text": "and another"}, hdr)[0]
        qw = helper(plugin, ws, "wait", "--secs", "10")
        qgot = json.loads(qw.stdout) if qw.returncode == 0 else {}
        mid = srv.snap(jid, tok)
        rp = helper(plugin, ws, "reply", "--job", jid, "--n", "1", "From the case's caseType.")
        rp2 = helper(plugin, ws, "reply", "--job", jid, "--n", "1", "again")
        after = srv.snap(jid, tok)
        art = after["artifacts"][0] if after["artifacts"] else {}
        dl = srv.get(f"/api/jobs/{jid}/file/{art.get('id')}?t={tok}")[0]
        check("jobs: a question about a finished report reaches the waiting worker with its text, "
              "is answered on the page, and changes nothing - still complete, same downloads",
              q_bad == 403 and q_empty == 409 and q_code == 200 and q_twice == 409
              and (qgot.get("inquiry") or {}).get("text") == "Where does Type come from?"
              and qgot.get("id") == jid and qgot.get("status") == "complete"
              and mid["status"] == "complete" and mid["artifacts"] == before["artifacts"]
              and rp.returncode == 0 and rp2.returncode == 1
              and after["inquiries"][0]["answer"] == "From the case's caseType."
              and after["status"] == "complete" and after["artifacts"] == before["artifacts"]
              and dl == 200, (q_bad, q_empty, q_code, q_twice, qw.stdout[-300:], rp.stdout, rp2.stdout))
        # -- a pasted screenshot: uploaded to the job's own folder, named by the server, and
        # passed to the worker as a path; anything that is not a real picture is refused
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
        a_code, _, a_body = srv.req("POST", f"/api/jobs/{jid}/attach", headers={"X-JTI-Job": tok,
                                    "Content-Type": "image/png"}, raw=png)
        pid = json.loads(a_body or b"{}").get("id", "")
        a_txt = srv.req("POST", f"/api/jobs/{jid}/attach", headers={"X-JTI-Job": tok,
                        "Content-Type": "text/plain"}, raw=b"hello")[0]
        a_fake = srv.req("POST", f"/api/jobs/{jid}/attach", headers={"X-JTI-Job": tok,
                         "Content-Type": "image/png"}, raw=b"not a png at all")[0]
        a_tok = srv.req("POST", f"/api/jobs/{jid}/attach", headers={"X-JTI-Job": "nope",
                        "Content-Type": "image/png"}, raw=png)[0]
        q_forged = srv.js("POST", f"/api/jobs/{jid}/inquire",
                          {"text": "see this", "images": ["../../../etc/passwd"]}, hdr)[0]
        q2 = srv.js("POST", f"/api/jobs/{jid}/inquire", {"text": "What is circled here?", "images": [pid]}, hdr)[0]
        q2w = helper(plugin, ws, "wait", "--secs", "10")
        q2got = (json.loads(q2w.stdout) if q2w.returncode == 0 else {}).get("inquiry") or {}
        q2img = (q2got.get("images") or [""])[0]
        helper(plugin, ws, "reply", "--job", jid, "--n", "2", "The case number.")
        check("jobs: a pasted screenshot is stored in the job's hidden folder under a server-made "
              "name and reaches the worker as a path; non-pictures, fakes, bad tokens and forged "
              "ids are refused",
              a_code == 200 and re.match(r"^img-\d+-[0-9a-f]{8}\.png$", pid) and a_txt == 415
              and a_fake == 400 and a_tok == 403 and q_forged == 400 and q2 == 200
              and q2got.get("text") == "What is circled here?"
              and q2img == os.path.join(folder, ".jti-build", "attachments", pid)
              and open(q2img, "rb").read() == png,
              (a_code, pid, a_txt, a_fake, a_tok, q_forged, q2, q2w.stdout[-300:]))
        # -- an attached FILE (picked or dropped): named by its extension, content checked
        # against it, stored under a server-made id that keeps the original name as its tail
        pdf = b"%PDF-1.4\n" + b"x" * 40
        def att(raw, name, ctype="application/octet-stream", token=tok):
            hd = {"X-JTI-Job": token, "Content-Type": ctype}
            if name is not None:
                hd["X-JTI-Name"] = urllib.parse.quote(name)
            c, _, body = srv.req("POST", f"/api/jobs/{jid}/attach", headers=hd, raw=raw)
            return c, json.loads(body or b"{}")
        f_pdf = att(pdf, "Old report (v2).pdf")
        f_csv = att(b"case,total\n1,2\n", "expected.csv")
        f_exe = att(b"MZ\x90\x00", "setup.exe")
        f_fakepdf = att(b"not a pdf", "fake.pdf")
        f_bintxt = att(b"abc\0def", "notes.txt")
        f_noext = att(b"hello", "README")
        f_path = att(pdf, "../../etc/evil.pdf")
        f_img = att(png, "shot.png", "image/png")
        fid, cid = f_pdf[1].get("id", ""), f_csv[1].get("id", "")
        too_many = srv.js("POST", f"/api/jobs/{jid}/inquire",
                          {"text": "x", "images": [pid] * 4, "files": [fid] * 3}, hdr)[0]
        f_forged = srv.js("POST", f"/api/jobs/{jid}/inquire",
                          {"text": "x", "files": ["file-1-deadbeef-../../x.pdf"]}, hdr)[0]
        q3 = srv.js("POST", f"/api/jobs/{jid}/inquire",
                    {"text": "Does this match the old report?", "images": [pid], "files": [fid, cid]}, hdr)[0]
        q3w = helper(plugin, ws, "wait", "--secs", "10")
        q3got = (json.loads(q3w.stdout) if q3w.returncode == 0 else {}).get("inquiry") or {}
        att_dir = os.path.join(folder, ".jti-build", "attachments")
        helper(plugin, ws, "reply", "--job", jid, "--n", "3", "Yes.")
        check("jobs: an attached file is accepted by extension with its content checked, keeps its "
              "name as a safe tail, and reaches the worker as `files`; executables, mislabelled "
              "files, nameless files, path tricks, forged ids and more than six attachments are refused",
              f_pdf[0] == 200 and re.match(r"^file-\d+-[0-9a-f]{8}-Old_report_v2\.pdf$", fid)
              and f_pdf[1].get("kind") == "file"
              and f_csv[0] == 200 and cid.endswith("-expected.csv")
              and f_exe[0] == 415 and f_fakepdf[0] == 400 and f_bintxt[0] == 400 and f_noext[0] == 415
              and f_path[0] == 200 and re.match(r"^file-\d+-[0-9a-f]{8}-evil\.pdf$", f_path[1].get("id", ""))
              and f_img[0] == 200 and f_img[1].get("kind") == "image"
              and re.match(r"^img-\d+-[0-9a-f]{8}\.png$", f_img[1].get("id", ""))
              and too_many == 400 and f_forged == 400 and q3 == 200
              and q3got.get("files") == [os.path.join(att_dir, fid), os.path.join(att_dir, cid)]
              and q3got.get("images") == [os.path.join(att_dir, pid)]
              and open(os.path.join(att_dir, fid), "rb").read() == pdf
              and all(not n.startswith("..") and "/" not in n for n in os.listdir(att_dir)),
              (f_pdf, f_csv, f_exe[0], f_fakepdf[0], f_bintxt[0], f_noext[0], f_path, f_img,
               too_many, f_forged, q3, q3w.stdout[-300:]))
        bad_tok = srv.js("POST", f"/api/jobs/{jid}/revise", {"text": "x"}, {"X-JTI-Job": "nope"})[0]
        empty = srv.js("POST", f"/api/jobs/{jid}/revise", {"text": "   "}, hdr)
        code, d = srv.js("POST", f"/api/jobs/{jid}/revise",
                         {"text": "Rename the Type column to Case Type"}, hdr)
        j = srv.snap(jid, tok)
        check("jobs: changes can be requested only on a finished build, with the job's token, "
              "and not blank",
              c1.returncode == 0 and early[0] == 409 and bad_tok == 403 and empty[0] == 409
              and code == 200 and d.get("ok"), (c1.stdout[-200:], early, bad_tok, empty, code, d))
        check("jobs: a change request puts the SAME job back in the queue with the request, "
              "its old gates and downloads cleared (setup stages stay ticked, the rest rerun)",
              j["status"] == "submitted" and j["revision"]["n"] == 1
              and j["revision"]["text"] == "Rename the Type column to Case Type"
              and j["gates"] is None and j["artifacts"] == []
              and j["percent"] < 30 and "contract" not in j["done"] and "package" not in j["done"], j)
        w = helper(plugin, ws, "wait", "--secs", "10")
        got = json.loads(w.stdout) if w.returncode == 0 else {}
        running = srv.js("POST", f"/api/jobs/{jid}/revise", {"text": "again"}, hdr)[0]
        c_early = helper(plugin, ws, "complete")
        r2 = run_gates(plugin, ws, folder)
        c2 = helper(plugin, ws, "complete")
        j2 = srv.snap(jid, tok)
        check("jobs: the waiting worker claims it with the request text, in the same folder; it "
              "cannot complete until the gates pass again, then completes with its history",
              got.get("id") == jid and got.get("folder") == folder
              and (got.get("revision") or {}).get("text") == "Rename the Type column to Case Type"
              and running == 409 and c_early.returncode == 1 and r2.returncode == 0
              and c2.returncode == 0 and j2["status"] == "complete" and j2["percent"] == 100
              and len(j2["revisions"]) == 1 and j2["artifacts"],
              (w.stdout[-300:], running, c_early.stdout[-200:], c2.stdout[-200:]))
        ui = open(os.path.join(plugin, "scripts", "build_ui.js"), encoding="utf8").read()
        check("builder page: a finished build shows a 'Questions or changes?' box that posts "
              "to /revise and follows the job again",
              "Questions or changes?" in ui and "'/revise'" in ui and "'/inquire'" in ui
              and "onPaste=${onPaste}" in ui and "'/attach'" in ui
              and "onDrop=${onDrop}" in ui and 'type="file"' in ui and "Attach a file" in ui
              and "navigator.clipboard.read()" in ui and "Paste from clipboard" in ui
              and "files: pics.filter" in ui
              and "Ask a question" in ui and "RevisePanel" in ui
              and "useJob(job, round)" in ui, "build_ui.js")
        app = open(os.path.join(plugin, "scripts", "app.js"), encoding="utf8").read()
        check("builder page: 'match a picture' takes a pasted screenshot (page-wide, not in text "
              "boxes), a dropped file, or the clipboard button, all through one upload",
              "document.addEventListener('paste', onPaste)" in app and "el.tagName === 'TEXTAREA'" in app
              and "class=${'mt12 lookdrop'" in app and "sendLook(firstFile(e.dataTransfer" in app
              and "onClick=${lookFromClipboard}" in app and app.count("fetch('/api/look?name='") == 1,
              "app.js")
    finally:
        srv.stop()


# ── phase 5: cancellation and the local-server security rules ────────────────────────
def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def run_phase5(check, skip, ctx):
    import http.client
    plugin, root = ctx["plugin"], ctx["ws"]
    ws = fresh_ws(root, "cancel")
    srv = Server(plugin, ws).start()
    try:
        # a file the user already had in the report folder, before the job existed
        folder = os.path.join(ws, "Proj", "Cancel_Probe")
        os.makedirs(folder)
        open(os.path.join(folder, "my-notes.txt"), "w").write("mine\n")
        code, d = srv.submit(spec_for("Cancel_Probe"))
        jid, tok = d["job"], d["token"]
        helper(plugin, ws, "wait", "--secs", "10")
        # a long child: writes a partial file, prints its pid, then sleeps
        child = ("import os,time; open('partial.txt','w').write('x'); "
                 "print('CHILD', os.getpid(), flush=True); time.sleep(120)")
        p = subprocess.Popen([sys.executable, os.path.join(plugin, "scripts", "jobs.py"), "run",
                              "--stage", "render", "--", sys.executable, "-c", child],
                             cwd=folder, env=dict(os.environ, JTI_PROJECT_ROOT=ws),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cpid = wait_for(lambda: ((srv.snap(jid, tok) or {}).get("child") or {}).get("pid"))
        wait_for(lambda: os.path.exists(os.path.join(folder, "partial.txt")))
        t0 = time.time()
        c_no, _ = srv.js("POST", f"/api/jobs/{jid}/cancel", {})
        c_ok, r = srv.js("POST", f"/api/jobs/{jid}/cancel", {}, {"X-JTI-Job": tok})
        out, _ = p.communicate(timeout=30)
        took = time.time() - t0
        j = srv.snap(jid, tok)
        check("jobs: cancel during a running child stops it (whole process group) within seconds",
              c_no == 403 and c_ok == 200 and p.returncode == 6 and "CANCELLED" in out
              and cpid and not pid_alive(cpid) and took < 10, f"rc={p.returncode} {took:.1f}s {out[-300:]}")
        check("jobs: a cancelled job is CANCELLED - never successful - and lists what it created",
              j["status"] == "cancelled" and j["artifacts"] == [] and "partial.txt" in j["partial"]
              and "verification/spec.json" in j["partial"] and "my-notes.txt" not in j["partial"], j["partial"])
        check("jobs: cancelling leaves every file in place, the user's own included",
              open(os.path.join(folder, "my-notes.txt")).read() == "mine\n"
              and os.path.exists(os.path.join(folder, "partial.txt")), os.listdir(folder))
        after = [helper(plugin, ws, *a).returncode for a in (("done", "fixtures"), ("complete",))]
        c_pkg = srv.get(f"/api/jobs/{jid}/package?t={tok}")[0]
        c_again, _ = srv.js("POST", f"/api/jobs/{jid}/cancel", {}, {"X-JTI-Job": tok})
        check("jobs: after a cancel every helper call exits 6, nothing downloads, cancel is final",
              after == [6, 6] and c_pkg == 409 and c_again == 409, (after, c_pkg, c_again))

        # cancel while the worker is blocked on a question
        code, d = srv.submit(spec_for("Cancel_Ask"))
        jid2, tok2 = d["job"], d["token"]
        helper(plugin, ws, "wait", "--secs", "10")
        q = helper(plugin, ws, "ask", "--id", "x", "--title", "t", "--prompt", "p", "--type", "text",
                   background=True)
        wait_for(lambda: (srv.snap(jid2, tok2) or {}).get("question"))
        srv.js("POST", f"/api/jobs/{jid2}/cancel", {}, {"X-JTI-Job": tok2})
        qo, _ = q.communicate(timeout=30)
        check("jobs: cancel reaches a worker that is waiting on a question (exit 6)",
              q.returncode == 6 and srv.snap(jid2, tok2)["status"] == "cancelled", qo)
        # cancel before anyone claimed it: immediate
        code, d = srv.submit(spec_for("Cancel_Early"))
        srv.js("POST", f"/api/jobs/{d['job']}/cancel", {}, {"X-JTI-Job": d["token"]})
        check("jobs: a job nobody has claimed is cancelled at once",
              srv.snap(d["job"], d["token"])["status"] == "cancelled", "")

        # ---- security -----------------------------------------------------------------
        def raw(method, path, headers, body=b""):
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
            c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in headers.items():
                c.putheader(k, v)
            c.endheaders(body or None)
            r = c.getresponse(); b = r.read(); c.close()
            return r.status, b
        host = f"127.0.0.1:{srv.port}"
        codes = {
            "rebinding Host": raw("GET", "/api/bootstrap", {"Host": f"evil.example:{srv.port}"})[0],
            "cross-origin POST": raw("POST", "/api/jobs", {"Host": host, "Origin": "http://evil.example",
                                     "X-JTI-Session": srv.session, "Content-Length": "2"}, b"{}")[0],
            "no Content-Length": raw("POST", "/api/jobs", {"Host": host, "X-JTI-Session": srv.session})[0],
            "oversized body": raw("POST", "/api/jobs", {"Host": host, "X-JTI-Session": srv.session,
                                  "Content-Length": str(2 * 1024 * 1024)})[0],
            "GET on a mutation": raw("GET", "/api/jobs", {"Host": host})[0],
            "worker GET": raw("GET", "/api/worker/claim", {"Host": host})[0],
            "old spec route": raw("POST", "/api/spec", {"Host": host, "Content-Length": "2"}, b"{}")[0],
            "upload without session": raw("POST", "/api/look?name=a.png", {"Host": host,
                                          "Content-Length": "8"}, b"\x89PNG\r\n\x1a\n")[0],
        }
        check("jobs: wrong Host (DNS rebinding), cross-origin POST, no/oversized body, GET on a "
              "mutation, the old spec route and an unauthenticated upload are all refused",
              codes == {"rebinding Host": 421, "cross-origin POST": 403, "no Content-Length": 411,
                        "oversized body": 413, "GET on a mutation": 405, "worker GET": 405,
                        "old spec route": 404, "upload without session": 403}, codes)
        bad = [spec_for("../../escape"), dict(spec_for("Abs_Path"), project="/etc"),
               dict(spec_for("Link_Dest"), project="Proj/link")]
        os.symlink("/tmp", os.path.join(ws, "Proj", "link"))
        res = [srv.submit(b)[0] for b in bad]
        check("jobs: a path in the report name, an unwritable destination and a destination "
              "reached through a symlink are all refused; nothing is written outside",
              res == [400, 400, 400] and not os.path.exists(os.path.join(ws, "escape"))
              and not os.path.exists("/etc/Abs_Path") and not os.path.exists("/tmp/Link_Dest"), res)
        src = open(os.path.join(plugin, "scripts", "serve_builder.py")).read()
        state = os.path.join(ws, ".jti-builder", "server.json")
        check("jobs: the server binds 127.0.0.1 only, and its worker token file is private (0600)",
              'Server(("127.0.0.1", a.port)' in src and 'Server(("0.0.0.0"' not in src
              and 'Server(("", ' not in src
              and oct(os.stat(state).st_mode & 0o777) == "0o600"
              and oct(os.stat(os.path.dirname(state)).st_mode & 0o777) == "0o700",
              oct(os.stat(state).st_mode))
        cmd = open(os.path.join(plugin, "commands", "build-report.md")).read()
        front = cmd.split("---")[1]
        check("commands/build-report.md asks through the browser only - no chat question tool",
              "AskUserQuestion" not in front and '"$J" ask' in cmd and '"$J" wait' in cmd
              and 'J="$P/scripts/jobs.py"' in cmd and "Never ask a question here" in cmd
              and "--gates" in cmd and "Never import" in cmd, front)
    finally:
        srv.stop()


# ── the field browser, picked paths in the spec, and finding the job server ──────────
def run_fields(check, skip, ctx):
    import glob
    plugin, root = ctx["plugin"], ctx["ws"]
    if not ctx["jrs"]:
        return skip("field browser", "no JasperReports install (javac/javap)")
    ws = fresh_ws(root, "fields")
    jdk = os.path.join(ctx["jrs"], "java", "bin")
    cls = os.path.join(ws, "classes"); os.makedirs(cls)
    subprocess.run([os.path.join(jdk, "javac"), "-d", cls, *sorted(glob.glob(os.path.join(
        ctx["fix"], "fake_sdk", "com", "sustain", "cases", "model", "*.java")))], check=True)
    jar = os.path.join(ws, "ecourt-sdk-fake.jar")
    subprocess.run([os.path.join(jdk, "jar"), "cf", jar, "com"], cwd=cls, check=True)
    subprocess.run([sys.executable, os.path.join(plugin, "scripts", "project.py"), "sdk-register",
                    os.path.join(ws, "Proj"), jar], env=dict(os.environ, JTI_PROJECT_ROOT=ws),
                   capture_output=True, check=True)
    os.makedirs(os.path.join(ws, "NoSdk"))
    srv = Server(plugin, ws, jobs=False).start()
    try:
        c, d = srv.js("GET", "/api/fields?project=Proj&entity=Case")
        f = {x["name"]: x for x in d.get("fields", [])}
        check("fields: the browser lists an entity's real fields from the project's SDK",
              c == 200 and d.get("ok") and f.get("caseNumber", {}).get("kind") == "value"
              and f.get("parent", {}).get("kind") == "entity"
              and f.get("parties", {}).get("kind") == "collection"
              and f["parties"].get("targetShort") == "Party"
              and "id" in f and "class" not in f and "Case" in d.get("roots", []), d)
        c, d2 = srv.js("GET", "/api/fields?project=Proj&entity=" + f["parties"]["target"])
        check("fields: drilling into a list lands on its element type",
              d2.get("ok") and d2.get("entity") == "Party"
              and any(x["name"] == "lastName" for x in d2["fields"]), d2)
        bad = [srv.js("GET", "/api/fields?project=Proj&entity=" + e)[1]
               for e in ("java.lang.Runtime", "Nope", "../../etc/passwd")]
        nosdk = srv.js("GET", "/api/fields?project=NoSdk")[1]
        check("fields: only classes IN the jar are read; a project with no SDK says so",
              all(not b.get("ok") for b in bad) and nosdk.get("reason") == "no-sdk", (bad, nosdk))
        spec = spec_for("Picked")
        spec["paths"] = {"caseNumber": "Case.caseNumber", "partyLastName": "Case.parties[].lastName"}
        spec["criteria"] = [{"path": "Case.filingDate", "kind": "range",
                             "params": ["FilingDateFrom", "FilingDateTo"]}]
        c, _ = srv.js("POST", "/api/spec", spec)
        spec2 = dict(spec_for("Picked_Bad"), paths=["not", "a", "map"], criteria="nope")
        srv.js("POST", "/api/spec", spec2)
        s1 = json.load(open(os.path.join(ws, "Proj", "Picked", "verification", "spec.json")))
        s2 = json.load(open(os.path.join(ws, "Proj", "Picked_Bad", "verification", "spec.json")))
        check("fields: picked paths and filters are kept in spec.json; malformed ones dropped",
              c == 200 and s1.get("paths") == spec["paths"]
              and s1.get("criteria") == [{"path": "Case.filingDate", "operator": "range",
                                          "params": ["FilingDateFrom", "FilingDateTo"]}]
              and "paths" not in s2 and "criteria" not in s2, (s1.get("criteria"), s2))
        # the eSeries-style settings: a criterion's operator / flags / default, a column's options
        full = spec_for("Configured")
        full["criteria"] = [{"path": "Case.caseStatus", "label": "Status", "operator": "IN", "lookup": "CASE_STATUS",
                             "multi": True, "lookupFormat": "LABEL", "required": True, "hidden": False,
                             "default": "OPEN", "type": "pick-list", "params": ["CaseStatus"]},
                            {"path": "Case.x", "operator": "rm -rf", "params": ["X"]}]
        full["columnOptions"] = {"caseNumber": {"link": True, "sort": "DESCEND", "aggregate": "GROUP_BY",
                                                "format": "", "customFormat": "", "truncate": "12"},
                                 "caseType": {"link": False, "sort": "sideways", "aggregate": "EXPLODE"}}
        srv.js("POST", "/api/spec", full)
        s3 = json.load(open(os.path.join(ws, "Proj", "Configured", "verification", "spec.json")))
        c0, c1 = s3["criteria"]
        check("fields: criterion settings (operator, pick-list, required, default) and column options "
              "(link, sort, aggregate, truncate) are kept; values outside the eSeries sets are refused",
              c0["operator"] == "IN" and c0["multi"] is True and c0["required"] is True
              and c0["default"] == "OPEN" and c0["lookup"] == "CASE_STATUS" and c1["operator"] == "EQUALS"
              and "lookupFormat" not in c0      # retired: a report input always carries the CODE
              and s3["columnOptions"]["caseNumber"] == {"link": True, "sort": "DESCEND", "aggregate": "GROUP_BY",
                                                       "format": "", "customFormat": "", "truncate": "12"}
              and "caseType" not in s3["columnOptions"], (s3.get("criteria"), s3.get("columnOptions")))
    finally:
        srv.stop()

    # a job server running for ANOTHER workspace is still found by the helper
    other = fresh_ws(root, "otherws")
    srv = Server(plugin, ws).start()
    try:
        stale = os.path.join(other, ".jti-builder"); os.makedirs(stale, mode=0o700)
        open(os.path.join(stale, "server.json"), "w").write(json.dumps(
            {"port": 1, "pid": 999999, "worker_token": "x"}))
        r = helper(plugin, other, "wait", "--secs", "2", timeout=60)
        check("jobs: the helper finds a job server started from another workspace (and ignores "
              "a leftover state file from a dead one)",
              r.returncode == 7 and "NO JOB YET" in r.stdout, r.stdout + r.stderr)
    finally:
        srv.stop()


# ── the Data Dictionary as the field browser's source ─────────────────────────────────
def make_dd(path, rows):
    """A minimal DataDictionary-*.xlsx (inline strings, one sheet), shaped like the eSeries
    export: an entity row (name in A), then field rows (B name, C type, D description,
    H 'Examples: a,b')."""
    import zipfile
    from xml.sax.saxutils import escape
    def cell(ref, v):
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
    xml = []
    for i, r in enumerate(rows, 1):
        xml.append(f'<row r="{i}">' + "".join(cell(f"{'ABCDEFGH'[j]}{i}", v)
                                              for j, v in enumerate(r) if v) + "</row>")
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxml'
             'formats.org/spreadsheetml/2006/main"><sheetData>' + "".join(xml) + '</sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Sheet1"/></sheets></workbook>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)


DD_ROWS = [["Case", "tCase"],
           ["", "caseNumber", "String (255)", "Case Number - assigned at filing", "Not Null"],
           ["", "caseStatus", "Lookup List (CASE_STATUS)", "Case Status", "", "", "", "Examples: Open,Closed,Pending"],
           ["", "filingDate", "Date", "Filing date", "", "", "Indexed"],
           ["", "parties", "Collection (Party)", ""],
           ["", "FancyWidget", "Widget", ""]] + \
          [["", f"extra{i}", "String (255)", ""] for i in range(20)] + \
          [["Party", "tParty"], ["", "partyType", "Lookup List (PARTY_TYPE)", "", "", "", "", "Examples: Defendant,Victim"],
           ["", "person", "Person", ""],
           ["Person", "tPerson"], ["", "lastName", "String (255)", "Last name"]]


def run_dd(check, skip, ctx):
    plugin, root = ctx["plugin"], ctx["ws"]
    ws = fresh_ws(root, "dd")
    dd = os.path.join(ws, "DataDictionary-probe.xlsx")
    make_dd(dd, DD_ROWS)
    proj = os.path.join(plugin, "scripts", "project.py")
    env = dict(os.environ, JTI_PROJECT_ROOT=ws)
    bad = subprocess.run([sys.executable, proj, "dd-register", os.path.join(ws, "Proj"),
                          os.path.join(plugin, ".claude-plugin", "plugin.json")], env=env,
                         capture_output=True, text=True)
    good = subprocess.run([sys.executable, proj, "dd-register", os.path.join(ws, "Proj"), dd],
                          env=env, capture_output=True, text=True)
    check("dd-register keeps a Data Dictionary in the project and refuses anything else",
          "REFUSED" in bad.stdout and good.stdout.startswith("SAVED")
          and os.path.isfile(os.path.join(ws, "Proj", "dd", "DataDictionary-probe.xlsx")),
          bad.stdout + good.stdout)
    os.makedirs(os.path.join(ws, "Other"))
    open(os.path.join(ws, "Other", ".jti-project.json"), "w").write("{}")
    srv = Server(plugin, ws, jobs=False).start()
    try:
        c, d = srv.js("GET", "/api/fields?project=Proj&entity=Case")
        f = {x["name"]: x for x in d.get("fields", [])}
        check("fields: with a Data Dictionary on file it is the source - pick-lists carry their "
              "list and values, descriptions come through, widgets are left out",
              d.get("source") == "dd" and f["caseStatus"]["lookup"] == "CASE_STATUS"
              and f["caseStatus"]["values"] == ["Open", "Closed", "Pending"]
              and f["caseStatus"]["label"] == "pick-list" and f["filingDate"]["label"] == "date"
              and "assigned at filing" in f["caseNumber"]["description"]
              and f["parties"]["kind"] == "collection" and f["parties"]["target"] == "Party"
              and "FancyWidget" not in f, d)
        c, p = srv.js("GET", "/api/fields?project=Proj&entity=Party")
        check("fields: the dictionary walks relations the SDK jar cannot (Party -> Person)",
              any(x["name"] == "person" and x["kind"] == "entity" and x["target"] == "Person"
                  for x in p.get("fields", [])), p)
        code, _, body = srv.req("POST", "/api/dd?project=Other&name=DataDictionary-up.xlsx",
                                raw=open(dd, "rb").read(), headers={"Content-Type": "application/octet-stream"})
        after = srv.js("GET", "/api/fields?project=Other&entity=Case")[1]
        c2, _, b2 = srv.req("POST", "/api/dd?project=Other&name=notes.xlsx", raw=b"not a zip",
                            headers={"Content-Type": "application/octet-stream"})
        check("fields: a dictionary attached from the page is registered and used at once; "
              "a non-dictionary upload is refused",
              code == 200 and after.get("source") == "dd" and c2 == 400, (body[:200], b2[:200]))
        spec = spec_for("Lookup_Pick")
        spec["criteria"] = [{"path": "Case.caseStatus", "kind": "in", "lookup": "CASE_STATUS",
                             "params": ["CaseStatus"]}]
        srv.js("POST", "/api/spec", spec)
        s = json.load(open(os.path.join(ws, "Proj", "Lookup_Pick", "verification", "spec.json")))
        check("fields: a filter picked on a pick-list keeps the list name in spec.json",
              s.get("criteria", [{}])[0].get("lookup") == "CASE_STATUS", s.get("criteria"))
    finally:
        srv.stop()


def run_closed(check, skip, ctx):
    """Closing the builder tab stops the worker too - a reload does not."""
    plugin, root = ctx["plugin"], ctx["ws"]
    ws = fresh_ws(root, "closed")
    srv = Server(plugin, ws, env={"JTI_CLOSE_GRACE": "2", "JTI_PAGE_TTL": "8"}).start()
    try:
        beacon = lambda tok=None: srv.js("POST", "/api/session/closed", {"session": tok or srv.session})
        c, _ = beacon("nope")
        check("closed: the close beacon is refused without the session token", c == 403, c)

        srv.js("GET", "/api/watching"); beacon(); time.sleep(0.5); srv.js("GET", "/api/watching")
        w = helper(plugin, ws, "wait", "--secs", "5")
        check("closed: a RELOAD (beacon, then the page checks straight back in) does not stop Claude",
              w.returncode == 7, (w.returncode, w.stdout[-200:]))

        # What the real page does: a per-load id on every check-in and on the beacon.
        beacon_p = lambda page: srv.js("POST", "/api/session/closed", {"session": srv.session, "page": page})
        srv.js("GET", "/api/watching?page=A"); beacon_p("A"); srv.js("GET", "/api/watching?page=B")
        w = helper(plugin, ws, "wait", "--secs", "5")
        check("closed: a reload (a NEW page id checks in after the beacon) does not stop Claude",
              w.returncode == 7, (w.returncode, w.stdout[-200:]))

        srv.js("GET", "/api/watching"); beacon()
        t0 = time.time(); w = helper(plugin, ws, "wait", "--secs", "20")
        check("closed: closing the tab stops a waiting worker (exit 8, says the page was closed)",
              w.returncode == 8 and "page was closed" in w.stdout and time.time() - t0 < 10,
              (w.returncode, round(time.time() - t0, 1), w.stdout[-200:]))
        w = helper(plugin, ws, "wait", "--secs", "3")
        check("closed: used up once collected - the next session is not ended by the old tab", w.returncode == 7, w.returncode)

        srv.js("GET", "/api/watching")        # opened, then silent: no beacon (a crash, a lost network)
        t0 = time.time(); w = helper(plugin, ws, "wait", "--secs", "25")
        check("closed: a page that stops checking in for the timeout stops the worker",
              w.returncode == 8 and 7 < time.time() - t0 < 20, (w.returncode, round(time.time() - t0, 1)))
    finally:
        srv.stop()
    # The straggler, on a server whose page timeout is far away, so only the close can end it.
    ws = fresh_ws(root, "closed_late")
    srv = Server(plugin, ws, env={"JTI_CLOSE_GRACE": "2", "JTI_PAGE_TTL": "120"}).start()
    try:
        beacon_p = lambda page: srv.js("POST", "/api/session/closed", {"session": srv.session, "page": page})
        srv.js("GET", "/api/watching?page=C"); beacon_p("C"); srv.js("GET", "/api/watching?page=C")
        t0 = time.time(); w = helper(plugin, ws, "wait", "--secs", "15")
        check("closed: a check-in still in flight from the CLOSED tab (same id, after its beacon) "
              "does not cancel the close - Claude stops after the grace, not the page timeout",
              w.returncode == 8 and time.time() - t0 < 10, (w.returncode, round(time.time() - t0, 1)))
    finally:
        srv.stop()
    # A page opened BEFORE the server restarted still holds the session token it fetched
    # then. Its close beacon (and its Build button) must still work afterwards (10-01).
    ws = fresh_ws(root, "closed_restart")
    srv = Server(plugin, ws, env={"JTI_CLOSE_GRACE": "2", "JTI_PAGE_TTL": "120"}).start()
    old_tok = srv.session
    srv.stop()
    srv = Server(plugin, ws, env={"JTI_CLOSE_GRACE": "2", "JTI_PAGE_TTL": "120"}).start()
    try:
        srv.js("GET", "/api/watching?page=D")
        c, _ = srv.js("POST", "/api/session/closed", {"session": old_tok, "page": "D"})
        t0 = time.time(); w = helper(plugin, ws, "wait", "--secs", "15")
        code, d = srv.js("POST", "/api/jobs", spec_for("After_Restart"), {"X-JTI-Session": old_tok})
        check("closed: after a server restart, a tab opened before it still stops Claude when "
              "closed, and its Build button still submits (the session token survives a restart)",
              srv.session == old_tok and c == 200 and w.returncode == 8 and time.time() - t0 < 10
              and code == 200, (c, w.returncode, round(time.time() - t0, 1), code, d))
    finally:
        srv.stop()


def run_marks_done(check, skip, ctx):
    """`jobs.py run` marks its stage done when the child succeeds - and not when it fails."""
    plugin, root = ctx["plugin"], ctx["ws"]
    ws = fresh_ws(root, "rundone")
    srv = Server(plugin, ws).start()
    try:
        code, d = srv.submit(spec_for("Run_Done"))
        helper(plugin, ws, "wait", "--secs", "5")
        folder = os.path.join(ws, "Proj", "Run_Done")
        ok = subprocess.run([sys.executable, os.path.join(plugin, "scripts", "jobs.py"), "run", "--stage", "scaffold",
                             "--", sys.executable, "-c", "print('hi')"], cwd=folder, capture_output=True, text=True,
                            env=dict(os.environ, JTI_PROJECT_ROOT=ws))
        s1 = srv.snap(d["job"], d["token"])
        bad = subprocess.run([sys.executable, os.path.join(plugin, "scripts", "jobs.py"), "run", "--stage", "fixtures",
                              "--", sys.executable, "-c", "raise SystemExit(3)"], cwd=folder, capture_output=True,
                             text=True, env=dict(os.environ, JTI_PROJECT_ROOT=ws))
        s2 = srv.snap(d["job"], d["token"])
        check("jobs: `run` marks its stage done on success, and leaves a failed step not done",
              ok.returncode == 0 and "scaffold" in (s1 or {}).get("done", []) and bad.returncode == 3
              and "fixtures" not in (s2 or {}).get("done", []), (ok.returncode, (s1 or {}).get("done"), bad.returncode))
        helper(plugin, ws, "fail", "--stage", "fixtures", "--message", "test stops here")
    finally:
        srv.stop()
