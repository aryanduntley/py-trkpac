"""Name normalization, user prompts, and formatting helpers."""

from __future__ import annotations

import re
import sys


def normalize_name(name: str) -> str:
    """Normalize package name: lowercase, replace hyphens/dots with underscores.

    Follows PEP 503 normalization rules.
    """
    return re.sub(r"[-_.]+", "_", name).lower()


def prompt_choice(message: str, choices: list[str]) -> str | None:
    """Prompt the user to pick from a list of choices. Returns the choice or None on cancel.

    choices: list of short labels like ["Upgrade", "Keep current"]
    Cancel is always appended automatically.
    """
    all_choices = choices + ["Cancel"]
    labels = [f"[{i + 1}] {c}" for i, c in enumerate(all_choices)]
    print(f"\n{message}")
    for label in labels:
        print(f"  {label}")

    while True:
        raw = input("Choice: ").strip().lower()
        if raw in ("c", "cancel", str(len(all_choices))):
            return None
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass
        print("Invalid choice. Try again.")


def confirm(message: str, default_yes: bool = True) -> bool:
    """Simple y/n confirmation. Returns True/False. 'c' or 'cancel' returns False."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    raw = input(f"{message} {suffix} ").strip().lower()
    if raw in ("c", "cancel"):
        return False
    if raw == "":
        return default_yes
    return raw in ("y", "yes")


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a simple formatted table to stdout."""
    if not rows:
        print("  (none)")
        return

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "  ".join("-" * col_widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rows:
        print("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))


def error(message: str) -> None:
    """Print an error message to stderr."""
    print(f"Error: {message}", file=sys.stderr)


def info(message: str) -> None:
    """Print an info message."""
    print(message)
