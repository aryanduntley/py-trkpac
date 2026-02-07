""".bashrc management: add/remove/update PYTHONPATH and PATH blocks."""

from __future__ import annotations

import shutil
from pathlib import Path

START_MARKER = "# >>> py-trkpac managed >>>"
END_MARKER = "# <<< py-trkpac managed <<<"


def _build_block(target_path: str) -> str:
    """Build the shell config block for a given target path."""
    # Use $HOME so it's portable if the user copies their bashrc
    home = Path.home()
    try:
        rel = Path(target_path).relative_to(home)
        path_expr = f"$HOME/{rel}"
    except ValueError:
        # target_path is not under $HOME, use absolute
        path_expr = target_path

    return (
        f"{START_MARKER}\n"
        f'export PATH="{path_expr}/bin:$PATH"\n'
        f'export PYTHONPATH="{path_expr}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
        f"{END_MARKER}"
    )


def _read_shell_config(config_path: Path) -> str:
    if not config_path.exists():
        return ""
    return config_path.read_text()


def _has_block(content: str) -> bool:
    return START_MARKER in content and END_MARKER in content


def _remove_block(content: str) -> str:
    """Remove the managed block from content."""
    lines = content.splitlines(keepends=True)
    result = []
    inside = False
    for line in lines:
        if line.rstrip() == START_MARKER:
            inside = True
            continue
        if line.rstrip() == END_MARKER:
            inside = False
            continue
        if not inside:
            result.append(line)
    return "".join(result)


def _backup(config_path: Path) -> Path | None:
    """Create a one-time backup of the shell config. Returns backup path or None if already backed up."""
    backup_path = config_path.parent / f"{config_path.name}.py-trkpac-backup"
    if not backup_path.exists() and config_path.exists():
        shutil.copy2(config_path, backup_path)
        return backup_path
    return None


def add_to_shell(target_path: str, config_path: Path) -> bool:
    """Add the py-trkpac block to the shell config. Returns True if modified."""
    content = _read_shell_config(config_path)
    if _has_block(content):
        return False

    _backup(config_path)

    block = _build_block(target_path)
    # Add a newline before block if file doesn't end with one
    if content and not content.endswith("\n"):
        content += "\n"
    content += f"\n{block}\n"
    config_path.write_text(content)
    return True


def remove_from_shell(config_path: Path) -> bool:
    """Remove the py-trkpac block from the shell config. Returns True if modified."""
    content = _read_shell_config(config_path)
    if not _has_block(content):
        return False

    content = _remove_block(content)
    config_path.write_text(content)
    return True


def update_shell(target_path: str, config_path: Path) -> bool:
    """Update the py-trkpac block with a new target path. Returns True if modified."""
    content = _read_shell_config(config_path)
    if _has_block(content):
        content = _remove_block(content)

    _backup(config_path)

    block = _build_block(target_path)
    if content and not content.endswith("\n"):
        content += "\n"
    content += f"\n{block}\n"
    config_path.write_text(content)
    return True
