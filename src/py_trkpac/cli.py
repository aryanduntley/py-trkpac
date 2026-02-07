"""CLI entry point: argparse setup and command dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from py_trkpac import __version__
from py_trkpac.db import open_db, init_db, find_db
from py_trkpac.installer import do_install, do_remove, do_update
from py_trkpac.shell import add_to_shell, update_shell
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

    info(f"Target directory: {target_path}")
    info(f"Shell config:     {shell_config}")

    if not confirm("Proceed?"):
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
        kind = "explicit" if p["is_explicit"] else "dependency"
        date = p["install_date"][:10] if p["install_date"] else ""
        rows.append([p["display_name"], p["version"], kind, date])

    print_table(["Package", "Version", "Type", "Installed"], rows)

    explicit_count = sum(1 for p in packages if p["is_explicit"])
    dep_count = len(packages) - explicit_count
    info(f"\n{len(packages)} package(s): {explicit_count} explicit, {dep_count} dependencies")

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
    info(f"\n{pkg['display_name']}=={pkg['version']} depends on:")
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


def cmd_config(args: argparse.Namespace) -> int:
    """Show or modify configuration."""
    db = open_db()

    if args.action == "set" and args.key and args.value:
        old_value = db.get_config(args.key)
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

    # config
    p_config = subparsers.add_parser("config", help="Show or modify configuration")
    p_config.add_argument("action", nargs="?", help="'set' to modify a config value")
    p_config.add_argument("key", nargs="?", help="Config key to set")
    p_config.add_argument("value", nargs="?", help="New value")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "init": cmd_init,
        "install": cmd_install,
        "remove": cmd_remove,
        "list": cmd_list,
        "list-deps": cmd_list_deps,
        "update": cmd_update,
        "config": cmd_config,
    }

    handler = dispatch.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)
