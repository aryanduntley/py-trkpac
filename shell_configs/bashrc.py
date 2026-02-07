"""Bash shell configuration handler for Ubuntu/Debian."""

# This module is a placeholder for future refactoring where shell-specific
# logic moves out of shell.py into per-shell modules.
#
# For v1, all bash logic lives in src/py_trkpac/shell.py.
# This file exists to establish the pattern for future OS support.
#
# Shell config path: ~/.bashrc
# Marker format:
#   # >>> py-trkpac managed >>>
#   export PATH="<target>/bin:$PATH"
#   export PYTHONPATH="<target>${PYTHONPATH:+:$PYTHONPATH}"
#   # <<< py-trkpac managed <<<

SHELL_NAME = "bash"
DEFAULT_CONFIG_PATH = "~/.bashrc"
