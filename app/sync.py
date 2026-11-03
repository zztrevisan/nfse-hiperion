"""Baixa a caixa de cada empresa da lista e arquiva os XML por data.

Estrutura: <raiz>\\<EMPRESA - CNPJ>\\<AAAA>\\<MM>\\<Emitidas|Recebidas|Outros|Eventos>\\<arquivo>.xml
A data da pasta é a competência da nota (ou a emissão, se não houver). O evento vai
para o mês da nota a que se refere; se a nota não for conhecida, para o mês do evento.
"""
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .adn import AdnClient, AdnError, NoProxyError, parse_event, parse_note
from .store import Company, Store


def safe(value: str, fallback: str, limit: int = 60) -> str:
    value = unicodedata.normalize("NFC", value or "")
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:limit].strip(" .") or fallback


def company_folder_name(c: Company) -> str:
    return f"{safe(c.name.upper(), '', 80)} - {c.document}" if c.name else c.document


def date_parts(date: str) -> tuple[str, str]:
    m = re.match(r"(\d{4})-(\d{2})", date or "")
    return (m.group(1), m.group(2)) if m else ("SEM DATA", "00")


@dataclass
class Result:
    document: str
    status: str        # ok | vazio | sem_procuracao | erro | cancelado
    new_files: int
    message: str
    folder: str = ""


class Syncer:
    def __init__(self, client: AdnClient, store: Store, root: Path,
                 log: Callable[[str], None] = print, cancelled: Callable[[], bool] = lambda: False):
        self.client, self.store, self.root, self.log, self.cancelled = client, store, Path(root), log, cancelled

    def run_one(self, document: str, from_zero: bool = False,
                progress: Callable[[int], None] = lambda n: None) -> Result:
        c = self.store.company(document)
        start = 0 if from_zero else c.last_nsu
        written = 0
        try:
            for highest, docs in self.client.batches(document, start, self.cancelled):
                if not c.name:  # descobre a razão social pela primeira nota em que a empresa aparece
                    for d in docs:
                        if d.kind != "EVENTO":
                            name = parse_note(d.xml, document).owner_name
                            if name:
                                c.name = name
                                break
                if not c.folder and docs:
                    c.folder = company_folder_name(c)
                base = self.root / c.folder if c.folder else None
                notes = []
                for d in docs:
                    rel, filename, note = self._place(document, d)
                    target = base / rel
                    target.mkdir(parents=True, exist_ok=True)
                    (target / filename).write_bytes(d.xml)
                    written += 1
                    if note:
                        notes.append(note)
                self.store.checkpoint(c, highest, notes)
                progress(written)
            if self.cancelled():
                return Result(document, "cancelado", written, f"interrompido no NSU {c.last_nsu}", c.folder)
        except NoProxyError as exc:
            return Result(document, "sem_procuracao", written,
                          f"sem procuração para o certificado — cadastrar no e-CAC ({exc})", c.folder)
        except AdnError as exc:
            return Result(document, "erro", written, str(exc), c.folder)
        except Exception as exc:  # XML quebrado, disco cheio etc.: registra e segue para a próxima empresa
            return Result(document, "erro", written, f"{type(exc).__name__}: {exc}", c.folder)
        if not c.last_sync:  # caixa vazia: marca a consulta mesmo sem documentos
            self.store.checkpoint(c, c.last_nsu, [])
        status = "ok" if written else "vazio"
        msg = f"{written} arquivo(s) novo(s), último NSU {c.last_nsu}" if written else "nada novo"
        return Result(document, status, written, msg, c.folder)

    def _place(self, owner: str, d) -> tuple[str, str, tuple[str, str, str] | None]:
        """Pasta relativa, nome do arquivo e, para nota, (chave, pasta, número) para o índice."""
        if d.kind == "EVENTO":
            ev = parse_event(d.xml)
            known = self.store.note(owner, ev.note_key) if ev.note_key else None
            if known:
                month_dir, number = str(Path(known[0]).parent), known[1]
            else:
                year, month = date_parts(ev.date)
                month_dir, number = str(Path(year) / month), "SEM-NUMERO"
            name = f"{safe(number, 'SEM-NUMERO', 20)}_{safe(ev.description, 'Evento', 40)}_{d.nsu}.xml"
            return str(Path(month_dir) / "Eventos"), name, None
        info = parse_note(d.xml, owner)
        year, month = date_parts(info.date)
        rel = str(Path(year) / month / info.direction)
        name = f"{safe(info.number, 'SEM-NUMERO', 20)}_{safe(info.counterpart, 'SEM-NOME', 50)}_{d.nsu}.xml"
        return rel, name, ((d.access_key, rel, info.number) if d.access_key else None)
