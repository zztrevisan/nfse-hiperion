from collections.abc import Iterable
from xml.sax.saxutils import escape

from .base import Provider
from ..models import Company, DownloadedDocument


class SimulationProvider(Provider):
    def download(self, company: Company, password: str, year: int, month: int,
                 directions: set[str]) -> Iterable[DownloadedDocument]:
        for direction in ("Emitidas", "Recebidas"):
            if direction not in directions:
                continue
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<simulacao nfse="nao-e-documento-fiscal" cnpj="{escape(company.cnpj)}" '
                f'competencia="{year}-{month:02d}" direcao="{direction}" />\n'
            ).encode("utf-8")
            yield DownloadedDocument(direction, "SIMULACAO_NAO_FISCAL.xml", xml)
