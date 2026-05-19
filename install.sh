#!/usr/bin/env bash
# py-trkpac standalone installer.
#
# Installs py-trkpac into a fixed, Python-version-independent location
# OUTSIDE the directory it manages, plus a launcher on your PATH. No pip
# into system Python, no PEP 668 fight, no chicken/egg, survives Python
# minor-version upgrades (py-trkpac is pure stdlib).
#
# Usage:
#   ./install.sh                      # from a clone, or after download
#   curl -fsSL https://raw.githubusercontent.com/aryanduntley/py-trkpac/main/install.sh | bash
#
# Override locations:
#   PY_TRKPAC_HOME=~/.py-trkpac PY_TRKPAC_BIN=~/bin ./install.sh

set -euo pipefail

LIBDIR="${PY_TRKPAC_HOME:-$HOME/.local/share/py-trkpac}"
BINDIR="${PY_TRKPAC_BIN:-$HOME/.local/bin}"

command -v python3 >/dev/null 2>&1 || { echo "error: python3 not found on PATH" >&2; exit 1; }

# Resolve this script's directory (following symlinks) to detect a checkout.
SOURCE="${BASH_SOURCE[0]:-$0}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" 2>/dev/null && pwd || true)"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/src/py_trkpac/__init__.py" ]; then
    SRC_PKG="$SCRIPT_DIR/src/py_trkpac"
    VER="$(python3 -c "import sys; sys.path.insert(0,'$SCRIPT_DIR/src'); import py_trkpac; print(py_trkpac.__version__)")"
    echo "Installing py-trkpac $VER from local source ($SRC_PKG)"
else
    echo "Fetching py-trkpac from PyPI..."
    VER="$(python3 - "$STAGE" <<'PY'
import json, urllib.request, sys, io, zipfile
stage = sys.argv[1]
meta = json.load(urllib.request.urlopen("https://pypi.org/pypi/py-trkpac/json", timeout=30))
ver = meta["info"]["version"]
url = next((f["url"] for f in meta["releases"][ver]
            if f["filename"].endswith("-py3-none-any.whl")), None)
if url is None:
    sys.exit("no py3-none-any wheel found for py-trkpac on PyPI")
blob = io.BytesIO(urllib.request.urlopen(url, timeout=120).read())
with zipfile.ZipFile(blob) as z:
    for n in z.namelist():
        if n.startswith("py_trkpac/") and not n.endswith("/"):
            z.extract(n, stage)
print(ver)
PY
)"
    SRC_PKG="$STAGE/py_trkpac"
    echo "Installing py-trkpac $VER from PyPI"
fi

# Clean install into the standalone location.
rm -rf "$LIBDIR/py_trkpac"
mkdir -p "$LIBDIR"
cp -R "$SRC_PKG" "$LIBDIR/py_trkpac"
find "$LIBDIR/py_trkpac" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# Delegate launcher creation to the package itself so the file is byte
# identical to what `py-trkpac init` writes — keeping init idempotent.
LAUNCHER="$(PYTHONPATH="$LIBDIR" python3 - "$BINDIR" <<'PY'
import sys, pathlib
from py_trkpac.shell import write_launcher
import py_trkpac
root = pathlib.Path(py_trkpac.__file__).resolve().parent.parent
path, _status = write_launcher(str(root), pathlib.Path(sys.argv[1]))
print(path)
PY
)"

echo
echo "Installed:"
echo "  package:  $LIBDIR/py_trkpac"
echo "  launcher: $LAUNCHER"
echo

case ":${PATH}:" in
    *":$BINDIR:"*) ;;
    *) echo "WARNING: $BINDIR is not on your PATH. Add this to your shell rc:"
       echo "  export PATH=\"$BINDIR:\$PATH\""
       echo ;;
esac

echo "Next: run"
echo "  py-trkpac init"
echo "to set up the managed package directory, database, and shell config."
