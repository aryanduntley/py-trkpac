"""Python-version health checks.

A Python minor-version upgrade (e.g. 3.13 -> 3.14) silently breaks every
compiled (C-extension) package in the managed target directory, because
those .so files are ABI-locked to the CPython minor version they were
built for. py-trkpac itself is stdlib-only and survives, but the packages
it manages do not.

This module records the Python version packages were installed under,
detects when the running interpreter no longer matches, warns loudly with
an actionable fix, and prunes foreign-ABI binaries during a rebuild.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from py_trkpac.utils import info

if TYPE_CHECKING:
    from py_trkpac.db import Database

PYTHON_VERSION_KEY = "python_version"

# Matches the CPython ABI tag in extension filenames, e.g.
# "_cffi_backend.cpython-313-x86_64-linux-gnu.so" -> ("3", "13").
# Version-agnostic stable-ABI files ("name.abi3.so") deliberately do not
# match and are never pruned.
_ABI_SO_RE = re.compile(r"\.cpython-(\d)(\d+)[^/]*\.so$")


def current_python_version() -> str:
    """The running interpreter's version as 'major.minor' (e.g. '3.14')."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _abi_tag_to_version(major: str, minor: str) -> str:
    return f"{int(major)}.{int(minor)}"


def detect_target_abi(target_path: Path) -> str | None:
    """Infer which Python the installed binaries were built for.

    Scans the target tree for ``*.cpython-NN*.so`` files and returns the
    most common 'major.minor' tag, or None if there are no tagged
    extensions (a pure-Python environment, where no mismatch can occur).

    Bounded so this stays cheap even on large trees: it stops after
    sampling enough tagged files to decide.
    """
    if not target_path.is_dir():
        return None

    counts: dict[str, int] = {}
    sampled = 0
    for root, dirs, files in os.walk(target_path):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for fname in files:
            m = _ABI_SO_RE.search(fname)
            if not m:
                continue
            ver = _abi_tag_to_version(m.group(1), m.group(2))
            counts[ver] = counts.get(ver, 0) + 1
            sampled += 1
        if sampled >= 200:
            break

    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def _warn(recorded: str, current: str) -> None:
    bar = "=" * 70
    info(bar)
    info(" WARNING: Python changed since your packages were installed.")
    info("")
    info(f"   Installed for Python {recorded}, but now running {current}.")
    info("   Compiled (C-extension) packages WILL fail to import until")
    info("   they are rebuilt for the new interpreter.")
    info("")
    info("   Fix:  py-trkpac rebuild")
    info(bar)


def check_python_version(db: "Database") -> None:
    """Warn (on first lines of output) if the interpreter changed.

    Cheap in the common case: one config read and a string compare.
    Legacy databases predating version tracking are backfilled — inferred
    from installed binaries when possible — so the very upgrade that
    motivated this feature is still caught for existing users.
    """
    current = current_python_version()
    recorded = db.get_config(PYTHON_VERSION_KEY)

    if recorded is None:
        target = db.get_config("target_path")
        detected = detect_target_abi(Path(target)) if target else None
        recorded = detected or current
        db.set_config(PYTHON_VERSION_KEY, recorded)

    if recorded != current:
        _warn(recorded, current)


def record_python_version(db: "Database") -> None:
    """Stamp the current interpreter as the one packages were built for.

    Called after any successful install/update/rebuild so the recorded
    version stays accurate and the warning clears once packages match.
    """
    db.set_config(PYTHON_VERSION_KEY, current_python_version())


def prune_foreign_abi(target_path: Path) -> int:
    """Delete extension files built for a different Python ABI.

    pip ``--upgrade`` reinstalls a package's Python code, but a wheel
    built for a new interpreter ships a *differently named* .so
    (``cpython-313`` vs ``cpython-314``), so the stale, unloadable binary
    is left behind to shadow nothing — or worse, linger as dead weight.
    This removes any ``*.cpython-NN*.so`` whose tag is not the running
    interpreter's, then clears all ``__pycache__`` dirs (regenerated on
    demand). Returns the number of .so files removed.
    """
    if not target_path.is_dir():
        return 0

    current = current_python_version()
    removed = 0
    pycache_dirs: list[Path] = []

    for root, dirs, files in os.walk(target_path):
        if "__pycache__" in dirs:
            pycache_dirs.append(Path(root) / "__pycache__")
            dirs.remove("__pycache__")
        for fname in files:
            m = _ABI_SO_RE.search(fname)
            if not m:
                continue
            if _abi_tag_to_version(m.group(1), m.group(2)) != current:
                try:
                    (Path(root) / fname).unlink()
                    removed += 1
                except OSError:
                    pass

    for pd in pycache_dirs:
        shutil.rmtree(pd, ignore_errors=True)

    return removed
