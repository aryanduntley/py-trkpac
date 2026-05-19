"""CLI entry point: argparse setup and command dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from py_trkpac import __version__
from py_trkpac.db import open_db, init_db, find_db
from py_trkpac.health import check_python_version
from py_trkpac.installer import do_install, do_remove, do_update, do_rebuild
from py_trkpac.shell import add_to_shell, update_shell, write_launcher
from py_trkpac.utils import info, error, print_table, confirm


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize py-trkpac: set target directory, create DB, update shell config."""
    home = Path.home()
    default_target = home / "python-libraries"
    default_shell = home / ".bashrc"

    # Check if already initialized
    existing = find_db()
    if existing and not args.force:
        info(f"py-trkpac is already initialized (DB: {existing})")
        info("Use --force to reinitialize.")
        return 0

    # When --force is used with an existing DB, surface the current state
    # so the user knows exactly what they're re-initializing over.
    existing_target = None
    existing_pkg_count = 0
    if existing and args.force:
        try:
            old_db = open_db(existing)
            existing_target = old_db.get_config("target_path")
            existing_pkg_count = len(old_db.get_all_packages())
            old_db.close()
        except Exception:
            pass

    # Get target path
    if args.target:
        target_path = Path(args.target).expanduser().resolve()
    else:
        raw = input(f"Target directory for packages [{default_target}]: ").strip()
        if raw.lower() in ("c", "cancel"):
            info("Cancelled.")
            return 0
        target_path = Path(raw).expanduser().resolve() if raw else default_target

    # Get shell config path
    shell_config = Path(args.shell_config) if args.shell_config else default_shell

    if existing and args.force:
        info(f"\nExisting py-trkpac installation:")
        info(f"  database:         {existing}")
        if existing_target:
            info(f"  current target:   {existing_target}")
        info(f"  tracked packages: {existing_pkg_count}")
        info(f"\nReinitializing will:")
        info(f"  * create/replace the DB at: {target_path}/.py-trkpac.db")
        info(f"  * rewrite the managed block in: {shell_config}")
        if existing_target and str(Path(existing_target).resolve()) != str(target_path):
            info(
                f"  * leave the old target directory stranded "
                f"(py-trkpac will no longer see its packages):\n"
                f"      {existing_target}"
            )
    else:
        info(f"Target directory: {target_path}")
        info(f"Shell config:     {shell_config}")

    default_yes = not (existing and args.force)
    if not confirm("Proceed?", default_yes=default_yes):
        info("Cancelled.")
        return 0

    # Create DB
    db = init_db(target_path, shell_config)
    info(f"Database created: {db.db_path}")

    # Update shell config
    if add_to_shell(str(target_path), shell_config):
        info(f"Updated {shell_config} with PATH and PYTHONPATH entries.")
    else:
        info(f"{shell_config} already has py-trkpac entries.")

    # Install the resilient launcher. pip's generated console-script pins a
    # hard `#!/usr/bin/python3.X` shebang that dangles when the OS upgrades
    # Python; this launcher delegates to whatever python3 is current and
    # points PYTHONPATH at wherever py-trkpac actually lives right now (a
    # standalone dir, the managed dir, or a source checkout) so it does not
    # clobber an existing standalone install.
    if not args.no_launcher:
        import py_trkpac
        import_root = Path(py_trkpac.__file__).resolve().parent.parent
        launcher_path, status = write_launcher(str(import_root))
        if status == "unchanged":
            info(f"Launcher already current: {launcher_path}")
        elif status == "replaced":
            info(
                f"Replaced launcher at {launcher_path} "
                f"(backup: {launcher_path}.py-trkpac-backup) — "
                f"now Python-upgrade resilient (loads from {import_root})."
            )
        else:
            info(
                f"Installed Python-upgrade-resilient launcher: "
                f"{launcher_path} (loads from {import_root})"
            )
        if import_root.match("*/lib/python3.*/site-packages"):
            info(
                "Note: py-trkpac is in a version-pinned site-packages dir. "
                "For upgrade resilience, install it standalone (install.sh) "
                "or into the managed dir (`py-trkpac install py-trkpac`)."
            )

    db.close()
    info("\npy-trkpac initialized. Open a new terminal for PATH changes to take effect.")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """Install one or more packages."""
    if not args.packages:
        error("No packages specified.")
        return 1

    db = open_db()
    target_path = Path(db.get_config("target_path"))

    success = do_install(db, args.packages, target_path)
    db.close()
    return 0 if success else 1


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove one or more packages."""
    if not args.packages:
        error("No packages specified.")
        return 1

    db = open_db()
    target_path = Path(db.get_config("target_path"))

    success = do_remove(db, args.packages, target_path)
    db.close()
    return 0 if success else 1


def cmd_list(args: argparse.Namespace) -> int:
    """List installed packages."""
    db = open_db()
    packages = db.get_all_packages()

    if not packages:
        info("No packages installed.")
        db.close()
        return 0

    rows = []
    for p in packages:
        if p["is_local"]:
            kind = "local"
        elif p["is_explicit"]:
            kind = "explicit"
        else:
            kind = "dependency"
        date = p["install_date"][:10] if p["install_date"] else ""
        rows.append([p["display_name"], p["version"], kind, date])

    print_table(["Package", "Version", "Type", "Installed"], rows)

    local_count = sum(1 for p in packages if p["is_local"])
    explicit_count = sum(1 for p in packages if p["is_explicit"] and not p["is_local"])
    dep_count = len(packages) - explicit_count - local_count
    parts = []
    if explicit_count:
        parts.append(f"{explicit_count} explicit")
    if local_count:
        parts.append(f"{local_count} local")
    if dep_count:
        parts.append(f"{dep_count} dependencies")
    info(f"\n{len(packages)} package(s): {', '.join(parts)}")

    db.close()
    return 0


def cmd_list_deps(args: argparse.Namespace) -> int:
    """List dependencies for a package."""
    db = open_db()
    pkg = db.get_package(args.package)
    if not pkg:
        error(f"{args.package} is not installed.")
        db.close()
        return 1

    # Direct dependencies
    deps = db.get_dependencies(pkg["id"])
    header = f"\n{pkg['display_name']}=={pkg['version']}"
    if pkg["is_local"]:
        header += f" (local: {pkg['source_path']})"
    header += " depends on:"
    info(header)
    if deps:
        for d in deps:
            info(f"  {d['display_name']}=={d['version']}")
    else:
        info("  (none)")

    # Reverse: what requires this package
    dependents = db.get_dependents(pkg["id"])
    info(f"\nRequired by:")
    if dependents:
        for d in dependents:
            info(f"  {d['display_name']}=={d['version']}")
    else:
        info("  (none)")

    db.close()
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update packages."""
    db = open_db()
    target_path = Path(db.get_config("target_path"))

    packages = args.packages if args.packages else None
    success = do_update(db, packages, target_path)
    db.close()
    return 0 if success else 1


def cmd_rebuild(args: argparse.Namespace) -> int:
    """Reinstall all tracked packages for the current Python interpreter."""
    db = open_db()
    target_path = Path(db.get_config("target_path"))

    success = do_rebuild(db, target_path)
    db.close()
    return 0 if success else 1


def cmd_config(args: argparse.Namespace) -> int:
    """Show or modify configuration."""
    db = open_db()

    if args.action == "set" and args.key and args.value:
        old_value = db.get_config(args.key)

        # target_path changes are high-impact: packages in the old directory
        # become invisible to py-trkpac and the shell config is rewritten.
        if args.key == "target_path":
            new_target = Path(args.value).expanduser().resolve()
            old_resolved = Path(old_value).resolve() if old_value else None
            pkg_count = len(db.get_all_packages())

            info(f"\nChanging target_path:")
            info(f"  old: {old_value}")
            info(f"  new: {new_target}")
            if old_resolved and old_resolved != new_target:
                info(
                    f"\nWarning: {pkg_count} tracked package(s) live under the "
                    f"old target. They will NOT be moved."
                )
                info(
                    f"  * the existing database ({old_value}/.py-trkpac.db) "
                    f"stays where it is"
                )
                info(
                    f"  * py-trkpac will point at the new target and see zero "
                    f"packages until you install into it"
                )
                info(
                    f"  * your shell config ({db.get_config('shell_config')}) "
                    f"will be rewritten to the new PATH/PYTHONPATH"
                )
                info(
                    f"  * to recover the old packages you must either switch "
                    f"back or move the directory contents manually"
                )
            if not confirm("Proceed?", default_yes=False):
                info("Cancelled.")
                db.close()
                return 0

        db.set_config(args.key, args.value)
        info(f"Config '{args.key}' updated: {old_value} -> {args.value}")

        # If target_path changed, update shell config
        if args.key == "target_path":
            shell_config = Path(db.get_config("shell_config"))
            update_shell(args.value, shell_config)
            info(f"Updated {shell_config}.")
    else:
        # Show all config
        info("py-trkpac configuration:")
        info(f"  target_path:  {db.get_config('target_path')}")
        info(f"  shell_config: {db.get_config('shell_config')}")
        info(f"  database:     {db.db_path}")

    db.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="py-trkpac",
        description="Global Python package manager with SQLite tracking",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize py-trkpac")
    p_init.add_argument("--target", help="Target directory for packages")
    p_init.add_argument("--shell-config", help="Path to shell config file (default: ~/.bashrc)")
    p_init.add_argument("--force", action="store_true", help="Reinitialize even if DB exists")
    p_init.add_argument(
        "--no-launcher",
        action="store_true",
        help="Do not (re)write the ~/.local/bin/py-trkpac launcher",
    )

    # install
    p_install = subparsers.add_parser("install", help="Install packages")
    p_install.add_argument("packages", nargs="+", help="Package names to install")

    # remove
    p_remove = subparsers.add_parser("remove", help="Remove packages")
    p_remove.add_argument("packages", nargs="+", help="Package names to remove")

    # list
    subparsers.add_parser("list", help="List installed packages")

    # list-deps
    p_list_deps = subparsers.add_parser("list-deps", help="List dependencies for a package")
    p_list_deps.add_argument("package", help="Package name")

    # update
    p_update = subparsers.add_parser("update", help="Update packages")
    p_update.add_argument("packages", nargs="*", help="Package names (omit for all explicit)")

    # rebuild
    subparsers.add_parser(
        "rebuild",
        help="Reinstall all packages for the current Python (after a Python upgrade)",
    )

    # config
    p_config = subparsers.add_parser("config", help="Show or modify configuration")
    p_config.add_argument("action", nargs="?", help="'set' to modify a config value")
    p_config.add_argument("key", nargs="?", help="Config key to set")
    p_config.add_argument("value", nargs="?", help="New value")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Warn early (before command output) if the interpreter changed since
    # packages were installed. Best-effort: a missing/locked DB just means
    # the command itself will report the real problem.
    if args.command != "init":
        try:
            _db = open_db()
            check_python_version(_db)
            _db.close()
        except Exception:
            pass

    dispatch = {
        "init": cmd_init,
        "install": cmd_install,
        "remove": cmd_remove,
        "list": cmd_list,
        "list-deps": cmd_list_deps,
        "update": cmd_update,
        "rebuild": cmd_rebuild,
        "config": cmd_config,
    }

    handler = dispatch.get(args.command)
    if handler:
        try:
            sys.exit(handler(args))
        except KeyboardInterrupt:
            info("\nAborted.")
            sys.exit(130)
        except EOFError:
            info("\nAborted.")
            sys.exit(130)
    else:
        parser.print_help()
        sys.exit(1)
