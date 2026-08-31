import os
import sqlite3
from pathlib import Path

from .models import Company


def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "NFSeLote"
    root.mkdir(parents=True, exist_ok=True)
    return root


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "nfse.db"
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cnpj TEXT NOT NULL UNIQUE,
                legal_name TEXT NOT NULL,
                certificate_path TEXT NOT NULL,
                encrypted_password BLOB NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
        """)

    def setting(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.connection.commit()

    def companies(self) -> list[Company]:
        rows = self.connection.execute(
            "SELECT id,cnpj,legal_name,certificate_path,encrypted_password,active FROM companies ORDER BY legal_name"
        ).fetchall()
        return [Company(r[0], r[1], r[2], Path(r[3]), r[4], bool(r[5])) for r in rows]

    def save_company(self, company: Company) -> None:
        if company.id is None:
            self.connection.execute(
                "INSERT INTO companies(cnpj,legal_name,certificate_path,encrypted_password,active) VALUES(?,?,?,?,?)",
                (company.cnpj, company.legal_name, str(company.certificate_path), company.encrypted_password, company.active),
            )
        else:
            self.connection.execute(
                "UPDATE companies SET cnpj=?,legal_name=?,certificate_path=?,encrypted_password=?,active=? WHERE id=?",
                (company.cnpj, company.legal_name, str(company.certificate_path), company.encrypted_password, company.active, company.id),
            )
        self.connection.commit()

    def delete_company(self, company_id: int) -> None:
        self.connection.execute("DELETE FROM companies WHERE id=?", (company_id,))
        self.connection.commit()

