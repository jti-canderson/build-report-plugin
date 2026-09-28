"""harness_marker.py - stamp and check the scaffold's verification/run.sh.

The fast verifier replaces run.sh with its own one-JVM path, so it may do that ONLY for a
harness it knows is exactly what scaffold.py wrote. Loose substring matching was not enough:
a customised run.sh can keep `render_check.groovy`, `--variant` and the WANT line while adding
a required step, and fast mode then skipped that step and reported success where legacy failed.

So scaffold.py stamps line 2 of every run.sh it writes:

    # JTI_SCAFFOLD_HARNESS_VERSION=1 sha256=<hash of the file with this line removed>

check() accepts only that exact form, an exactly supported version, and a matching hash. An
unmarked harness (every report scaffolded before this), an unknown or newer version, a malformed
marker, more than one marker, or ANY edit to the file after generation all fail - and the caller
falls back to the legacy gates, which run the harness as written. One implementation, shared by
the writer and the checker, so they cannot drift.
"""
import hashlib
import re

SUPPORTED = {1}
CURRENT = 1
LINE = re.compile(r"^# JTI_SCAFFOLD_HARNESS_VERSION=(\S*) sha256=(\S*)$")
LOOSE = re.compile(r"JTI_SCAFFOLD_HARNESS_VERSION")


def _body_hash(lines):
    return hashlib.sha256("\n".join(lines).encode("utf8")).hexdigest()


def stamp(text):
    """Insert the marker after the shebang. The hash covers every other line."""
    lines = text.split("\n")
    marker = f"# JTI_SCAFFOLD_HARNESS_VERSION={CURRENT} sha256={_body_hash(lines)}"
    return "\n".join(lines[:1] + [marker] + lines[1:])


def check(text):
    """(True, 'version N') for an exact, unmodified, supported harness; else (False, reason)."""
    lines = text.split("\n")
    hits = [i for i, ln in enumerate(lines) if LOOSE.search(ln)]
    if not hits:
        return False, "verification/run.sh has no JTI_SCAFFOLD_HARNESS_VERSION marker"
    if len(hits) > 1:
        return False, "verification/run.sh has more than one harness marker"
    i = hits[0]
    m = LINE.match(lines[i])
    if not m or i != 1:
        return False, "the harness marker is malformed or not on line 2"
    ver, digest = m.group(1), m.group(2)
    if not ver.isdigit() or int(ver) not in SUPPORTED:
        return False, f"harness version {ver!r} is not supported by this verifier ({sorted(SUPPORTED)})"
    if _body_hash(lines[:i] + lines[i + 1:]) != digest:
        return False, "verification/run.sh was modified after scaffold.py wrote it"
    return True, f"version {ver}"
