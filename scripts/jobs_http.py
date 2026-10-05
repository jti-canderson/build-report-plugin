"""jobs_http.py - the job routes serve_builder.py adds in --jobs mode (/build-report only; port 8789).

Browser routes need the SESSION token (from /api/bootstrap) to submit, and the job's own
TOKEN for everything about that job. Worker routes need the WORKER token, which only exists
in <workspace>/.jti-builder/server.json (mode 0600). The browser can ask for predefined
actions only - there is no route that takes a command or a filesystem path.
"""
import json
import os
import pathlib
import re
import time
import urllib.parse

import jobs as J

MAX_JSON = 1 * 1024 * 1024


def MAXA(kind):
    return J.MAX_ANSWER.get(kind, 400)
JOB_PATH = re.compile(r"^/api/jobs/([0-9a-f]{16})(/[a-z]+)?(/[a-z0-9]+)?$")


def safe_file(folder, rel):
    """The regular file at folder/rel, or None. Resolved first, so no `..`, no absolute path
    and no symlink anywhere along the way can reach outside the report folder."""
    folder = pathlib.Path(folder).resolve()
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel:
        return None
    p = folder / rel
    cur = folder
    for part in pathlib.PurePosixPath(rel).parts:
        if part in ("..", "."):
            return None
        cur = cur / part
        if cur.is_symlink():
            return None
    try:
        r = p.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if folder not in r.parents or not r.is_file():
        return None
    return r


def safe_name(name):
    import re as _re
    return _re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "download"


CTYPE = {".pdf": "application/pdf", ".png": "image/png", ".zip": "application/zip",
         ".txt": "text/plain; charset=utf-8", ".jrxml": "application/xml",
         ".groovy": "text/plain; charset=utf-8"}


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
            if u.path == "/api/session/done":
                # The page's "Done" button: the worker stops after its current step.
                if method != "POST":
                    raise Refuse(405, "POST only")
                self.need_session(h)
                stopping, msg = self.s.request_done()
                h._send(200, json.dumps({"ok": True, "stopping": stopping, "message": msg}))
                return True
            if u.path == "/api/session/closed":
                # navigator.sendBeacon on pagehide: it cannot set headers, so the session
                # token rides in the body. Only MARKS the page as closing - a reload checks
                # back in at once and cancels it (Store.page_gone).
                if method != "POST":
                    raise Refuse(405, "POST only")
                b = body_json(h)
                if not J.same(str(b.get("session") or ""), self.s.session_token):
                    raise Refuse(403, "session token missing or wrong")
                self.s.page_closed(str(b.get("page") or ""))
                print(f"  builder tab closed - Claude stops in {J.CLOSE_GRACE} s unless the page comes back",
                      flush=True)
                h._send(200, json.dumps({"ok": True}))
                return True
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
            raw = str(payload.get("project") or "").strip()
            given = pathlib.Path(raw).expanduser() if raw.startswith(("/", "~")) \
                else self.app.P.ROOT / raw
            if given.absolute() != given.resolve():
                raise Refuse(400, f"{raw!r} goes through a symlink (it is really "
                                  f"{given.resolve()}) - browse to the real folder instead")
            if not __import__("os").access(folder.parent, __import__("os").W_OK):
                raise Refuse(400, f"{folder.parent} is not writable - pick another destination")
            pre, err = self.preexisting(folder)
            if err:
                raise Refuse(409, err)
            # Lists the scaffold expects: a hand-posted spec that omits them would store null,
            # and the generated gen_jrxml.py then dies on `META = null`.
            for k in ("meta", "tiles", "sections", "params"):
                if not isinstance(payload.get(k), list):
                    payload[k] = []
            if not isinstance(payload.get("variants"), list) or not payload["variants"]:
                payload["variants"] = ["full", "none"]
            try:
                ok, msg = self.app.write_spec(payload)
            except OSError as e:
                raise Refuse(400, f"could not write the report folder: {e.strerror or e}")
            if not ok:
                raise Refuse(400, msg)
            report = {"name": payload["name"].strip(),
                      "title": (payload.get("title") or "").strip()
                      or payload["name"].strip().replace("_", " "),
                      "folder": str(folder), "destination": str(folder.parent)}
            j, tok = self.s.create(report, "verification/spec.json", pre)
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
        # Files an earlier UNFINISHED builder job recorded creating may be rebuilt; any other
        # report file - including one that appeared after that job ended - is the user's.
        ours = set(prior.get("partial") or []) \
            if prior and prior.get("status") in ("failed", "cancelled", "timed_out") else set()
        real = [f for f in files if (f.endswith((".jrxml", ".groovy")) or f.startswith("RULE-"))
                and f not in ours]
        if real:
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
        if method == "GET" and action in ("file", "preview", "package"):
            return self.download(h, j, action, arg)
        if method == "POST" and action == "cancel":
            with self.s.lock:
                r = self.cancel(self.s.get(jid))
            h._send(200, json.dumps(r)); return True
        if method == "POST" and action == "attach":
            h._send(200, json.dumps(self.attach(h, j)))
            return True
        if method == "POST" and action == "revise":
            b = body_json(h) or {}
            ok, msg = self.s.revise(self.s.get(jid), b.get("text"), *self.attached(j, b))
            if not ok:
                raise Refuse(409, msg)
            h._send(200, json.dumps({"ok": True, "message": msg,
                                     "job": self.s.public(self.s.get(jid))}))
            return True
        if method == "POST" and action == "inquire":
            b = body_json(h) or {}
            ok, msg = self.s.inquire(self.s.get(jid), b.get("text"), *self.attached(j, b))
            if not ok:
                raise Refuse(409, msg)
            h._send(200, json.dumps({"ok": True, "message": msg,
                                     "job": self.s.public(self.s.get(jid))}))
            return True
        if method == "POST" and action == "answer":
            with self.s.lock:
                r = self.post_answer(h, self.s.get(jid), body_json(h))
            h._send(200, json.dumps(r)); return True
        if method == "POST" and action == "upload":
            h._send(200, json.dumps(self.upload(h, j, (q.get("q") or [""])[0])))
            return True
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
        if action == "answer":
            return self.wait_answer(h, str(b.get("id") or ""), min(max(int(b.get("secs") or 50), 1), 55))
        if action == "claim":
            j = s.claim(min(max(int(b.get("secs") or 50), 1), 55))
            if j in ("DONE", "CLOSED"):
                print("  telling Claude to stop: " + ("the tab was closed" if j == "CLOSED" else "Done was clicked"),
                      flush=True)
                h._send(200, json.dumps({"ok": True, "job": None, "finished": True,
                                         "reason": "closed" if j == "CLOSED" else "done"}))
                return True
            if isinstance(j, tuple):                       # ("INQUIRY", job, question)
                _, jj, q = j
                d = self.claimed(jj)
                d.update({"revision": None, "status": jj["status"],
                          "inquiry": {"n": q["n"], "text": q["text"], "images": q.get("images") or [],
                                      "files": q.get("files") or []},
                          "earlier": [{"q": x["text"], "a": x["answer"]}
                                      for x in jj.get("inquiries") or [] if x["answer"]]})
                h._send(200, json.dumps({"ok": True, "job": d}))
                return True
            h._send(200, json.dumps({"ok": True, "job": self.claimed(j) if j else None}))
            return True
        if action == "reply":
            n = b.get("n")
            if not isinstance(n, int):
                raise Refuse(400, "n must be the question number")
            ok, msg = s.reply(str(b.get("job") or ""), n, b.get("text"))
            if not ok:
                raise Refuse(409, msg)
            h._send(200, json.dumps({"ok": True}))
            return True
        with s.lock:
            j = s.worker_job()
            if not j:
                last = s.last_claimed()
                if last and action not in ("claim",):
                    # The build the worker was on has ENDED. Say how, so the helper stops
                    # with the right exit code instead of a confusing "no job".
                    h._send(200, json.dumps({"ok": True, "cancel": last["status"] == "cancelled",
                                             "ended": last["status"]}))
                    return True
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
        if action == "ask":
            err = J.Store.check_question(b.get("question"))
            if err:
                raise Refuse(400, err)
            if j["question"] and j["question"]["id"] == b["question"]["id"]:
                # The same question again: the worker's shell call timed out while the user
                # was still deciding. Resume waiting on it - do not re-ask or reset its clock.
                return {"resumed": True}
            if j["question"]:
                raise Refuse(409, f"question {j['question']['id']!r} is still open - one at a time")
            s.ask(j, b["question"], b.get("timeout") or 3600)
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
        if action == "ping":
            return None
        if action == "status":
            return {"job": s.public(j)}
        raise Refuse(404, f"no worker action {action!r}")

    def wait_answer(self, h, qid, secs):
        """Long-poll: the answer, a timeout, or the cancel flag - whichever comes first."""
        s = self.s
        end = time.monotonic() + secs
        with s.lock:
            while True:
                j = s.worker_job()
                if not j:
                    j = next((x for x in (s.get(i) for i in s.index) if x and x["status"] ==
                              "timed_out" and (x.get("timed_out") or {}).get("question") == qid), None)
                    reply = {"ok": True, "timeout": True} if j else \
                        {"ok": False, "message": "no claimed job"}
                    break
                j["worker_seen"] = time.time()
                if j["cancel_requested"]:
                    self.finish_cancel(j); s.save(j)
                    reply = {"ok": True, "cancel": True}
                    break
                if qid in j["answers"]:
                    reply = {"ok": True, "answer": {"id": qid, **j["answers"][qid]}}
                    break
                q = j["question"]
                if not q or q["id"] != qid:
                    reply = {"ok": False, "message": f"no open question {qid!r}"}
                    break
                if time.time() >= q["deadline"]:
                    s.time_out(j); s.save(j)
                    reply = {"ok": True, "timeout": True}
                    break
                left = end - time.monotonic()
                if left <= 0:
                    reply = {"ok": True, "answer": None}
                    break
                s.changed.wait(timeout=min(left, 1.0, max(0.05, q["deadline"] - time.time())))
        h._send(200, json.dumps(reply))
        return True

    # ------------------------------------------------------------------ browser answers
    def post_answer(self, h, j, b):
        q = j["question"]
        qid = b.get("id")
        if not q or q["id"] != qid:
            raise Refuse(409, "that question is no longer open")
        if time.time() >= q["deadline"]:
            raise Refuse(409, "that question timed out")
        if q["type"] == "file":
            if b.get("skip") and not q["required"]:
                ans = {"value": None, "skipped": True}
            elif b.get("value") and b["value"] in [o["value"] for o in q["options"]]:
                ans = {"value": b["value"]}              # e.g. "skip" offered as an option
            else:
                raise Refuse(400, "a file question is answered by uploading the file")
        elif b.get("skip"):
            if q["required"]:
                raise Refuse(400, "this question needs an answer")
            ans = {"value": None, "skipped": True}
        elif q["type"] == "choice":
            v, t = b.get("value"), (b.get("text") or "")
            if not isinstance(t, str) or len(t) > MAXA("choice"):
                raise Refuse(400, "answer text too long")
            if v in [o["value"] for o in q["options"]]:
                ans = {"value": v, "text": t.strip() or None}
            elif q["allowText"] and t.strip():
                ans = {"value": None, "text": t.strip()}
            else:
                raise Refuse(400, "pick one of the options")
        else:
            t = b.get("text")
            if not isinstance(t, str) or not t.strip():
                raise Refuse(400, "type an answer")
            if len(t) > MAXA(q["type"]):
                raise Refuse(400, f"answers are limited to {MAXA(q['type'])} characters")
            ans = {"value": t.strip(), "text": t.strip()}
        self.s.answer(j, qid, ans)
        self.s.save(j)
        return {"ok": True}

    # Screenshots and files added to the "Questions or changes?" box (pasted, dropped or
    # picked). Stored inside the job's own hidden folder under a name the SERVER picks; the
    # request then names them by that id, and only ids that exist there are passed on to
    # Claude (as paths it can open).
    IMAGE_TYPES = {"image/png": (".png", b"\x89PNG"), "image/jpeg": (".jpg", b"\xff\xd8\xff"),
                   "image/gif": (".gif", b"GIF8"), "image/webp": (".webp", b"RIFF")}
    MAX_IMAGE = 10 * 1024 * 1024
    IMAGE_ID = re.compile(r"^img-\d+-[0-9a-f]{8}\.(png|jpg|gif|webp)$")
    # Other files, by extension, each with the check its content must pass. A file is never
    # opened or run by the server - this only keeps an executable or a mislabelled blob out.
    _ZIP, _OLE, _TEXT = (b"PK\x03\x04",), (b"\xd0\xcf\x11\xe0",), None
    FILE_TYPES = {".pdf": (b"%PDF",), ".zip": _ZIP, ".xlsx": _ZIP, ".docx": _ZIP, ".pptx": _ZIP,
                  ".xls": _OLE, ".doc": _OLE,
                  **dict.fromkeys((".txt", ".csv", ".tsv", ".json", ".xml", ".jrxml", ".groovy",
                                   ".vm", ".md", ".log", ".sql", ".html", ".htm", ".yaml",
                                   ".yml", ".properties"), _TEXT)}
    FILE_ID = re.compile(r"^file-\d+-[0-9a-f]{8}-[A-Za-z0-9_-][A-Za-z0-9._-]{0,79}$")
    MAX_ATTACH = 10 * 1024 * 1024

    def attach_dir(self, j):
        d = pathlib.Path(j["report"]["folder"]) / ".jti-build" / "attachments"
        if d.is_symlink() or d.parent.is_symlink():
            raise Refuse(400, "attachment folder is a symlink")
        return d

    @classmethod
    def safe_name(cls, raw):
        """The browser's file name reduced to a plain basename the FILE_ID pattern accepts,
        or None when its extension is not one we take."""
        import urllib.parse as _u
        name = os.path.basename(_u.unquote(raw or "").replace("\\", "/")).strip()
        stem, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext not in cls.FILE_TYPES:
            return None, ext
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")[:80 - len(ext)] or "file"
        return stem + ext, ext

    def attach(self, h, j):
        import secrets as _s
        if j["status"] != "complete":
            raise Refuse(409, "files can be added once the report is built")
        kind = (h.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        raw_name = h.headers.get("X-JTI-Name")
        # A picture is a picture whether it was pasted (no name) or picked from disk; a file
        # with a picture's extension but no picture type from the browser is treated the same.
        by_ext = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".gif": "image/gif", ".webp": "image/webp"}
        if kind not in self.IMAGE_TYPES and raw_name:
            kind = by_ext.get(os.path.splitext(raw_name)[1].lower(), kind)
        if kind in self.IMAGE_TYPES:
            ext, magic = self.IMAGE_TYPES[kind]
            magics, stem = (magic,), "img"
        elif raw_name:
            name, ext = self.safe_name(raw_name)
            if name is None:
                raise Refuse(415, f"a {ext or 'file without an extension'} file cannot be attached - "
                                  "pictures, PDF, Word, Excel, zip and text files can")
            magics, stem = self.FILE_TYPES[ext], "file"
        else:
            raise Refuse(415, "only a PNG, JPEG, GIF or WebP picture can be pasted")
        n = h.headers.get("Content-Length")
        if n is None:
            raise Refuse(411, "Content-Length is required")
        n = int(n)
        if n <= 0 or n > self.MAX_ATTACH:
            raise Refuse(413, "files are limited to 10 MB each")
        data = h.rfile.read(n)
        if len(data) != n:
            raise Refuse(400, "the upload was cut short")
        if magics is self._TEXT:
            if b"\0" in data[:65536]:
                raise Refuse(400, "that is not a text file")
        elif not any(data.startswith(m) for m in magics):
            raise Refuse(400, "that file is not the type its name says")
        d = self.attach_dir(j)
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        tag = f"{int(time.time())}-{_s.token_hex(4)}"
        fid = f"img-{tag}{ext}" if stem == "img" else f"file-{tag}-{name}"
        with open(d / fid, "xb") as f:
            f.write(data)
        os.chmod(d / fid, 0o600)
        return {"ok": True, "id": fid, "bytes": n, "kind": "image" if stem == "img" else "file"}

    def attached(self, j, b):
        """(image paths, file paths) for the attachments a request names - ids the server
        issued for THIS job only. Anything else is refused rather than silently dropped."""
        imgs, files = b.get("images") or [], b.get("files") or []
        if not isinstance(imgs, list) or not isinstance(files, list):
            raise Refuse(400, "attachments must be lists")
        if len(imgs) + len(files) > J.Store.MAX_IMAGES:
            raise Refuse(400, f"up to {J.Store.MAX_IMAGES} attachments per message")
        d = self.attach_dir(j)

        def paths(ids, pat, what):
            out = []
            for i in ids:
                p = d / str(i)
                if not isinstance(i, str) or not pat.match(i) or p.is_symlink() or not p.is_file():
                    raise Refuse(400, f"an attached {what} was not found - add it again")
                out.append(str(p))
            return out
        return paths(imgs, self.IMAGE_ID, "picture"), paths(files, self.FILE_ID, "file")

    def upload(self, h, j, qid):
        """The file for a `file` question, streamed to the job's own upload folder. The name
        is reduced to a safe basename; nothing about the path comes from the browser."""
        import re as _re
        q = j["question"]
        if not q or q["id"] != qid or q["type"] != "file":
            raise Refuse(409, "no open file question with that id")
        n = h.headers.get("Content-Length")
        if n is None:
            raise Refuse(411, "Content-Length is required")
        n = int(n)
        if n <= 0 or n > J.MAX_UPLOAD:
            raise Refuse(413, f"files are limited to {J.MAX_UPLOAD // (1024 * 1024)} MB")
        raw = urllib.parse.unquote(h.headers.get("X-JTI-Filename") or "upload")
        name = _re.sub(r"[^A-Za-z0-9._-]+", "_", pathlib.PurePath(raw).name).lstrip(".")[:120] or "upload"
        up = pathlib.Path(j["report"]["folder"]) / ".jti-build" / "uploads"
        if up.is_symlink() or up.parent.is_symlink():
            raise Refuse(400, "upload folder is a symlink")
        up.mkdir(mode=0o700, parents=True, exist_ok=True)
        dest = up / name
        if dest.exists():
            dest = up / f"{int(time.time())}-{name}"
        left = n
        with open(dest, "xb") as f:
            while left:
                chunk = h.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk); left -= len(chunk)
        if left:
            dest.unlink()
            raise Refuse(400, "the upload was cut short")
        with self.s.lock:
            j = self.s.get(j["id"])
            if not j["question"] or j["question"]["id"] != qid:
                dest.unlink()
                raise Refuse(409, "that question closed while the file was uploading")
            self.s.answer(j, qid, {"value": str(dest), "file": str(dest),
                                   "name": pathlib.PurePath(raw).name[:200], "bytes": n})
            self.s.save(j)
        return {"ok": True, "name": name, "bytes": n}

    def download(self, h, j, action, aid):
        """Only a COMPLETE job's registered artifacts, looked up by the id the server gave
        them - never by a path from the URL - re-checked inside the folder and against the
        hash recorded at completion."""
        if j["status"] != "complete":
            raise Refuse(409, "nothing to download - this build did not complete")
        folder = pathlib.Path(j["report"]["folder"])

        def load(a):
            p = safe_file(folder, a["rel"])
            if not p or J.sha(str(p)) != a["sha256"]:
                raise Refuse(409, f"{a['name']} changed or moved since the build finished")
            return p.read_bytes()
        if action == "package":
            import io
            import zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for a in j["artifacts"]:
                    if a["kind"] != "page":                 # page images are previews only
                        z.writestr(a["rel"], load(a))
            name = safe_name(j["report"]["name"]) + "-package.zip"
            h._send(200, buf.getvalue(), "application/zip",
                    {"Content-Disposition": f'attachment; filename="{name}"'})
            return True
        a = next((x for x in j["artifacts"] if x["id"] == aid), None)
        if not a or (action == "preview" and a["kind"] != "page"):
            raise Refuse(404, "no such file in this build")
        ext = pathlib.PurePath(a["name"]).suffix.lower()
        disp = "inline" if action == "preview" else "attachment"
        h._send(200, load(a), CTYPE.get(ext, "application/octet-stream"),
                {"Content-Disposition": f'{disp}; filename="{safe_name(a["name"])}"'})
        return True

    def claimed(self, j):
        folder = pathlib.Path(j["report"]["folder"])
        spec = J.Store._read(folder / j["spec"]) or {}
        return {"id": j["id"], "folder": str(folder), "spec_path": str(folder / j["spec"]),
                "spec": spec, "destination": j["report"]["destination"],
                "helper": str(pathlib.Path(J.HERE) / "jobs.py"),
                # Set when the user asked for changes to the report this job already built.
                "revision": j.get("revision")}

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
        """Finish ONLY a verified build. Every gate must have passed with no failure since,
        and the rule, .jrxml and zip must still be byte-for-byte what was verified. Then the
        deliverables are registered by the server - the browser can download those and
        nothing else."""
        s = self.s
        g = j.get("gates")
        if not g or not g.get("ok"):
            raise Refuse(409, "the gates have not passed for this job - nothing is complete "
                              "until `jobs.py run --gates` passes")
        folder = pathlib.Path(j["report"]["folder"]).resolve()
        for name, want in g["files"].items():
            p = safe_file(folder, name)
            if not p or J.sha(str(p)) != want:
                raise Refuse(409, f"{name} changed after the gates passed - run them again")
        # The documents must have been WRITTEN, not just generated: a NOTES block still
        # holding contract_docs' "TODO before this ships" seed is an unfinished handoff.
        import contract_docs as CD
        for name in ("verification/RULE_REGISTRATION.txt", "verification/JRXML_CONTRACT.txt"):
            p = safe_file(folder, name)
            t = p.read_text(encoding="utf8", errors="replace") if p else ""
            i = t.find(CD.BEGIN)
            if i >= 0 and t[i + len(CD.BEGIN):].lstrip().startswith("TODO before this ships"):
                raise Refuse(409, f"{name} still has its unfilled NOTES seed - fill it (the "
                                  f"documentation stage) before completing")
        arts = []

        def add(kind, rel):
            p = safe_file(folder, rel)
            if p:
                arts.append({"id": f"a{len(arts) + 1}", "kind": kind, "name": p.name,
                             "rel": str(p.relative_to(folder)), "bytes": p.stat().st_size,
                             "sha256": J.sha(str(p))})
        for name in g["files"]:
            add("rule" if name.endswith(".groovy") else "jrxml" if name.endswith(".jrxml")
                else "rule-zip", name)
        for name in ("verification/RULE_REGISTRATION.txt", "verification/JRXML_CONTRACT.txt"):
            add("doc", name)
        # The folder-view launcher (static-text Velocity), generated from spec.launcher.
        add("launcher", safe_name(j["report"]["name"]) + "_Launcher.vm")
        vdir = folder / "verification"
        if vdir.is_dir() and not vdir.is_symlink():
            for p in sorted(vdir.glob("*.pdf")):
                add("pdf", f"verification/{p.name}")
            for p in sorted(vdir.glob("*.png")):
                add("page", f"verification/{p.name}")
        kinds = {a["kind"] for a in arts}
        missing = [k for k in ("rule", "jrxml", "rule-zip", "doc", "pdf") if k not in kinds]
        if missing:
            raise Refuse(409, f"cannot complete - no verified {', '.join(missing)} in the report folder")
        j["artifacts"] = arts
        s.done(j, "complete", "Report built and verified")
        j["status"], j["running"] = "complete", False
        s.event(j, "complete", "complete", f"{len(arts)} files ready")
        return {"artifacts": arts}

    STALE_WORKER = 300          # seconds without a helper call before cancel stops waiting

    def cancel(self, j):
        """Set the persistent cancel flag. The worker sees it on its very next helper call
        (every call reports it; a running child is polled every half second and stopped).
        Nothing is deleted. A job nobody is working on is cancelled at once."""
        if j["status"] in J.TERMINAL:
            raise Refuse(409, f"this build already ended ({j['status']})")
        j["cancel_requested"] = True
        seen = j.get("worker_seen") or 0
        if j["status"] == "submitted" or time.time() - seen > self.STALE_WORKER:
            self.finish_cancel(j)
        else:
            j["status"], j["running"] = "cancelling", False
            j["status_text"] = "Cancelling - waiting for the current step to stop"
            self.s.event(j, "cancel_requested", j["stage"], j["status_text"], "warn")
        self.s.save(j)
        return {"ok": True, "status": j["status"]}

    def finish_cancel(self, j):
        j["status"], j["running"] = "cancelled", False
        j["partial"] = self.s.created_files(j)
        j["status_text"] = "Cancelled"
        self.s.event(j, "cancelled", j["stage"], "Cancelled - nothing was deleted", "warn")
