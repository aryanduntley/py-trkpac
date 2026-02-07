"""pip subprocess wrapper, .dist-info snapshot/diff, METADATA and RECORD parsing."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

from py_trkpac.db import Database
from py_trkpac.utils import normalize_name, info, error


SYSTEM_DIST_PACKAGES = Path("/usr/lib/python3/dist-packages")


def check_system_package(name: str) -> tuple[str, str] | None:
    """Check if a package is installed in system dist-packages.

    Returns (name, version) if found, None otherwise.
    """
    norm = normalize_name(name)
    if not SYSTEM_DIST_PACKAGES.is_dir():
        return None
    for child in SYSTEM_DIST_PACKAGES.iterdir():
        if not (child.is_dir() and child.name.endswith(".dist-info")):
            continue
        dir_name = child.name[: -len(".dist-info")]
        parts = dir_name.rsplit("-", 1)
        if len(parts) == 2 and normalize_name(parts[0]) == norm:
            return (parts[0], parts[1])
    return None


# -- .dist-info snapshot and diffing --

def snapshot_dist_infos(target_path: Path) -> dict[str, str]:
    """Return a dict of {dist-info dir name: modification time as string} for all .dist-info in target."""
    result = {}
    if not target_path.is_dir():
        return result
    for child in target_path.iterdir():
        if child.is_dir() and child.name.endswith(".dist-info"):
            # Use METADATA mtime as a fingerprint for changes
            meta = child / "METADATA"
            mtime = str(meta.stat().st_mtime) if meta.exists() else "0"
            result[child.name] = mtime
    return result


def diff_dist_infos(
    before: dict[str, str], after: dict[str, str]
) -> list[str]:
    """Return list of .dist-info dir names that are new or changed."""
    changed = []
    for name, mtime in after.items():
        if name not in before or before[name] != mtime:
            changed.append(name)
    return changed


# -- METADATA parsing --

def parse_metadata(dist_info_path: Path) -> dict:
    """Parse a METADATA file and return {name, version, requires_dist}."""
    meta_file = dist_info_path / "METADATA"
    result = {"name": None, "version": None, "requires_dist": []}
    if not meta_file.exists():
        return result

    for line in meta_file.read_text(errors="replace").splitlines():
        if line.startswith("Name: "):
            result["name"] = line[6:].strip()
        elif line.startswith("Version: "):
            result["version"] = line[9:].strip()
        elif line.startswith("Requires-Dist: "):
            result["requires_dist"].append(line[15:].strip())
        elif line == "":
            # End of headers
            break
    return result


def parse_dependency_name(requires_dist_entry: str) -> str | None:
    """Extract just the package name from a Requires-Dist entry.

    Examples:
        "numpy (>=1.21)" -> "numpy"
        "torch>=2.0; extra == 'gpu'" -> "torch"
        "typing-extensions; python_version < '3.11'" -> "typing_extensions"

    Returns None for entries that are conditional on extras (extra == '...'),
    since those are optional dependencies not installed by default.
    """
    # Skip entries conditional on extras
    if "extra ==" in requires_dist_entry or "extra==" in requires_dist_entry:
        return None

    # Extract package name (everything before version specifier, semicolon, or space+paren)
    match = re.match(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)", requires_dist_entry)
    if match:
        return normalize_name(match.group(1))
    return None


# -- pyproject.toml parsing for local installs --

def parse_pyproject_name(project_path: Path) -> tuple[str, str] | None:
    """Read pyproject.toml and return (name, version), or None if unparseable."""
    toml_path = project_path / "pyproject.toml"
    if not toml_path.exists():
        return None
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        project = data.get("project", {})
        name = project.get("name")
        version = project.get("version", "0.0.0")
        if not name:
            return None
        return (name, version)
    except (tomllib.TOMLDecodeError, KeyError):
        return None


def resolve_local_packages(packages: list[str]) -> tuple[list[str], dict[str, str]]:
    """Separate package args into pip args and a local-packages mapping.

    Returns:
        pip_args: list of args to pass to pip (local paths kept as-is, PyPI names kept as-is)
        local_packages: dict of {normalized_name: resolved_path_str} for local installs
    """
    local_packages: dict[str, str] = {}  # norm_name -> resolved_path
    pip_args: list[str] = []

    for pkg in packages:
        resolved = Path(pkg).expanduser().resolve()
        if resolved.is_dir() and (
            (resolved / "pyproject.toml").exists() or (resolved / "setup.py").exists()
        ):
            meta = parse_pyproject_name(resolved)
            if meta:
                norm = normalize_name(meta[0])
                local_packages[norm] = str(resolved)
                pip_args.append(str(resolved))
            else:
                # Can't determine name — still pass to pip, just won't be tracked as local
                error(f"Could not parse package name from {resolved}/pyproject.toml")
                pip_args.append(str(resolved))
        else:
            pip_args.append(pkg)

    return pip_args, local_packages


# -- RECORD parsing for removal --

def parse_record(dist_info_path: Path) -> list[str]:
    """Parse RECORD file to get list of installed file paths (relative to target)."""
    record_file = dist_info_path / "RECORD"
    if not record_file.exists():
        return []

    files = []
    for line in record_file.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        # RECORD format: filepath,hash,size
        parts = line.split(",")
        if parts:
            filepath = parts[0]
            if filepath:
                files.append(filepath)
    return files


def remove_package_files(target_path: Path, dist_info_name: str) -> int:
    """Remove all files for a package using its RECORD. Returns count of files removed."""
    dist_info_path = target_path / dist_info_name
    files = parse_record(dist_info_path)

    removed = 0
    dirs_to_check = set()

    for rel_path in files:
        full_path = target_path / rel_path
        if full_path.is_file():
            full_path.unlink()
            removed += 1
            dirs_to_check.add(full_path.parent)

    # Remove the .dist-info directory itself
    if dist_info_path.is_dir():
        import shutil
        shutil.rmtree(dist_info_path)
        removed += 1

    # Prune empty parent directories (but never remove target_path itself)
    for d in sorted(dirs_to_check, key=lambda p: len(p.parts), reverse=True):
        try:
            if d != target_path and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass

    return removed


# -- Find .dist-info for a package name --

def find_dist_info(target_path: Path, package_name: str) -> Path | None:
    """Find the .dist-info directory for a given package name."""
    norm = normalize_name(package_name)
    if not target_path.is_dir():
        return None
    for child in target_path.iterdir():
        if not (child.is_dir() and child.name.endswith(".dist-info")):
            continue
        # dist-info names look like: numpy-2.4.0.dist-info
        dir_name = child.name[: -len(".dist-info")]
        # Split on last hyphen to separate name from version
        parts = dir_name.rsplit("-", 1)
        if parts and normalize_name(parts[0]) == norm:
            return child
    return None


# -- pip operations --

def pip_install(packages: list[str], target_path: Path) -> subprocess.CompletedProcess:
    """Run pip install --target for the given packages."""
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--no-user", "--upgrade",
        f"--target={target_path}",
        *packages,
    ]
    info(f"Running: {' '.join(cmd)}\n")
    return subprocess.run(cmd, capture_output=False)


# -- High-level install orchestration --

def do_install(db: Database, packages: list[str], target_path: Path) -> bool:
    """Run the full install flow. Returns True on success."""
    # Resolve local paths: separate into pip args and local-package mapping
    pip_args, local_packages = resolve_local_packages(packages)

    # Build a name->original_arg mapping for pre-flight lookups
    # For local packages, use the resolved name; for PyPI, use the arg as-is
    name_to_arg: dict[str, str] = {}
    for pkg in pip_args:
        resolved = Path(pkg).expanduser().resolve()
        if str(resolved) in local_packages.values():
            # Find the norm name for this path
            for norm, path in local_packages.items():
                if path == str(resolved):
                    name_to_arg[norm] = pkg
                    break
        else:
            name_to_arg[normalize_name(pkg)] = pkg

    # Pre-flight checks
    from py_trkpac.utils import confirm as _confirm
    to_install = []
    for norm, original_arg in name_to_arg.items():
        # Check if package exists in system Python (e.g. managed by apt)
        if norm not in local_packages:
            sys_pkg = check_system_package(norm)
            if sys_pkg:
                sys_name, sys_ver = sys_pkg
                info(
                    f"Warning: {sys_name}=={sys_ver} is installed in system "
                    f"Python ({SYSTEM_DIST_PACKAGES}). "
                    f"Installing will shadow the system version."
                )
                if not _confirm(f"Proceed with installing {norm}?", default_yes=False):
                    info(f"Skipping {norm}.")
                    continue

        existing = db.get_package(norm)
        if existing:
            dependents = db.get_dependents(existing["id"])
            if existing["is_explicit"]:
                info(f"{existing['display_name']}=={existing['version']} is already installed.")
                from py_trkpac.utils import prompt_choice
                choice = prompt_choice(
                    f"What would you like to do with {existing['display_name']}?",
                    ["Upgrade/reinstall", "Keep current"],
                )
                if choice is None:
                    info("Cancelled.")
                    return False
                if choice == "Keep current":
                    continue
            else:
                dep_names = ", ".join(d["display_name"] for d in dependents)
                info(
                    f"{existing['display_name']}=={existing['version']} "
                    f"is installed as a dependency for: {dep_names}"
                )
                from py_trkpac.utils import prompt_choice
                choice = prompt_choice(
                    f"What would you like to do with {existing['display_name']}?",
                    ["Promote to explicit + upgrade", "Keep as dependency"],
                )
                if choice is None:
                    info("Cancelled.")
                    return False
                if choice == "Keep as dependency":
                    continue
        to_install.append(original_arg)

    if not to_install:
        info("Nothing to install.")
        return True

    # Snapshot before
    before = snapshot_dist_infos(target_path)

    # Run pip
    result = pip_install(to_install, target_path)
    if result.returncode != 0:
        error("pip install failed. Database not modified.")
        return False

    # Snapshot after and diff
    after = snapshot_dist_infos(target_path)
    changed = diff_dist_infos(before, after)

    if not changed:
        info("No packages changed on disk.")
        return True

    # Record all new/changed packages in DB
    requested_names = set(name_to_arg.keys())
    installed_packages = {}  # norm_name -> (package_id, meta)

    for dist_info_name in changed:
        dist_path = target_path / dist_info_name
        meta = parse_metadata(dist_path)
        if not meta["name"] or not meta["version"]:
            continue

        norm = normalize_name(meta["name"])
        is_explicit = norm in requested_names
        is_local = norm in local_packages
        source_path = local_packages.get(norm)
        pkg_id = db.upsert_package(
            name=meta["name"],
            display_name=meta["name"],
            version=meta["version"],
            is_explicit=is_explicit,
            is_local=is_local,
            source_path=source_path,
        )
        installed_packages[norm] = (pkg_id, meta)

    # Build dependency relationships
    for norm, (pkg_id, meta) in installed_packages.items():
        dep_ids = []
        for req in meta["requires_dist"]:
            dep_name = parse_dependency_name(req)
            if dep_name is None:
                continue
            dep_pkg = db.get_package(dep_name)
            if dep_pkg:
                dep_ids.append(dep_pkg["id"])
        db.set_dependencies(pkg_id, dep_ids)

    # Summary
    info(f"\nInstalled/updated {len(changed)} package(s):")
    for dist_info_name in sorted(changed):
        dist_path = target_path / dist_info_name
        meta = parse_metadata(dist_path)
        norm = normalize_name(meta["name"] or "")
        marker = "*" if norm in requested_names else " "
        local_marker = " (local)" if norm in local_packages else ""
        info(f"  {marker} {meta['name']}=={meta['version']}{local_marker}")
    info("(* = explicitly requested)")

    return True


def do_remove(db: Database, packages: list[str], target_path: Path) -> bool:
    """Run the full remove flow. Returns True on success."""
    from py_trkpac.utils import confirm

    for pkg in packages:
        existing = db.get_package(pkg)
        if not existing:
            error(f"{pkg} is not installed.")
            continue

        # Check dependents
        dependents = db.get_dependents(existing["id"])
        if dependents:
            dep_names = ", ".join(d["display_name"] for d in dependents)
            info(f"{existing['display_name']} is required by: {dep_names}")
            if not confirm(f"Remove {existing['display_name']} anyway?", default_yes=False):
                info(f"Skipping {existing['display_name']}.")
                continue

        # Find and remove files
        dist_info = find_dist_info(target_path, existing["name"])
        if dist_info:
            removed = remove_package_files(target_path, dist_info.name)
            info(f"Removed {removed} files for {existing['display_name']}.")
        else:
            info(f"Warning: .dist-info not found for {existing['display_name']} on disk.")

        # Remove from DB (CASCADE deletes dependency rows)
        db.remove_package(existing["name"])
        info(f"Removed {existing['display_name']}=={existing['version']} from database.")

    # Recursive orphan cleanup — peel off one layer at a time
    while True:
        orphans = db.get_orphaned_dependencies()
        if not orphans:
            break
        info("\nThe following packages are no longer needed by anything:")
        for o in orphans:
            info(f"  {o['display_name']}=={o['version']}")
        if not confirm("Remove them?"):
            break
        for o in orphans:
            dist_info = find_dist_info(target_path, o["name"])
            if dist_info:
                remove_package_files(target_path, dist_info.name)
            db.remove_package(o["name"])
            info(f"  Removed {o['display_name']}")

    return True


def do_update(db: Database, packages: list[str] | None, target_path: Path) -> bool:
    """Update packages. If packages is None/empty, update all explicit packages."""
    if packages:
        to_update = []
        for pkg in packages:
            existing = db.get_package(pkg)
            if not existing:
                error(f"{pkg} is not installed.")
                continue
            if existing["is_local"]:
                info(
                    f"{existing['display_name']} is a local install. "
                    f"Reinstall from source path: py-trkpac install {existing['source_path']}"
                )
                continue
            to_update.append(existing["display_name"])
    else:
        explicit = db.get_explicit_packages()
        # Skip local packages — they need explicit reinstall from source path
        explicit = [p for p in explicit if not p["is_local"]]
        if not explicit:
            info("No explicit packages to update.")
            return True
        to_update = [p["display_name"] for p in explicit]
        info(f"Updating {len(to_update)} explicit package(s)...")

    if not to_update:
        return True

    # Use the same install flow — pip --upgrade handles version checking
    return do_install(db, to_update, target_path)
