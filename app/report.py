"""Relatório de faturamento mensal (saídas = Emitidas, entradas = Recebidas) a partir
dos XML já baixados em <raiz>\\<EMPRESA - DOC>\\AAAA\\MM\\...

Notas canceladas ou substituídas (eventos 101101 / 105102 / 105104 / 305101 ou descrição
com "cancel"/"substitu") aparecem no detalhe, mas não somam no faturamento.
"""
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .adn import _find, _block, _local

CANCEL_CODES = ("101101", "105102", "105104", "305101")
_FOLDER_DOC = re.compile(r"(?:^|- )([0-9A-Z]{14}|\d{11})$")


@dataclass
class NoteRow:
    company: str
    document: str
    period: str          # AAAA-MM (pasta)
    kind: str            # Saída | Entrada
    number: str
    date: str
    counterpart_doc: str
    counterpart: str
    service_value: float
    net_value: float
    iss: float
    iss_withheld: bool
    key: str
    status: str = "Ativa"


@dataclass
class Summary:
    out_count: int = 0
    out_value: float = 0.0
    out_iss: float = 0.0
    in_count: int = 0
    in_value: float = 0.0
    in_iss_withheld: float = 0.0
    cancelled: int = 0


def _num(text: str) -> float:
    try:
        return float((text or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _note_key(root: ET.Element) -> str:
    inf = _block(root, "infNFSe")
    key = (inf.get("Id") if inf is not None else "") or ""
    return re.sub(r"^NFS", "", re.sub(r"\W", "", key))


def _cancelled_keys(company_dir: Path) -> set[str]:
    keys = set()
    for path in company_dir.glob("*/*/Eventos/*.xml"):
        try:
            root = ET.fromstring(path.read_bytes())
        except ET.ParseError:
            continue
        tags = " ".join(_local(n.tag) for n in root.iter())
        desc = (_find(root, "xDesc") + " " + _find(root, "tpEvento")).lower()
        if any(c in tags or c in desc for c in CANCEL_CODES) or "cancel" in desc or "substitu" in desc:
            key = re.sub(r"\W", "", _find(root, "chNFSe"))
            if key:
                keys.add(key)
    return keys


def company_dirs(root: Path, only: set[str] | None = None) -> list[tuple[Path, str]]:
    result = []
    for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        m = _FOLDER_DOC.search(d.name)
        if m and (not only or m.group(1) in only):
            result.append((d, m.group(1)))
    return result


def collect(root: Path, start: str, end: str, only: set[str] | None = None) -> list[NoteRow]:
    rows = []
    for company_dir, doc in company_dirs(root, only):
        name = company_dir.name.rsplit(" - ", 1)[0] if " - " in company_dir.name else doc
        cancelled = _cancelled_keys(company_dir)
        for path in sorted(company_dir.glob("*/*/*/*.xml")):
            year, month, direction = path.parts[-4:-1]
            period = f"{year}-{month}"
            if direction not in ("Emitidas", "Recebidas") or not start <= period <= end:
                continue
            try:
                root_el = ET.fromstring(path.read_bytes())
            except ET.ParseError:
                continue
            other = _block(root_el, "toma", "tomador") if direction == "Emitidas" else _block(root_el, "emit", "prest")
            key = _note_key(root_el)
            rows.append(NoteRow(
                company=name, document=doc, period=period,
                kind="Saída" if direction == "Emitidas" else "Entrada",
                number=_find(root_el, "nNFSe", "nDPS"),
                date=(_find(root_el, "dCompet") or _find(root_el, "dhEmi"))[:10],
                counterpart_doc=re.sub(r"\W", "", _find(other, "CNPJ", "CPF")),
                counterpart=_find(other, "xNome", "xRazSoc", "xFant"),
                service_value=_num(_find(root_el, "vServ")),
                net_value=_num(_find(root_el, "vLiq")) or _num(_find(root_el, "vServ")),
                iss=_num(_find(root_el, "vISSQN")),
                iss_withheld=_find(root_el, "tpRetISSQN") == "2",
                key=key,
                status="Cancelada/Substituída" if key and key in cancelled else "Ativa",
            ))
    return rows


def summarize(rows: list[NoteRow]) -> dict[tuple[str, str, str], Summary]:
    out: dict[tuple[str, str, str], Summary] = defaultdict(Summary)
    for r in rows:
        s = out[(r.company, r.document, r.period)]
        if r.status != "Ativa":
            s.cancelled += 1
            continue
        if r.kind == "Saída":
            s.out_count += 1; s.out_value += r.service_value; s.out_iss += r.iss
        else:
            s.in_count += 1; s.in_value += r.service_value
            if r.iss_withheld:
                s.in_iss_withheld += r.iss
    return dict(sorted(out.items()))


def write_xlsx(path: Path, rows: list[NoteRow], start: str, end: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    money = '#,##0.00'
    bold, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E79")
    wb = Workbook()

    def sheet(ws, headers, data, money_cols, widths):
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill = bold, head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in data:
            ws.append(row)
        for col in money_cols:
            for cell in ws[get_column_letter(col)][1:]:
                cell.number_format = money
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    period = start if start == end else f"{start} a {end}"
    summary = summarize(rows)
    ws = wb.active; ws.title = "Resumo"
    data = [[name, doc, p, s.out_count, s.out_value, s.out_iss, s.in_count, s.in_value, s.in_iss_withheld,
             s.out_value - s.in_value, s.cancelled] for (name, doc, p), s in summary.items()]
    if data:
        n = len(data) + 1
        data.append(["TOTAL", "", period] + [f"=SUM({get_column_letter(c)}2:{get_column_letter(c)}{n})"
                                             for c in range(4, 12)])
    sheet(ws, ["Empresa", "CNPJ/CPF", "Competência", "Qtd saídas", "Faturamento (saídas)", "ISS das saídas",
               "Qtd entradas", "Valor entradas", "ISS retido nas entradas", "Saídas − entradas", "Canceladas"],
          data, [5, 6, 8, 9, 10], [40, 18, 12, 10, 18, 14, 11, 16, 16, 16, 11])
    if data:
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)

    ws = wb.create_sheet("Notas")
    sheet(ws, ["Empresa", "CNPJ/CPF", "Competência", "Tipo", "Número", "Data", "Doc. contraparte",
               "Contraparte", "Valor do serviço", "Valor líquido", "ISS", "ISS retido", "Situação", "Chave"],
          [[r.company, r.document, r.period, r.kind, r.number, r.date, r.counterpart_doc, r.counterpart,
            r.service_value, r.net_value, r.iss, "Sim" if r.iss_withheld else "Não", r.status, r.key]
           for r in rows], [9, 10, 11], [34, 16, 11, 8, 10, 11, 16, 34, 14, 14, 11, 9, 20, 52])
    wb.save(path)
