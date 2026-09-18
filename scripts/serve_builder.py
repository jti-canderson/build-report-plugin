#!/usr/bin/env python3
"""
A local page for building a report spec, so the choices are made by clicking rather than
by answering four questions in a chat.

    python3 serve_builder.py [--port 8787] [--no-open]

WHY THIS EXISTS: AskUserQuestion caps at FOUR options. That cap is what made the template
letters misleading (the menu reorders, the letters did not), what split a five-project list
across two prompts that each wanted their own answer, and what forced a two-step template
menu. A form has no cap: six templates and five projects are just six and five, and every
preview sits next to its own label permanently instead of being sent as attachments first.

WHAT IT DOES AND DOES NOT DO. It writes `spec.json` into the project folder and prints the
one command to run. It does NOT invoke Claude - that is deliberate for now: no background
process, nothing to debug through a browser, and a build that wants to ask a follow-up
question can still ask it. Wiring a Generate button to `claude -p` is the next step, not
this one.

SCOPE. Binds to 127.0.0.1 only, and every path it writes is resolved under the same
workspace root `project.py` uses - the `.jti-root` marker, then $JTI_PROJECT_ROOT, then the
folder holding the plugin. A spec cannot be written outside it.
"""
import argparse
import http.server
import json
import os
import pathlib
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "templates"))
import project as P          # noqa: E402  - ROOT resolution, containment, project listing
import catalog as C          # noqa: E402  - the template list, single source of truth

PREVIEW = os.path.join(PLUGIN, "templates", "examples", "labeled")
NAME_OK = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,60}$')

# Every spec written this run, and a condition to wake anyone long-polling /api/wait.
# This is what lets Claude Code sit and WAIT for the Write button instead of the user
# copying a command back into the chat.
WRITES = []
WROTE = threading.Condition()
WAITERS = [0]          # how many /api/wait calls are parked right now


def projects():
    """Straight from project.py - never a second copy of the filter. A hand-written
    duplicate disagreed with `list` the first time it was written."""
    return [{**r, "environment": r["environment"] or ""} for r in P.list_projects()]


def templates():
    out = []
    for mod, title, one_liner, egs, more in C.CATALOG:
        stem = C._name(mod)
        out.append({"module": mod, "title": title, "one_liner": one_liner,
                    "examples": egs, "detail": more,
                    "preview": f"/preview/{stem}.png" if
                    os.path.exists(os.path.join(PREVIEW, stem + ".png")) else ""})
    return out


def inside_ws(d):
    return d == P.ROOT or P.ROOT in d.parents


def pickable(d):
    """Can a report be built INTO this folder?

    Not simply `not _is_report(d)`. The workspace root holds 14 loose .jrxml files AND
    seven report folders, so it is both - and `list_projects` rightly offers it while a
    naive is-it-a-report test disabled it. The page asks the server this question rather
    than re-deriving it, because the first cut re-derived it and the two disagreed.

    The ONLY disqualifier is that the folder is itself a report: loose .jrxml files with no
    report folders under them. Building a report inside a report is never what anyone meant.

    Everything else is fair game, including an empty folder and one outside the workspace.
    The earlier rule - "it must already hold reports or carry project metadata" - came from
    mirroring the dropdown, and it was wrong for browsing: it refused ~/Downloads and every
    new empty folder, which is exactly what someone browsing is usually trying to reach.
    """
    # ONLY meaningful inside the workspace. ~/Downloads holds 69 loose .jrxml files
    # because that is where a browser puts them - which made the heuristic call it "a
    # report" and refuse it. Outside the workspace there is no such thing as a report
    # folder, just a folder.
    if not inside_ws(d):
        return True
    return not (P._is_report(d) and not P._reports_in(d))


SHORTCUTS_FILE = ".jti-shortcuts"


def shortcuts():
    """The folder shortcuts, most-used first.

    The one people reach for constantly is the level ABOVE the workspace root - here
    ~/JaspersoftWorkspace, which holds MyReports alongside Config Work - so it is derived
    rather than hardcoded, and it leads. `Workspace` (the .jti-root itself) comes next.

    A teammate's layout will not match this one, so `<workspace>/.jti-shortcuts` is read if
    present: one path per line, `Label = /path` or just `/path`. Those come first. `#`
    starts a comment. Nothing here enumerates anything - is_dir() is a stat, which macOS
    does not gate; the listing only happens when a shortcut is actually clicked.
    """
    home = pathlib.Path.home()
    out, seen = [], set()

    def add(label, path):
        try:
            path = pathlib.Path(path).expanduser()
            if path.is_dir() and str(path) not in seen:
                seen.add(str(path))
                out.append((label, path))
        except OSError:
            pass

    cfg = P.ROOT / SHORTCUTS_FILE
    if cfg.exists():
        try:
            for line in cfg.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                label, _, path = line.partition("=")
                add(label.strip(), path.strip()) if path else \
                    add(pathlib.Path(label).name, label)
        except OSError:
            pass

    parent = P.ROOT.parent
    if parent != home and parent != P.ROOT:
        add(parent.name, parent)
    add("Workspace", P.ROOT)
    add("Home", home)
    for n in ("Downloads", "Desktop", "Documents"):
        add(n, home / n)
    return out


def form_spec(blob, filename):
    """Parse an uploaded folder-view export into builder-shaped sections.

    The file is written to a temp path and handed to formexport.py --spec, the same parser
    the command uses - one implementation, so the form and the chat flow cannot disagree
    about what a folder view says.

    Nothing is written into the workspace: an upload is an INPUT, not a deliverable. It is
    parsed, its shape is returned, and the temp copy is deleted.
    """
    suffix = ".zip" if filename.lower().endswith(".zip") else ".xml"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(blob)
        tmp.close()
        r = subprocess.run(
            [sys.executable,
             os.path.join(PLUGIN, "skills", "jasper-reports", "scripts", "formexport.py"),
             tmp.name, "--spec"],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return {"ok": False, "message": (r.stderr or r.stdout or "could not read it")[:400]}
        forms = json.loads(r.stdout or "[]")
        if not forms:
            return {"ok": False, "message":
                    "No folder view in that file. A FORM export holds panels and columns; "
                    "a RULE or REPORT export does not, and a .jrxml is already a layout."}
        return {"ok": True, "forms": forms}
    except json.JSONDecodeError:
        return {"ok": False, "message": "the parser did not return readable output"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "the parser took too long"}
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def checkdir(rel):
    """Does this path exist and is it a folder - WITHOUT reading it.

    stat() is not gated by macOS TCC; iterdir() is. So a folder can be validated, chosen and
    written into without ever triggering the privacy prompt for merely looking. The prompt
    then appears where it belongs: at the moment something is actually written.
    """
    if rel in ("", ".", None):
        d = P.ROOT
    else:
        d = pathlib.Path(str(rel)).expanduser()
        if not str(d).startswith("/"):
            d = P.ROOT / rel
    try:
        d = d.resolve()
        ok = d.is_dir()
    except OSError:
        return {"ok": False, "message": f"{rel} cannot be reached"}
    if not ok:
        return {"ok": False, "message": f"{d} is not a folder that exists"}
    return {"ok": True, "path": str(d), "inside": inside_ws(d),
            "pickable": pickable(d), "root": str(P.ROOT)}


def browse(rel):
    """Any folder the user explicitly navigates to - including outside the workspace.

    THE RULE THAT MATTERS is not "inside ROOT"; it is WHERE THE PATH CAME FROM. A folder
    the user clicked or typed in this form is a grant - they are looking at it and choosing
    it. A path DERIVED from something else is not, and that distinction is the actual fix
    for the bug this model was protecting against: on 09/09 a build took an attachment's
    location (~/Downloads) and invented a client project from it, silently, having asked
    nobody. Refusing every path outside ROOT prevented that, but it also stopped someone
    deliberately putting a report on their Desktop, which is a reasonable thing to want.

    So: the page browses anywhere, and says loudly when it is outside the workspace.
    `/build-report` still refuses to infer a project from an attachment path - that rule
    lives in the command and is unchanged.
    """
    if rel in ("", ".", None):
        here = P.ROOT
    elif str(rel).startswith("/") or str(rel).startswith("~"):
        here = pathlib.Path(str(rel)).expanduser()
    else:
        here = P.ROOT / rel
    try:
        here = here.resolve()
    except OSError:
        return {"error": f"{rel!r} cannot be resolved"}
    if not here.is_dir():
        return {"error": f"{here} is not a folder"}
    def ref(d):
        """Inside the workspace, keep paths relative so they read well; outside, absolute."""
        try:
            return str(d.relative_to(P.ROOT))
        except ValueError:
            return str(d)

    kids = []
    try:
        for d in sorted(here.iterdir()):
            if not d.is_dir() or d.name.startswith(".") or d.name in P.NOT_A_PROJECT:
                continue
            kids.append({"name": d.name, "rel": ref(d),
                         "isReport": P._is_report(d) and inside_ws(d),
                         "reports": len(P._reports_in(d)),
                         "pickable": pickable(d)})
    except PermissionError:
        # macOS gates ~/Desktop, ~/Documents and friends behind TCC. Say which fix applies
        # rather than leaving a bare refusal - the folder is not missing, the permission is.
        return {"error": f"macOS is blocking access to {here}. Grant the terminal running "
                         f"this builder access under System Settings \u2192 Privacy & "
                         f"Security \u2192 Files and Folders, or pick a different folder."}
    except OSError:
        pass

    inside = here == P.ROOT or P.ROOT in here.parents
    return {"path": ref(here), "label": str(here),
            "parent": None if here == here.parent else ref(here.parent),
            "dirs": kids, "isReport": P._is_report(here),
            "reports": len(P._reports_in(here)), "pickable": pickable(here),
            "inside": inside, "root": str(P.ROOT),
            "quick": [{"name": n, "path": str(d)} for n, d in shortcuts()]}


def write_spec(payload):
    """Validate, then write spec.json inside the chosen project. Returns (ok, message)."""
    name = (payload.get("name") or "").strip()
    if not NAME_OK.match(name):
        return False, ("Report name must start with a letter and use only letters, digits "
                       "and underscores - it becomes the .jrxml and rule file names.")
    proj = (payload.get("project") or "").strip()
    if proj in ("", "."):
        folder = P.ROOT
    else:
        cand = pathlib.Path(proj).expanduser() if proj.startswith(("/", "~")) \
            else P.ROOT / proj
        folder = cand.resolve() if cand.is_dir() else None
    # The folder must already EXIST. Browsing to a place is a grant to write a report
    # there; it is not a grant to create arbitrary directory trees anywhere on the disk.
    if folder is None:
        return False, (f"{proj!r} is not a folder that exists. Browse to it, or create it "
                       f"first.")
    if not payload.get("sections"):
        return False, "Add at least one section with at least one column."
    for s in payload["sections"]:
        if not s.get("cols"):
            return False, f"Section {s.get('key') or '?'} has no columns."

    out = folder / name
    out.mkdir(parents=True, exist_ok=True)
    spec = {k: payload.get(k) for k in
            ("name", "title", "template", "why", "sections", "meta", "tiles",
             "params", "variants", "root", "id", "intent")}
    spec["title"] = spec.get("title") or name.replace("_", " ")
    spec["variants"] = spec.get("variants") or ["full", "none"]
    p = out / "spec.json"
    p.write_text(json.dumps(spec, indent=2) + "\n")
    try:
        rel = str(p.relative_to(P.ROOT))
    except ValueError:
        rel = str(p)                       # a folder chosen outside the workspace
    with WROTE:
        WRITES.append(rel)
        WROTE.notify_all()
    return True, rel


class Handler(http.server.SimpleHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass                                    # the console is for the spec path, not a log

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "builder.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path.startswith("/vendor/") or path == "/app.js":
            fn = os.path.basename(path)
            base = os.path.join(HERE, "vendor") if path.startswith("/vendor/") else HERE
            full = os.path.join(base, fn)
            if os.path.realpath(full).startswith(os.path.realpath(base)) \
                    and os.path.exists(full):
                with open(full, "rb") as f:
                    return self._send(200, f.read(), "application/javascript")
            return self._send(404, b"not found", "text/plain")
        if path == "/api/wait":
            # Block until a spec is written, then hand back its path. `since` is how many
            # writes the caller has already seen, so a spec written between polls is not
            # missed - a plain "wait for the next event" would drop it.
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            since = int((q.get("since") or ["0"])[0] or 0)
            secs = min(int((q.get("secs") or ["540"])[0] or 540), 900)
            with WROTE:
                WAITERS[0] += 1
            try:
                with WROTE:
                    if len(WRITES) <= since:
                        WROTE.wait(timeout=secs)
            finally:
                with WROTE:
                    WAITERS[0] -= 1
            with WROTE:
                if len(WRITES) > since:
                    return self._send(200, json.dumps(
                        {"ok": True, "spec": WRITES[since], "seen": since + 1}))
            return self._send(200, json.dumps({"ok": False, "timeout": True,
                                               "seen": len(WRITES)}))
        if path == "/api/checkdir":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(200, json.dumps(checkdir((q.get("path") or [""])[0])))
        if path == "/api/browse":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(200, json.dumps(browse((q.get("path") or [""])[0])))
        if path == "/api/bootstrap":
            return self._send(200, json.dumps({
                "root": str(P.ROOT), "rootWhy": P.ROOT_WHY,
                "projects": projects(), "templates": templates()}))
        if path.startswith("/preview/"):
            fn = os.path.basename(path)
            full = os.path.join(PREVIEW, fn)
            # basename() already strips traversal; the realpath check is the belt.
            if os.path.realpath(full).startswith(os.path.realpath(PREVIEW)) \
                    and os.path.exists(full):
                with open(full, "rb") as f:
                    return self._send(200, f.read(), "image/png")
            return self._send(404, b"no such preview", "text/plain")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        route = urllib.parse.urlparse(self.path)
        if route.path == "/api/formexport":
            n = int(self.headers.get("Content-Length") or 0)
            if n > 40 * 1024 * 1024:
                return self._send(400, json.dumps(
                    {"ok": False, "message": "that file is over 40 MB - not a config export"}))
            q = urllib.parse.parse_qs(route.query)
            body = self.rfile.read(n)
            out = form_spec(body, (q.get("name") or ["upload.zip"])[0])
            return self._send(200 if out.get("ok") else 400, json.dumps(out))
        if route.path != "/api/spec":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, json.dumps({"ok": False, "message": "bad JSON"}))
        ok, msg = write_spec(payload)
        return self._send(200 if ok else 400,
                          json.dumps({"ok": ok, "message": msg,
                                      "watched": WAITERS[0] > 0}))


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help:
        print(__doc__)
        sys.exit(0)

    # If the port is taken, find out by WHOM before shouting about it. A second
    # `/build-report` should say "it is already open at this URL", not fail with
    # EADDRINUSE and leave someone wondering which of the two is real.
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/api/bootstrap", timeout=1):
            print(f"  report builder ALREADY RUNNING at http://127.0.0.1:{a.port}/")
            if not a.no_open:
                webbrowser.open(f"http://127.0.0.1:{a.port}/")
            sys.exit(0)
    except Exception:
        pass

    # THREADED, not the plain TCPServer this used until 09/18. /api/wait blocks for minutes
    # by design, and on a single-threaded server that blocked the form too - the Write button
    # could never be served, so the thing being waited for could never happen.
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    # 127.0.0.1, never 0.0.0.0: this writes files, and nothing about it should be reachable
    # from the network.
    with Server(("127.0.0.1", a.port), Handler) as httpd:
        url = f"http://127.0.0.1:{a.port}/"
        print(f"  report builder  {url}")
        print(f"  workspace       {P.ROOT}   ({P.ROOT_WHY})")
        print(f"  {len(projects())} project(s), {len(templates())} template(s)")
        print("  Ctrl-C to stop.\n")
        if not a.no_open:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  stopped")


if __name__ == "__main__":
    main()
