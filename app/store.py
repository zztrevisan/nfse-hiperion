"""Estado local (SQLite em %LOCALAPPDATA%\\NFSeHiperion): configurações, último NSU por
empresa e índice chave → pasta das notas, usado para arquivar eventos junto da nota."""
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "NFSeHiperion"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Company:
    document: str
    name: str = ""
    folder: str = ""        # nome da pasta da empresa, fixado no primeiro download
    last_nsu: int = 0
    last_sync: str = ""


class Store:
    def __init__(self, path: Path | None = None):
        # check_same_thread=False: a UI lê e o worker grava, sempre um de cada vez.
        self.db = sqlite3.connect(path or data_dir() / "nfse.db", check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value BLOB);
            CREATE TABLE IF NOT EXISTS companies (
                document TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', folder TEXT NOT NULL DEFAULT '',
                last_nsu INTEGER NOT NULL DEFAULT 0, last_sync TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS notes (
                owner TEXT NOT NULL, access_key TEXT NOT NULL, relpath TEXT NOT NULL, number TEXT NOT NULL,
                PRIMARY KEY (owner, access_key));
        """)

    def get(self, key: str, default=""):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value) -> None:
        self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))
        self.db.commit()

    def company(self, document: str) -> Company:
        row = self.db.execute("SELECT document,name,folder,last_nsu,last_sync FROM companies WHERE document=?",
                              (document,)).fetchone()
        return Company(*row) if row else Company(document)

    def companies(self) -> dict[str, Company]:
        rows = self.db.execute("SELECT document,name,folder,last_nsu,last_sync FROM companies").fetchall()
        return {r[0]: Company(*r) for r in rows}

    def save_company(self, c: Company) -> None:
        self.db.execute(
            """INSERT INTO companies VALUES(?,?,?,?,?) ON CONFLICT(document) DO UPDATE SET
               name=excluded.name, folder=excluded.folder, last_nsu=excluded.last_nsu, last_sync=excluded.last_sync""",
            (c.document, c.name, c.folder, c.last_nsu, c.last_sync))
        self.db.commit()

    def checkpoint(self, c: Company, nsu: int, notes: list[tuple[str, str, str]]) -> None:
        """Grava o NSU do lote e as notas dele na mesma transação."""
        c.last_nsu, c.last_sync = nsu, datetime.now().isoformat(timespec="seconds")
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO notes VALUES(?,?,?,?)",
                                [(c.document, key, rel, num) for key, rel, num in notes])
            self.db.execute(
                """INSERT INTO companies VALUES(?,?,?,?,?) ON CONFLICT(document) DO UPDATE SET
                   name=excluded.name, folder=excluded.folder, last_nsu=excluded.last_nsu, last_sync=excluded.last_sync""",
                (c.document, c.name, c.folder, c.last_nsu, c.last_sync))

    def note(self, owner: str, access_key: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT relpath, number FROM notes WHERE owner=? AND access_key=?",
                              (owner, access_key)).fetchone()
        return (row[0], row[1]) if row else None
