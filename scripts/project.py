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

    project.py list
    project.py resolve  <name|path> [--create]
    project.py sdk-status <project-folder>

Status commands always exit 0 and print a leading token (NONE / OK / STALE / MISSING).
"No SDK on file" is a normal state, not a failure, and a non-zero exit for it surfaces
as a red error in the caller's UI for something that is merely a question to ask.
    project.py sdk-register <project-folder> <file>
"""
import datetime
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path.home() / "JaspersoftWorkspace" / "MyReports"
META = ".jti-project.json"
STALE_DAYS = 180
# Tooling that lives beside the projects but is not one.
NOT_A_PROJECT = {"JTI Report Templates", "jti-reports-plugin", "Entities",
                 "Older Versions", "bin", "lib"}


def _meta(folder):
    p = pathlib.Path(folder) / META
    return json.loads(p.read_text()) if p.exists() else {}


def _write(folder, data):
    (pathlib.Path(folder) / META).write_text(json.dumps(data, indent=2) + "\n")


def cmd_list():
    """Every folder that looks like a report project: registered, or holding reports."""
    out = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in NOT_A_PROJECT:
            continue
        m = _meta(d)
        reports = [x for x in d.iterdir()
                   if x.is_dir() and any(x.glob("*.jrxml"))] if d.is_dir() else []
        if m or reports:
            out.append((d.name, len(reports), bool(m.get("sdk")), m.get("environment")))
    if not out:
        print("no projects yet")
        return
    print(f"  {'project':<34} {'reports':>7}  {'SDK':<5} environment")
    for name, n, sdk, env in out:
        print(f"  {name:<34} {n:>7}  {'yes' if sdk else 'no ':<5} {env or '-'}")


def cmd_resolve(name, create=False):
    p = pathlib.Path(name)
    folder = p if p.is_absolute() else ROOT / name
    if not folder.exists():
        if not create:
            print(f"MISSING {folder}   (pass --create to make it)")
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
    folder = pathlib.Path(folder)
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
    folder, src = pathlib.Path(folder), pathlib.Path(src).expanduser()
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
    if c == "list":
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
