from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Company:
    id: int | None
    cnpj: str
    legal_name: str
    certificate_path: Path
    encrypted_password: bytes
    active: bool = True


@dataclass(frozen=True)
class DownloadedDocument:
    direction: str
    filename: str
    content: bytes
    relative_folder: str = ""
