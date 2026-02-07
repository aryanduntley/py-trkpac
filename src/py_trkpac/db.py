"""SQLite database: schema creation, config, package CRUD, dependency tracking."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from py_trkpac.utils import normalize_name

DB_FILENAME = ".py-trkpac.db"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS packages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    display_name TEXT NOT NULL,
    version      TEXT NOT NULL,
    is_explicit  INTEGER NOT NULL DEFAULT 0,
    install_date TEXT NOT NULL,
    updated_date TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_packages_name ON packages(name);

CREATE TABLE IF NOT EXISTS package_dependencies (
    package_id    INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    dependency_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    PRIMARY KEY (package_id, dependency_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Wrapper around the py-trkpac SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    # -- Schema --

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # -- Config --

    def get_config(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_config(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- Packages --

    def get_package(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM packages WHERE name = ?", (normalize_name(name),)
        ).fetchone()

    def get_all_packages(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM packages ORDER BY name"
        ).fetchall()

    def get_explicit_packages(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM packages WHERE is_explicit = 1 ORDER BY name"
        ).fetchall()

    def upsert_package(
        self,
        name: str,
        display_name: str,
        version: str,
        is_explicit: bool,
    ) -> int:
        """Insert or update a package. Returns the package id.

        If the package already exists:
        - version and updated_date are refreshed
        - is_explicit is promoted to 1 if requested, but never demoted
        """
        norm = normalize_name(name)
        existing = self.get_package(norm)
        if existing:
            # Never demote is_explicit from 1 to 0
            new_explicit = 1 if (existing["is_explicit"] or is_explicit) else 0
            self.conn.execute(
                "UPDATE packages SET version = ?, display_name = ?, "
                "is_explicit = ?, updated_date = ? WHERE id = ?",
                (version, display_name, new_explicit, _now(), existing["id"]),
            )
            self.conn.commit()
            return existing["id"]
        else:
            cur = self.conn.execute(
                "INSERT INTO packages (name, display_name, version, is_explicit, install_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (norm, display_name, version, int(is_explicit), _now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def remove_package(self, name: str) -> bool:
        """Remove a package by name. Returns True if it existed."""
        norm = normalize_name(name)
        cur = self.conn.execute("DELETE FROM packages WHERE name = ?", (norm,))
        self.conn.commit()
        return cur.rowcount > 0

    # -- Dependencies --

    def set_dependencies(self, package_id: int, dependency_ids: list[int]) -> None:
        """Replace all dependencies for a package."""
        self.conn.execute(
            "DELETE FROM package_dependencies WHERE package_id = ?", (package_id,)
        )
        for dep_id in dependency_ids:
            if dep_id == package_id:
                continue  # no self-references
            self.conn.execute(
                "INSERT OR IGNORE INTO package_dependencies (package_id, dependency_id) "
                "VALUES (?, ?)",
                (package_id, dep_id),
            )
        self.conn.commit()

    def get_dependencies(self, package_id: int) -> list[sqlite3.Row]:
        """Get packages that this package depends on."""
        return self.conn.execute(
            "SELECT p.* FROM packages p "
            "JOIN package_dependencies pd ON p.id = pd.dependency_id "
            "WHERE pd.package_id = ?",
            (package_id,),
        ).fetchall()

    def get_dependents(self, package_id: int) -> list[sqlite3.Row]:
        """Get packages that depend on this package ('required by')."""
        return self.conn.execute(
            "SELECT p.* FROM packages p "
            "JOIN package_dependencies pd ON p.id = pd.package_id "
            "WHERE pd.dependency_id = ?",
            (package_id,),
        ).fetchall()

    def get_orphaned_dependencies(self) -> list[sqlite3.Row]:
        """Find packages that are not explicit AND nothing depends on them."""
        return self.conn.execute(
            "SELECT p.* FROM packages p "
            "WHERE p.is_explicit = 0 "
            "AND p.id NOT IN ("
            "  SELECT dependency_id FROM package_dependencies"
            ")"
        ).fetchall()


def find_db() -> Path | None:
    """Try to find an existing py-trkpac database.

    Checks common locations in order:
    1. ~/python-libraries/.py-trkpac.db
    2. Walk known paths
    """
    home = Path.home()
    candidates = [
        home / "python-libraries" / DB_FILENAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def open_db(db_path: Path | None = None) -> Database:
    """Open the database. If no path given, try to find it."""
    if db_path is None:
        db_path = find_db()
    if db_path is None:
        raise FileNotFoundError(
            "No py-trkpac database found. Run 'py-trkpac init' first."
        )
    db = Database(db_path)
    return db


def init_db(target_path: Path, shell_config: Path) -> Database:
    """Create a new database at target_path and populate config."""
    target_path.mkdir(parents=True, exist_ok=True)
    db_path = target_path / DB_FILENAME
    db = Database(db_path)
    db.init_schema()
    db.set_config("target_path", str(target_path))
    db.set_config("shell_config", str(shell_config))
    return db
