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
    project.py sdk-decide <project-folder>   exit 0 = current SDK, don't ask; 10 = ask (stale);
                                             11 = REQUIRED: no usable SDK, the build waits for one

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
    project.py dd-register  <project-folder> <DataDictionary-*.xlsx>   the project's Data
                                             Dictionary export: what the field browser reads
    project.py dd-status    <project-folder>
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


def list_projects():
    """The projects, as data. ONE definition, because the builder page needs the same list
    the command does - and a second hand-written copy of this filter immediately disagreed
    with it (09/18: the page offered `jti-report-deploy-plugin` and two folders holding no
    reports, none of which `list` shows).

    The distinction that matters, and the one an earlier cut got wrong twice: a folder
    holding a .jrxml is a REPORT and must never be offered as somewhere to build a report
    INTO, while a folder holding report folders is a PROJECT. ROOT can be both - MyReports
    holds loose reports AND client projects - so both get listed rather than one hiding
    the other. A child qualifies only if it carries project metadata or actually holds
    reports; an empty folder is not a project.
    """
    out = []
    m = _meta(ROOT)
    if m or _reports_in(ROOT):
        out.append({"name": ".", "label": f"{ROOT.name}  (here)",
                    "reports": len(_reports_in(ROOT)), "sdk": bool(m.get("sdk")), "dd": bool(m.get("dd")),
                    "environment": m.get("environment")})
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
            out.append({"name": d.name, "label": d.name, "reports": len(reports),
                        "sdk": bool(cm.get("sdk")), "dd": bool(cm.get("dd")),
                        "environment": cm.get("environment")})
    return out


def cmd_list():
    """Report projects visible from ROOT: ROOT itself if it qualifies, plus any child that
    is a project rather than a report.

    The distinction that matters, and the one an earlier cut got wrong twice: a folder
    holding a .jrxml is a REPORT and must never be offered as somewhere to build a report
    INTO, while a folder holding report folders is a PROJECT. ROOT can be both a project
    and a container of them - MyReports holds seven loose reports AND three client
    projects - so both get listed rather than one hiding the other."""
    rows = [(r["label"], r["reports"], r["sdk"], r["environment"])
            for r in list_projects()]
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


ASK = 10        # sdk-decide: the user has to be asked (the SDK is stale; they may go on without)
REQUIRED = 11   # sdk-decide: no usable SDK in the project - the build cannot go on without one


def cmd_sdk_decide(folder):
    """Decide - in code, not in the model's judgement - whether a build must stop and ask.

    Exit 0 and one line to put in the build log and the handoff when a current, readable SDK
    is on file: nobody needs to confirm a file they registered months ago and that has not
    gone stale. Exit REQUIRED (11) when the project has no usable SDK - none recorded, the
    recorded file is gone, or it cannot be read: the build asks for one and does not go on
    without it, because without it no field is checked and a wrong one prints a blank column
    with no error. Exit ASK (10) when the SDK is only STALE: ask, but the user may go on.

    `sdk-status` is unchanged; this is what fast-mode builds call instead. Deciding here
    makes the no-question path deterministic and testable, rather than a sentence in the
    command the model may or may not weigh the same way twice.
    """
    folder = _under_root(folder)
    if folder is None:
        print(f"ASK     outside {ROOT} - cannot check the SDK")
        return ASK
    sdk = _meta(folder).get("sdk")
    if not sdk:
        print("REQUIRED no SDK/JAR recorded for this project")
        return REQUIRED
    stored = folder / sdk["stored"]
    if not stored.exists():
        print(f"REQUIRED recorded as {sdk['filename']} but the file is gone")
        return REQUIRED
    age = (datetime.date.today() - datetime.date.fromisoformat(sdk["registered"])).days
    # READABLE, not merely present: a truncated download or a renamed HTML error page sits on
    # disk looking like an SDK. A jar/xlsx is a zip, so it has to open as one.
    try:
        if stored.suffix.lower() in (".jar", ".zip", ".xlsx"):
            import zipfile
            with zipfile.ZipFile(stored) as z:
                if not z.namelist():
                    raise ValueError("empty archive")
        elif stored.stat().st_size == 0 or not os.access(stored, os.R_OK):
            raise ValueError("empty or unreadable")
    except Exception as e:                                  # noqa: BLE001
        print(f"REQUIRED {sdk['filename']} is on file but cannot be read ({type(e).__name__})")
        return REQUIRED
    if age >= STALE_DAYS:       # after the read check: a stale file that cannot be read is no SDK
        print(f"ASK     {sdk['filename']} is {age} days old (stale after {STALE_DAYS})")
        return ASK
    print(f"SDK     {sdk['filename']}, registered {sdk['registered']} ({age} day"
          f"{'s' if age != 1 else ''} ago) - current; used without asking")
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


def dd_check(path):
    """None if `path` is a Data Dictionary export, else why not. An .xlsx is a zip; the
    export's first sheet has entity rows (name in column A) and field rows under them."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            if not any(n.startswith("xl/worksheets/") for n in z.namelist()):
                return "not a spreadsheet (.xlsx)"
    except (zipfile.BadZipFile, OSError):
        return "not a spreadsheet (.xlsx)"
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "skills" /
                           "report-deployment" / "scripts"))
    import dd_resolve as D
    rows = 0
    for r in D.xlsx_rows(str(path)):
        if len(r) > 2 and not r[0].strip() and r[1].strip() and r[2].strip():
            rows += 1
            if rows >= 20:
                return None
    return "no entity/field rows - export it from eSeries: System Setup -> Data Dictionary"


def cmd_dd_register(folder, src):
    """Copy a Data Dictionary export into <project>/dd/ and record it, like sdk-register."""
    folder, src = _under_root(folder), pathlib.Path(src).expanduser()
    if folder is None:
        print(f"REFUSED outside {ROOT}")
        return 0
    if not src.exists():
        print(f"no such file: {src}")
        return 2
    why = dd_check(src)
    if why:
        print(f"REFUSED {src.name}: {why}")
        return 2
    dest_dir = folder / "dd"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    h = hashlib.sha256(dest.read_bytes()).hexdigest()[:16]
    m = _meta(folder)
    prev = m.get("dd")
    m["dd"] = {"filename": src.name, "stored": f"dd/{src.name}", "sha256": h,
               "registered": datetime.date.today().isoformat(), "size": dest.stat().st_size}
    if prev:
        m.setdefault("dd_history", []).append(prev)
    _write(folder, m)
    print(f"SAVED   {dest.relative_to(folder)}  sha {h}")
    return 0


def cmd_dd_status(folder):
    folder = _under_root(folder)
    dd = _meta(folder).get("dd") if folder else None
    if not dd:
        print("NONE    no Data Dictionary on file")
    elif not (folder / dd["stored"]).exists():
        print(f"MISSING {dd['stored']} is recorded but gone")
    else:
        print(f"OK      {dd['filename']} (registered {dd['registered']})")
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
    elif c == "sdk-decide":
        sys.exit(cmd_sdk_decide(a[1]))
    elif c == "sdk-register":
        sys.exit(cmd_sdk_register(a[1], a[2]))
    elif c == "dd-register":
        sys.exit(cmd_dd_register(a[1], a[2]))
    elif c == "dd-status":
        sys.exit(cmd_dd_status(a[1]))
    else:
        print(__doc__.strip())
        sys.exit(2)
