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
import re
import socketserver
import sys
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


def write_spec(payload):
    """Validate, then write spec.json inside the chosen project. Returns (ok, message)."""
    name = (payload.get("name") or "").strip()
    if not NAME_OK.match(name):
        return False, ("Report name must start with a letter and use only letters, digits "
                       "and underscores - it becomes the .jrxml and rule file names.")
    proj = (payload.get("project") or "").strip()
    folder = P.ROOT if proj in ("", ".") else P._under_root(P.ROOT / proj)
    if folder is None or not folder.exists():
        return False, f"Project {proj!r} is not a folder inside {P.ROOT}."
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
    rel = p.relative_to(P.ROOT)
    return True, str(rel)


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
        if urllib.parse.urlparse(self.path).path != "/api/spec":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, json.dumps({"ok": False, "message": "bad JSON"}))
        ok, msg = write_spec(payload)
        return self._send(200 if ok else 400, json.dumps({"ok": ok, "message": msg}))


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help:
        print(__doc__)
        sys.exit(0)

    socketserver.TCPServer.allow_reuse_address = True
    # 127.0.0.1, never 0.0.0.0: this writes files, and nothing about it should be reachable
    # from the network.
    with socketserver.TCPServer(("127.0.0.1", a.port), Handler) as httpd:
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
