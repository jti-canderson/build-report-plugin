#!/usr/bin/env python3
"""
Project and SDK bookkeeping for /build-report.

A project is a folder of reports for one client, carrying a `.jti-project.json`:

    { "project": "OKDAC",
      "environment": "okdac-qa-symphony.ecourt.com",
      "sdk": { "filename": "...", "stored": "sdk/...", "sha256": "...",
               "registered": "2026-09-02", "size": 12345 } }

The SDK matters because the local render harness is pinned to whatever JasperReports
and domain classes are on THIS machine. For a client that is not OKDAC that is a guess,
and a wrong guess is silent: the report compiles here and behaves differently there.

    project.py root                 which folder the plugin is scoped to, and why
    project.py list
    project.py resolve  <name|relative path> [--create]
    project.py sdk-status <project-folder>

SCOPE: every path this touches is resolved under the WORKSPACE ROOT and a path that
escapes it is refused. The plugin has no business anywhere else, and a tool that writes
outside the folder you handed it is a tool you have to supervise.

The root is NOT plain cwd - cwd moves whenever anything runs `cd`, which silently changed
what the plugin could see. It is, in order: $JTI_PROJECT_ROOT, the nearest ancestor with a
`.jti-root` file, the nearest ancestor holding `jti-reports-plugin/`, else cwd. Every
command prints the root it used; `project.py root` explains the choice.

Status commands always exit 0 and print a leading token (NONE / OK / STALE / MISSING).
"No SDK on file" is a normal state, not a failure, and a non-zero exit for it surfaces
as a red error in the caller's UI for something that is merely a question to ask.
    project.py sdk-register <project-folder> <file>
"""
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import sys

MARKER = ".jti-root"


def _find_root():
    """The workspace root, and how it was decided.

    NOT simply cwd. cwd was the rule until 09/09 and it is mutable shell state: any `cd`
    in any command moves it, so a session that wandered into a report folder listed no
    projects and a session that wandered into the plugin folder listed the plugin's own
    subfolders as if they were clients. The user sees "my project is missing" and nothing
    explains why. A permission grant has to be stable for the session; cwd is not.

    Order, most explicit first:
      1. JTI_PROJECT_ROOT          - set it deliberately, it always wins
      2. the nearest ancestor holding a .jti-root marker
      3. the nearest ancestor holding the plugin itself
      4. cwd, as before
    Hardcoding ~/JaspersoftWorkspace/MyReports (as this did until 09/03) is still wrong -
    the plugin must work for anyone whose reports live somewhere else.
    """
    env = os.environ.get("JTI_PROJECT_ROOT")
    if env:
        return pathlib.Path(env).resolve(), "JTI_PROJECT_ROOT"
    here = pathlib.Path.cwd().resolve()
    for d in [here] + list(here.parents):
        if (d / MARKER).exists():
            return d, f"{MARKER} marker"
    for d in [here] + list(here.parents):
        if (d / "jti-reports-plugin").is_dir():
            return d, "folder holding jti-reports-plugin"
    return here, "current directory"


ROOT, ROOT_WHY = _find_root()
# Folder names that are never a client project. A report build that derives its project
# from an attachment's path lands here - a file sitting in ~/Downloads says where the
# browser put it, not who the report is for. Creating one of these leaves junk the user has
# to notice and delete, so refuse and make the caller ask. Caught 09/09.
# NB: distinct from NOT_A_PROJECT below, which excludes tooling folders from `list`.
# These two were briefly given the same name and the second silently shadowed the first,
# so this guard compared against the wrong set and created the folder it was meant to
# refuse - a guard that looked right in isolation and did nothing.
NOT_A_PROJECT_NAME = {"downloads", "desktop", "documents", "tmp", "temp", "trash",
                      "untitled folder", "new folder", "inbox", "attachments"}

META = ".jti-project.json"
STALE_DAYS = 180
# Tooling that lives beside the projects but is not one.
NOT_A_PROJECT = {"JTI Report Templates", "jti-reports-plugin", "Entities",
                 "Older Versions", "bin", "lib"}


def _under_root(path):
    """The path, resolved, if it is inside ROOT - else None. Symlinks and .. are resolved
    FIRST, so neither can be used to step out."""
    try:
        p = pathlib.Path(path).expanduser().resolve()
    except OSError:
        return None
    return p if p == ROOT or ROOT in p.parents else None


def _meta(folder):
    p = pathlib.Path(folder) / META
    return json.loads(p.read_text()) if p.exists() else {}


def _write(folder, data):
    (pathlib.Path(folder) / META).write_text(json.dumps(data, indent=2) + "\n")


def _is_report(d):
    """A folder holding a .jrxml IS a report - it is never a project to build INTO."""
    return any(d.glob("*.jrxml"))


def _reports_in(d):
    try:
        return [x for x in d.iterdir() if x.is_dir() and _is_report(x)]
    except OSError:
        return []


def cmd_root():
    """Explain the scope, for when a project is 'missing'."""
    print(f"  root   {ROOT}")
    print(f"  chosen {ROOT_WHY}")
    print(f"  cwd    {pathlib.Path.cwd()}")
    if ROOT_WHY == "current directory":
        print("\n  This is the weakest anchor: cwd moves whenever anything runs `cd`, so what")
        print("  the plugin can see changes under you. Drop a .jti-root file in your")
        print("  workspace folder to pin it.")


def cmd_list():
    """Report projects visible from ROOT: ROOT itself if it qualifies, plus any child that
    is a project rather than a report.

    The distinction that matters, and the one an earlier cut got wrong twice: a folder
    holding a .jrxml is a REPORT and must never be offered as somewhere to build a report
    INTO, while a folder holding report folders is a PROJECT. ROOT can be both a project
    and a container of them - MyReports holds seven loose reports AND three client
    projects - so both get listed rather than one hiding the other."""
    rows = []
    m = _meta(ROOT)
    if m or _reports_in(ROOT):
        rows.append((f"{ROOT.name}  (here)", len(_reports_in(ROOT)),
                     bool(m.get("sdk")), m.get("environment")))
    try:
        children = sorted(ROOT.iterdir())
    except OSError:
        children = []
    for d in children:
        if not d.is_dir() or d.name.startswith(".") or d.name in NOT_A_PROJECT:
            continue
        if _is_report(d):          # a report of ROOT's, already counted above
            continue
        cm, reports = _meta(d), _reports_in(d)
        if cm or reports:
            rows.append((d.name, len(reports), bool(cm.get("sdk")), cm.get("environment")))
    if not rows:
        print(f"no projects yet under {ROOT}")
        print(f"  (root chosen by: {ROOT_WHY})")
        print("  If a project of yours is missing, the root is wrong, not the project.")
        print("  Put a .jti-root file in your workspace folder, or set JTI_PROJECT_ROOT.")
        return
    # Always say what the scope IS. A silent scope is what made a missing project look
    # like a missing project instead of a wrong root.
    print(f"  root  {ROOT}   ({ROOT_WHY})")
    print(f"  {'project':<34} {'reports':>7}  {'SDK':<5} environment")
    for name, n, sdk, env in rows:
        print(f"  {name:<34} {n:>7}  {'yes' if sdk else 'no ':<5} {env or '-'}")


def cmd_resolve(name, create=False):
    p = pathlib.Path(name).expanduser()
    folder = _under_root(p if p.is_absolute() else ROOT / name)
    if folder is None:
        print(f"REFUSED {name}   (outside {ROOT} - this plugin only works in the folder "
              f"you started it in)")
        return 0
    if not folder.exists():
        if not create:
            print(f"MISSING {folder}   (pass --create to make it)")
            return 0
        if folder.name.strip().lower() in NOT_A_PROJECT_NAME:
            # Creating this would turn a filesystem accident into a client folder.
            print(f"REFUSED {folder.name!r} is not a project name.")
            print("  This is where a file happened to be sitting, not who the report is")
            print("  for. Ask which project it belongs to and pass that name instead.")
            return 0
        folder.mkdir(parents=True)
        _write(folder, {"project": folder.name,
                        "created": datetime.date.today().isoformat()})
        print(f"CREATED {folder}")
        return 0
    if not (folder / META).exists():
        m = {"project": folder.name, "created": datetime.date.today().isoformat()}
        _write(folder, m)
        print(f"ADOPTED {folder}   (existing folder, now registered)")
        return 0
    print(f"FOUND   {folder}")
    return 0


def cmd_sdk_status(folder):
    folder = _under_root(folder)
    if folder is None:
        print(f"REFUSED outside {ROOT}")
        return 0
    m = _meta(folder)
    sdk = m.get("sdk")
    if not sdk:
        print("NONE    no SDK/JAR recorded for this project")
        return 0
    reg = datetime.date.fromisoformat(sdk["registered"])
    age = (datetime.date.today() - reg).days
    stored = folder / sdk["stored"]
    if not stored.exists():
        print(f"MISSING recorded as {sdk['filename']} but the file is gone")
        return 0
    state = "STALE  " if age >= STALE_DAYS else "OK     "
    print(f"{state} {sdk['filename']}  registered {sdk['registered']} "
          f"({age} day{'s' if age != 1 else ''} ago, {sdk['size'] // 1024} KB)")
    return 0


def cmd_sdk_register(folder, src):
    # The SOURCE may sit anywhere - it is a file the user just handed over, typically from
    # Downloads. The DESTINATION may not: the copy lands inside the project folder or not
    # at all.
    folder, src = _under_root(folder), pathlib.Path(src).expanduser()
    if folder is None:
        print(f"REFUSED outside {ROOT}")
        return 0
    if not src.exists():
        print(f"no such file: {src}")
        return 2
    dest_dir = folder / "sdk"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    h = hashlib.sha256(dest.read_bytes()).hexdigest()[:16]
    m = _meta(folder)
    prev = m.get("sdk")
    m["sdk"] = {"filename": src.name, "stored": f"sdk/{src.name}", "sha256": h,
                "registered": datetime.date.today().isoformat(),
                "size": dest.stat().st_size}
    if prev:
        m.setdefault("sdk_history", []).append(prev)
    _write(folder, m)
    same = prev and prev.get("sha256") == h
    print(f"SAVED   {dest.relative_to(folder)}  sha {h}"
          + ("   (identical to the previous one)" if same else ""))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__.strip())
        sys.exit(2)
    c = a[0]
    if c == "root":
        cmd_root()
    elif c == "list":
        cmd_list()
    elif c == "resolve":
        sys.exit(cmd_resolve(a[1], "--create" in a))
    elif c == "sdk-status":
        sys.exit(cmd_sdk_status(a[1]))
    elif c == "sdk-register":
        sys.exit(cmd_sdk_register(a[1], a[2]))
    else:
        print(__doc__.strip())
        sys.exit(2)
