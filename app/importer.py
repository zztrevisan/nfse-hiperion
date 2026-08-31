import csv
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ObjectIdentifier

CNPJ_OID = ObjectIdentifier("2.16.76.1.3.3")


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _xlsx_rows(path: Path):
    """Lê a primeira planilha XLSX sem exigir Excel ou bibliotecas adicionais."""
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")) for item in root]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        sheet = next(node for node in workbook.iter() if node.tag.endswith("}sheet"))
        rel_id = next(value for key, value in sheet.attrib.items() if key.endswith("}id"))
        target = targets[rel_id].lstrip("/")
        sheet_path = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(archive.read(sheet_path))
        for row in (node for node in root.iter() if node.tag.endswith("}row")):
            values = {}
            for cell in (node for node in row if node.tag.endswith("}c")):
                letters = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
                if not letters:
                    continue
                column = 0
                for char in letters.group(0):
                    column = column * 26 + ord(char) - 64
                value_node = next((node for node in cell.iter() if node.tag.endswith("}v")), None)
                inline = [node.text or "" for node in cell.iter() if node.tag.endswith("}t")]
                value = "".join(inline) if inline else (value_node.text if value_node is not None else "")
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                values[column - 1] = value
            if values:
                yield [values.get(index, "") for index in range(max(values) + 1)]


def read_sieg_companies(path: Path) -> list[dict[str, str]]:
    rows = iter(_xlsx_rows(path))
    try:
        headers = [_normalize(value) for value in next(rows)]
    except StopIteration:
        return []
    aliases = {"active": "ATIVO NA SIEG", "cnpj": "CNPJ CPF", "trade_name": "NOME FANTASIA",
               "legal_name": "RAZAO SOCIAL", "nickname": "APELIDO"}
    indexes = {key: headers.index(label) for key, label in aliases.items() if label in headers}
    if "cnpj" not in indexes:
        raise ValueError("a planilha não possui a coluna CNPJ/CPF")
    result = []
    for row in rows:
        get = lambda key: str(row[indexes[key]] or "").strip() if key in indexes and indexes[key] < len(row) else ""
        cnpj = _digits(get("cnpj"))
        if len(cnpj) != 14 or _normalize(get("active")) not in {"", "SIM"}:
            continue
        legal_name = get("legal_name") or get("trade_name") or get("nickname")
        if legal_name:
            result.append({"cnpj": cnpj, "legal_name": legal_name,
                           "trade_name": get("trade_name"), "nickname": get("nickname")})
    return result


def password_from_filename(path: Path) -> tuple[str, str]:
    match = re.search(r"\bsenha\s*[-:=]?\s*([^\s]+)", path.stem, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(" ._-"), "nome do arquivo"
    return "1234", "padrão 1234"


def certificate_cnpj(path: Path, password: str) -> str:
    key, cert, _ = pkcs12.load_key_and_certificates(path.read_bytes(), password.encode("utf-8"))
    if key is None or cert is None:
        raise ValueError("certificado sem chave privada")
    attrs = cert.subject.get_attributes_for_oid(CNPJ_OID)
    return _digits(attrs[0].value) if attrs else ""


@dataclass
class ImportItem:
    certificate: Path
    cnpj: str
    legal_name: str
    password: str
    password_source: str
    status: str
    detail: str


def scan_certificates(certificates_root: Path, companies: list[dict[str, str]]) -> list[ImportItem]:
    by_cnpj = {item["cnpj"]: item for item in companies}
    name_index = []
    for item in companies:
        names = {_normalize(item.get(key)) for key in ("legal_name", "trade_name", "nickname")}
        name_index.append((item, {name for name in names if name}))
    results = []
    certificates = sorted(path for path in certificates_root.rglob("*") if path.suffix.lower() in {".pfx", ".p12"})
    for certificate in certificates:
        password, source = password_from_filename(certificate)
        try:
            cert_cnpj = certificate_cnpj(certificate, password)
        except Exception:
            results.append(ImportItem(certificate, "", "", "", source, "ERRO", "senha inválida ou A1 ilegível"))
            continue
        company = by_cnpj.get(cert_cnpj)
        if company is None:
            context = _normalize(" ".join([certificate.stem] + [parent.name for parent in certificate.parents[:4]]))
            matches = [item for item, names in name_index if any(name and name in context for name in names)]
            company = matches[0] if len(matches) == 1 else None
        if company is None:
            results.append(ImportItem(certificate, cert_cnpj, "", "", source, "NÃO VINCULADO", "CNPJ/nome não encontrado na planilha"))
        else:
            detail = "CNPJ do certificado" if company["cnpj"] == cert_cnpj else "vínculo pelo nome da empresa"
            results.append(ImportItem(certificate, company["cnpj"], company["legal_name"], password, source, "PRONTO", detail))
    return results


def write_report(path: Path, items: list[ImportItem]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["Arquivo", "CNPJ", "Razão social", "Origem da senha", "Situação", "Detalhe"])
        for item in items:
            writer.writerow([str(item.certificate), item.cnpj, item.legal_name,
                             item.password_source, item.status, item.detail])
