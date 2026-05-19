# py-trkpac

A global Python package manager for linux that wraps pip with SQLite tracking. Install packages into a single shared directory, accessible from any terminal without activating a venv.

## Why

Python's default tooling pushes you toward virtual environments for everything. That's fine for project-specific dependencies, but for packages you use everywhere (pytest, requests, httpx, etc.), you end up with dozens of venvs all containing the same libraries.

py-trkpac gives you a single managed directory for globally available Python packages. It:

- Installs packages via pip into one target directory
- Tracks every package and its dependencies in SQLite
- Enforces one version per package (no silent duplicates)
- Detects dependency conflicts before they happen
- Manages your shell config (PATH/PYTHONPATH) automatically
- Works on Ubuntu without fighting PEP 668 (`externally-managed-environment`)

You still use venvs for project-specific needs. py-trkpac handles the rest.

## Install

Requires Python 3.13+ (works on 3.14). No external dependencies — pure Python stdlib. Linux.

### Recommended: standalone installer

One command. Installs py-trkpac into a fixed, Python-version-independent location **outside** the directory it manages, with a launcher on your `PATH`. No pip-into-system, no PEP 668 (`externally-managed-environment`) fight, no chicken/egg, and it **survives Python minor-version upgrades** (e.g. 3.13 → 3.14) because py-trkpac is pure stdlib.

```bash
curl -fsSL https://raw.githubusercontent.com/aryanduntley/py-trkpac/main/install.sh | bash
py-trkpac init
```

Or from a clone (offline / inspect first):

```bash
git clone https://github.com/aryanduntley/py-trkpac.git
cd py-trkpac && ./install.sh
py-trkpac init
```

Installs the package to `~/.local/share/py-trkpac/` and a launcher at `~/.local/bin/py-trkpac` (override with `PY_TRKPAC_HOME` / `PY_TRKPAC_BIN`; the installer warns if `~/.local/bin` is not on your `PATH`). Remove it any time with `./uninstall.sh` — it never touches your managed packages or shell config.

### From source (for development)

For hacking on py-trkpac itself — runs straight from `src/`, so edits are live, and it is equally upgrade-proof:

```bash
git clone https://github.com/aryanduntley/py-trkpac.git
ln -s "$PWD/py-trkpac/py-trkpac" ~/.local/bin/py-trkpac
py-trkpac init
```

### Alternatives (pip)

These work but are **not upgrade-durable on their own** — a Python minor-version upgrade orphans a version-pinned `pip` install. Prefer the standalone installer above.

- **pipx** (isolated, PEP 668-friendly): `pipx install py-trkpac && py-trkpac init`. Run `pipx reinstall-all` after a Python upgrade.
- **pip --user**: Debian/Ubuntu enforce PEP 668, so this needs `--break-system-packages`:
  `pip install --user --break-system-packages py-trkpac && py-trkpac init`.
  `init` writes the resilient launcher, but the package still sits in a version-pinned `site-packages` — reinstall (or switch to the standalone installer) after a Python upgrade.
- **venv bootstrap → self-install into the managed dir** (pip-only, no git, upgrade-proof — but py-trkpac then lives *inside* the directory it manages):

  ```bash
  python3 -m venv /tmp/trkpac-bootstrap
  /tmp/trkpac-bootstrap/bin/pip install py-trkpac
  /tmp/trkpac-bootstrap/bin/py-trkpac init
  /tmp/trkpac-bootstrap/bin/py-trkpac install py-trkpac
  rm -rf /tmp/trkpac-bootstrap   # py-trkpac is now on PATH via the managed dir
  ```

After any install, if a later OS upgrade changes your Python minor version, see [Surviving Python upgrades](#surviving-python-upgrades) — `py-trkpac rebuild` reinstalls your managed packages for the new interpreter.

## Usage

### Initialize

```bash
py-trkpac init
py-trkpac init --target ~/my-python-libs
py-trkpac init --shell-config ~/.zshrc
```

Sets the target directory where packages will be installed. Creates the SQLite database and adds PATH/PYTHONPATH entries to your shell config using managed marker comments.

### Install packages

```bash
py-trkpac install requests httpx pytest
```

- Checks the database for existing packages before installing
- Warns if a package is already installed in system Python (`/usr/lib/python3/dist-packages/`) and asks before shadowing it
- Prompts on version conflicts or when a package is already installed as a dependency
- Runs pip with `--target` and `--upgrade`
- Records all installed packages and auto-detected dependencies in the database
- Only updates the database after pip reports success

### Install local projects

```bash
py-trkpac install /path/to/downloaded-project
py-trkpac install ~/Desktop/Projects/my-mcp-server
```

- Detects local directories with `pyproject.toml` or `setup.py`
- Installs via pip into the same target directory as PyPI packages
- Parses `pyproject.toml` to identify the package name and track it in the database
- Tracks the source path so you know where each local package came from
- Shows as "local" type in `py-trkpac list`
- To update after source changes, just re-run the install command

### Remove packages

```bash
py-trkpac remove selenium
```

- Warns if other packages depend on the one being removed
- Cleans up files using pip's RECORD manifest
- Prompts to remove orphaned dependencies that nothing else needs, recursively through the full dependency tree

### List packages

```bash
py-trkpac list
```

```
Package          Version      Type        Installed
---------------  -----------  ----------  ----------
aifp             0.1.0        local       2026-02-07
click            8.3.1        explicit    2026-02-07
cryptography     46.0.4       explicit    2026-02-07
certifi          2026.1.4     dependency  2026-02-07
cffi             2.0.0        dependency  2026-02-07
...

63 package(s): 17 explicit, 1 local, 45 dependencies
```

### List dependencies

```bash
py-trkpac list-deps pytest
```

```
pytest==9.0.2 depends on:
  packaging==26.0
  iniconfig==2.3.0
  pluggy==1.6.0

Required by:
  pytest-cov==7.0.0
```

### Update packages

```bash
py-trkpac update           # update all explicit packages
py-trkpac update requests  # update a specific package
```

### Rebuild after a Python upgrade

```bash
py-trkpac rebuild
```

Reinstalls every tracked package — explicit **and** local — for the Python
interpreter you are running now. Use this after an OS upgrade bumps your
system Python to a new minor version (e.g. 3.13 → 3.14). It prunes the
stale, ABI-incompatible compiled extensions, reinstalls explicit packages
(pip re-resolves their dependencies), and reinstalls local packages from
their tracked source paths.

### View/change config

```bash
py-trkpac config
py-trkpac config set target_path /new/path
```

## Surviving Python upgrades

A Python **minor**-version upgrade (3.13 → 3.14) is the one event that can
break a global package directory. Compiled (C-extension) packages — numpy,
cryptography, pydantic-core, lxml, etc. — ship `.so` files locked to the
exact CPython minor version they were built for. When your OS replaces the
interpreter, every one of them stops importing. This is fundamental to
CPython and affects pip, venv, pipx, and conda equally; the only real fix
is to reinstall them for the new interpreter.

py-trkpac is built to make this a known, one-command recovery rather than a
cryptic failure:

- **It tells you.** py-trkpac records the Python version your packages were
  installed under. If you run any command under a different interpreter, it
  prints a prominent warning naming the old and new versions and pointing
  you at the fix. (Databases created before this feature are detected
  automatically by inspecting installed binaries.)
- **It fixes it in one command.** `py-trkpac rebuild` reinstalls everything
  for the current Python and prunes the dead binaries.
- **The tool itself never breaks.** py-trkpac is pure standard library, so
  it has no compiled parts to invalidate. The standalone installer (and
  `py-trkpac init`) write a launcher that delegates to whatever `python3`
  is current and points at wherever py-trkpac lives — never pip's
  version-pinned `console_scripts` stub. So the CLI keeps working across
  upgrades with zero intervention; only the *managed packages* need a
  `rebuild`.

> Tip: use the standalone installer (`install.sh`) — it places py-trkpac
> outside the managed directory in a version-independent location, so the
> CLI is upgrade-proof without living inside the folder it manages. A
> version-pinned `pip --user` install is the one setup that does *not*
> survive a Python upgrade; reinstall or switch installers if you used it.

## How it works

### Architecture

py-trkpac is a **policy layer** on top of pip. pip does all the real work (dependency resolution, downloading, building, installing). py-trkpac decides:

- Whether to install (conflict detection)
- Where to install (target directory)
- What to record (database tracking)
- When to prompt (user-facing decisions)

### Database

SQLite database stored at `<target_path>/.py-trkpac.db` with three tables:

- **config** — key/value settings (target path, shell config path)
- **packages** — every installed package (name, version, explicit vs dependency, dates)
- **package_dependencies** — many-to-many join table tracking which packages depend on which

Dependencies are packages too. numpy as a dependency of torch is a row in `packages` with `is_explicit=0`, linked via `package_dependencies`.

### Shell config management

py-trkpac manages a block in your shell config using marker comments:

```bash
# >>> py-trkpac managed >>>
export PATH="$HOME/python-libraries/bin:$PATH"
export PYTHONPATH="$HOME/python-libraries${PYTHONPATH:+:$PYTHONPATH}"
# <<< py-trkpac managed <<<
```

This block is added, updated, or removed idempotently. A backup of your shell config is created before the first modification.

### Package removal

Since `pip uninstall` doesn't work with `--target` installs, py-trkpac handles removal directly by parsing the RECORD file in each package's `.dist-info` directory and deleting the listed files.

## Project structure

```
py-trkpac/
├── install.sh                # standalone installer (recommended)
├── uninstall.sh              # reverses install.sh
├── py-trkpac                 # shell script entry point (dev/source use)
├── src/
│   └── py_trkpac/
│       ├── __init__.py       # version
│       ├── __main__.py       # python -m py_trkpac
│       ├── cli.py            # argparse, command dispatch
│       ├── db.py             # SQLite schema and operations
│       ├── installer.py      # pip wrapper, metadata parsing, rebuild
│       ├── shell.py          # .bashrc management + resilient launcher
│       ├── health.py         # Python-version tracking, upgrade warning
│       └── utils.py          # name normalization, prompts
├── shell_configs/            # future OS support stubs
│   ├── bashrc.py
│   ├── zshrc.py
│   └── fish.py
├── pyproject.toml
└── .gitignore
```

## License

MIT
