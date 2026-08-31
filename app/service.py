import logging
from pathlib import Path
from typing import Callable

from .folders import locate_company_folder, monthly_folders
from .models import Company
from .providers.base import Provider
from .security import unprotect


def safe_filename(name: str) -> str:
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError(f"Nome de arquivo inválido: {name}")
    return name


class BatchService:
    def __init__(self, provider: Provider, logger: logging.Logger):
        self.provider, self.logger = provider, logger

    def run(self, companies: list[Company], root: Path, year: int, month: int,
            status: Callable[[int, int, str], None], directions: set[str],
            result: Callable[[Company, str, str, dict[str, str]], None] | None = None) -> tuple[int, int, int]:
        active = [c for c in companies if c.active]
        successes = empty = failures = 0
        for index, company in enumerate(active, 1):
            paths = {"Pasta pesquisada": str(root)}
            status(index - 1, len(active), f"Processando {company.legal_name}")
            try:
                if len(company.cnpj) != 14 or not company.cnpj.isdigit():
                    raise ValueError("CNPJ deve conter 14 dígitos")
                if not company.certificate_path.is_file():
                    raise FileNotFoundError(f"Certificado não encontrado: {company.certificate_path}")
                company_folder = locate_company_folder(root, company.cnpj, company.legal_name)
                paths["Empresa"] = str(company_folder)
                password = unprotect(company.encrypted_password)
                documents = list(self.provider.download(company, password, year, month, directions))
                if not documents:
                    self.logger.warning("SEM NOTAS | %s | %s", company.cnpj, company.legal_name)
                    if result: result(company, "empty", "Nenhuma nota encontrada; conferir no portal", paths)
                    empty += 1
                    status(index, len(active), f"Sem notas: {company.legal_name}")
                    continue
                targets = monthly_folders(company_folder, year, month, directions)
                paths.update({direction: str(folder) for direction, folder in targets.items()})
                count = 0
                for document in documents:
                    if document.direction not in targets:
                        raise ValueError(f"Direção inválida: {document.direction}")
                    destination_folder = targets[document.direction]
                    if document.relative_folder:
                        if document.relative_folder != "Eventos":
                            raise ValueError(f"Subpasta inválida: {document.relative_folder}")
                        destination_folder = destination_folder / document.relative_folder
                        destination_folder.mkdir(exist_ok=True)
                    (destination_folder / safe_filename(document.filename)).write_bytes(document.content)
                    count += 1
                self.logger.info("OK | %s | %d arquivo(s)", company.cnpj, count)
                if result: result(company, "success", f"{count} arquivo(s) baixado(s)", paths)
                successes += 1
            except Exception as exc:
                self.logger.error("ERRO | %s | %s | %s", company.cnpj, company.legal_name, exc)
                if result: result(company, "error", str(exc), paths)
                failures += 1
            status(index, len(active), f"Concluída: {company.legal_name}")
        return successes, empty, failures
