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

```bash
# Clone the repo
git clone https://github.com/yourusername/py-trkpac.git ~/Desktop/Projects/py-trkpac

# Create a symlink (no pip install needed)
ln -s ~/Desktop/Projects/py-trkpac/py-trkpac ~/.local/bin/py-trkpac

# Initialize — sets target directory, creates DB, updates .bashrc
py-trkpac init
```

No external dependencies. Uses only Python stdlib (sqlite3, subprocess, argparse, pathlib, importlib.metadata).

Requires Python 3.13+.

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

### View/change config

```bash
py-trkpac config
py-trkpac config set target_path /new/path
```

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
├── py-trkpac                 # shell script entry point
├── src/
│   └── py_trkpac/
│       ├── __init__.py       # version
│       ├── __main__.py       # python -m py_trkpac
│       ├── cli.py            # argparse, command dispatch
│       ├── db.py             # SQLite schema and operations
│       ├── installer.py      # pip wrapper, metadata parsing
│       ├── shell.py          # .bashrc management
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
