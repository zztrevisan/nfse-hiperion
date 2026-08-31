import re
import unicodedata
from pathlib import Path


def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def business_name_key(value: str) -> str:
    """Normaliza diferenças comuns entre razão social e nome da pasta fiscal."""
    words = normalize(value).split()
    removable = {"LTDA", "EPP", "ME", "MEI"}
    while words and words[-1] in removable:
        words.pop()
    return " ".join(words)


def legal_name_from_folder(folder: Path) -> str:
    return re.sub(r"^\s*\d+\s*-\s*", "", folder.name).strip()


def find_a1_certificate(company_folder: Path) -> Path:
    certificate_dirs = [item for item in company_folder.iterdir()
                        if item.is_dir() and normalize(item.name) == "CERTIFICADO DIGITAL"]
    if not certificate_dirs:
        raise FileNotFoundError("subpasta CERTIFICADO DIGITAL não encontrada")
    candidates = []
    for folder in certificate_dirs:
        candidates.extend(path for path in folder.rglob("*") if path.suffix.lower() in {".pfx", ".p12"})
    if not candidates:
        raise FileNotFoundError("nenhum certificado PFX/P12 encontrado")
    if len(candidates) > 1:
        raise RuntimeError("mais de um certificado PFX/P12 encontrado; selecione manualmente")
    return candidates[0]


def child_folder(parent: Path, expected_name: str) -> Path:
    """Encontra uma subpasta ignorando acentos, pontos e espaços extras."""
    if not parent.is_dir():
        raise FileNotFoundError(f"pasta não encontrada: {parent}")
    matches = [item for item in parent.iterdir()
               if item.is_dir() and normalize(item.name) == normalize(expected_name)]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(item.name for item in parent.iterdir() if item.is_dir()) or "(nenhuma)"
    if not matches:
        raise FileNotFoundError(
            f"subpasta '{expected_name}' não encontrada dentro de '{parent}'. Encontradas: {available}"
        )
    raise RuntimeError(f"mais de uma subpasta corresponde a '{expected_name}' dentro de '{parent}'")


def locate_company_folder(root: Path, cnpj: str, legal_name: str) -> Path:
    if not root.is_dir():
        raise FileNotFoundError(f"Pasta raiz não encontrada: {root}")
    wanted_cnpj = digits(cnpj)
    folders = [p for p in root.iterdir() if p.is_dir()]
    marker_matches = []
    for folder in folders:
        marker = folder / ".nfse-cnpj"
        if marker.is_file() and digits(marker.read_text(encoding="utf-8")) == wanted_cnpj:
            marker_matches.append(folder)
    if len(marker_matches) == 1:
        return marker_matches[0]
    if len(marker_matches) > 1:
        raise RuntimeError(f"CNPJ encontrado em mais de uma pasta: {wanted_cnpj}")

    wanted_name = business_name_key(legal_name)
    name_matches = []
    for folder in folders:
        name_without_box = legal_name_from_folder(folder)
        if business_name_key(name_without_box) == wanted_name:
            name_matches.append(folder)
    if len(name_matches) != 1:
        reason = "nenhuma" if not name_matches else "mais de uma"
        raise FileNotFoundError(f"{reason} pasta corresponde a {legal_name}")
    match = name_matches[0]
    (match / ".nfse-cnpj").write_text(wanted_cnpj, encoding="utf-8")
    return match


def monthly_folders(company_folder: Path, year: int, month: int,
                    directions: set[str] | None = None) -> dict[str, Path]:
    # A pasta da empresa deve existir e já ter sido localizada com segurança.
    # Dali para baixo, a estrutura fiscal pode ser criada quando estiver ausente.
    fiscal = company_folder / "02. FISCAL"
    files = fiscal / "ARQUIVOS"
    services = files / "SERVIÇOS"
    bases = {
        "Emitidas": services / "PRESTADOS" / "PORTAL NACIONAL",
        "Recebidas": services / "TOMADOS" / "PORTAL NACIONAL",
    }
    selected = directions or set(bases)
    bases = {key: folder for key, folder in bases.items() if key in selected}
    competence = f"{month:02d}.{year}"
    result = {direction: base / competence for direction, base in bases.items()}
    for folder in result.values():
        folder.mkdir(parents=True, exist_ok=True)
    return result
