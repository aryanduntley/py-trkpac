#!/usr/bin/env bash
# py-trkpac standalone uninstaller — reverses install.sh.
#
# Removes the standalone package and its launcher ONLY. It deliberately
# does NOT touch your managed package directory (~/python-libraries by
# default), its database, or your shell config — that is your data and is
# managed by py-trkpac itself. Steps to remove those are printed at the end.
#
#   PY_TRKPAC_HOME=~/.py-trkpac PY_TRKPAC_BIN=~/bin ./uninstall.sh

set -euo pipefail

LIBDIR="${PY_TRKPAC_HOME:-$HOME/.local/share/py-trkpac}"
BINDIR="${PY_TRKPAC_BIN:-$HOME/.local/bin}"
LAUNCHER="$BINDIR/py-trkpac"

if [ -f "$LAUNCHER" ] && grep -q "py-trkpac launcher (managed)" "$LAUNCHER" 2>/dev/null; then
    rm -f "$LAUNCHER"
    echo "Removed launcher: $LAUNCHER"
elif [ -L "$LAUNCHER" ]; then
    echo "Left $LAUNCHER alone (it is a symlink, not a standalone launcher)."
else
    echo "No standalone launcher at $LAUNCHER (nothing to remove)."
fi

if [ -d "$LIBDIR" ]; then
    rm -rf "$LIBDIR"
    echo "Removed package: $LIBDIR"
else
    echo "No standalone package at $LIBDIR."
fi

echo
echo "Left untouched (remove manually if desired):"
echo "  * managed packages + DB:  ~/python-libraries  (or your --target)"
echo "  * shell config block:     the '# >>> py-trkpac managed >>>' block"
echo "                            in ~/.bashrc (a .py-trkpac-backup exists)"
